"""External drive routes; lifecycle endpoints intentionally removed."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.routers.auth import current_user, admin_user
from app.services import drive as service
from app.services import external_services as external

router = APIRouter(prefix='/drive', tags=['drive'], dependencies=[Depends(current_user)])

@router.get('/status')
def status(db: Session = Depends(get_db)):
    return service.get_status(db)

@router.get('/connection', dependencies=[Depends(admin_user)])
def connection(db: Session = Depends(get_db)):
    return external.masked_drive(external.load(db, 'drive'))

@router.put('/connection', dependencies=[Depends(admin_user)])
def save_connection(data: external.DriveConnection, db: Session = Depends(get_db)):
    try:
        external.save(db, 'drive', data.as_connection())
        return external.masked_drive(external.load(db, 'drive'))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

@router.post('/connection/test', dependencies=[Depends(admin_user)])
async def test_connection(data: external.DriveConnection, db: Session = Depends(get_db)):
    try:
        cfg = external.merge(db, 'drive', data.as_connection())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await external.probe('drive', cfg)

@router.post('/connection/token', dependencies=[Depends(admin_user)])
def reveal_token(db: Session = Depends(get_db)):
    return JSONResponse({'token': external.load(db, 'drive').token or ''},
        headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'Referrer-Policy': 'no-referrer'})

@router.get('/login-url')
def login_url(user=Depends(current_user), db: Session = Depends(get_db)):
    return JSONResponse(service.get_login_url(db, user.is_admin), headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})


# Only service cookies and OpenList's raw-token Authorization survive.
# Stella uses HttpOnly cookies, never forward these to an external service.
import asyncio
import httpx
from http.cookies import SimpleCookie
from urllib.parse import urlsplit, urljoin, quote
from fastapi.responses import Response, StreamingResponse

HOP = {'connection', 'keep-alive', 'transfer-encoding', 'upgrade', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailer'}


def proxy_headers(headers):
    blocked = HOP | {'host', 'cookie', 'authorization', 'origin', 'referer', 'accept-encoding'}
    blocked.update(x.strip().lower() for x in headers.get('connection', '').split(','))
    out = {k: v for k, v in headers.items() if k.lower() not in blocked and not k.lower().startswith('x-forwarded-')}
    cookies = SimpleCookie()
    try:
        cookies.load(headers.get('cookie', ''))
    except Exception:
        pass
    safe = [f'{k}={v.coded_value}' for k, v in cookies.items() if k.lower().startswith(('openlist_', 'alist_'))]
    if safe:
        out['cookie'] = '; '.join(safe)
    auth = headers.get('authorization', '')
    if auth and not auth.lower().startswith('bearer '):
        out['authorization'] = auth
    out['accept-encoding'] = 'identity'
    return out


@router.api_route('/openlist/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
async def openlist_proxy(path: str, request: Request, db: Session = Depends(get_db)):
    cfg = external.load(db, 'drive')
    if any(p in ('.', '..') for p in path.split('/')) or '\\' in path or '%' in path:
        raise HTTPException(400, '非法路径')
    base = (cfg.upstream_url or cfg.browser_url).rstrip('/')
    try:
        await asyncio.wait_for(asyncio.to_thread(external.check_resolved, base), 5)
    except (ValueError, OSError, TimeoutError):
        raise HTTPException(502, '上游地址不可用')
    url = base + '/' + quote(path, safe='/@:+,;=-._~')
    client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5), follow_redirects=False, trust_env=False)
    try:
        req = client.build_request(request.method, url, headers=proxy_headers(request.headers), params=request.query_params.multi_items(), content=request.stream())
        resp = await client.send(req, stream=True)
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(502, 'OpenList 上游连接失败')
    blocked = HOP | {'set-cookie'}
    blocked.update(x.strip().lower() for x in resp.headers.get('connection', '').split(','))
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in blocked}
    location = headers.get('location')
    if location:
        absolute = urljoin(url, location)
        if absolute == base or absolute.startswith(base + '/') or absolute.startswith(base + '?'):
            headers['location'] = '/drive/openlist' + absolute[len(base):]
        else:
            try:
                external.validate_url(absolute.split('?', 1)[0])
            except ValueError:
                headers.pop('location', None)
    headers['referrer-policy'] = 'no-referrer'
    headers['cache-control'] = 'no-store'
    if request.method != 'HEAD' and resp.status_code == 200 and 'text/html' in resp.headers.get('content-type', '') and not resp.headers.get('content-encoding'):
        try:
            body = await resp.aread()
            html = service.inject_theme_html(body.decode('utf-8', errors='replace'))
            headers.pop('content-length', None)
            headers.pop('etag', None)
            return Response(html, status_code=resp.status_code, headers=headers)
        finally:
            await resp.aclose()
            await client.aclose()
    async def chunks():
        try:
            async for chunk in resp.aiter_raw():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()
    return StreamingResponse(chunks(), status_code=resp.status_code, headers=headers)
