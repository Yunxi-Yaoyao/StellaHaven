"""OIDC Provider 路由：发现文档 / JWKS / 授权 / 令牌 / 用户信息。"""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import oidc as oidc_svc
from app.models.user import User
from app.routers import auth as auth_mod
from app.routers.auth import current_user

router = APIRouter(tags=["oidc"])


def _frontend_login(issuer: str) -> str:
    return f"{issuer}/login"


def _host_issuer(request: Request) -> str:
    host = request.headers.get("host", "")
    return oidc_svc.resolve_issuer(host)


def _optional_user(request: Request, response: Response, db: Session = Depends(get_db)):
    """可选登录态：已登录返回 User，未登录返回 None（不强制 401）。
    access token 过期但 refresh token 有效时自动续期（Set-Cookie 新 at）——
    authorize 是 iframe 裸 302 跳转，没有前端 JS 的 refreshAccess 兜底。"""
    try:
        return current_user(request, db)
    except HTTPException:
        pass
    try:
        return auth_mod.rotate_refresh(request, response, db)
    except HTTPException:
        return None


@router.get("/.well-known/openid-configuration")
def openid_configuration(request: Request):
    return oidc_svc.openid_configuration(_host_issuer(request))


@router.get("/oauth/jwks")
def jwks():
    return oidc_svc.jwks()


@router.get("/oauth/authorize")
def authorize(request: Request, response_type: str = "code", client_id: str = "",
              redirect_uri: str = "", scope: str = "openid", state: str = "",
              nonce: str = "", user: User | None = Depends(_optional_user)):
    issuer = _host_issuer(request)
    # 校验 client + redirect_uri
    if not oidc_svc._get_client(client_id):
        return JSONResponse({"error": "invalid_client", "error_description": "未知客户端"}, status_code=400)
    if not oidc_svc.verify_redirect_uri(client_id, redirect_uri):
        return JSONResponse({"error": "invalid_request", "error_description": "redirect_uri 不合法"}, status_code=400)
    if response_type != "code":
        return JSONResponse({"error": "unsupported_response_type"}, status_code=400)

    # 未登录 → 跳前端登录页，登录后回 authorize
    if user is None:
        next_url = str(request.url)
        return RedirectResponse(f"{_frontend_login(issuer)}?next={next_url}")

    # 已登录 → 直接发授权码
    code = oidc_svc.create_authorization_code(
        client_id=client_id, redirect_uri=redirect_uri,
        user_id=str(user.id), username=user.username,
        email=user.email or "", nonce=nonce or None,
        issuer=issuer,
    )
    params = {"code": code}
    if state:
        params["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}")


@router.post("/oauth/token")
def token(grant_type: str = Form(...), code: str = Form(None),
          client_id: str = Form(...), client_secret: str = Form(...),
          redirect_uri: str = Form(None)):
    if grant_type != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
    result = oidc_svc.exchange_code(code, client_id, client_secret, redirect_uri)
    if result is None:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    return result


@router.get("/oauth/userinfo")
def userinfo(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"error": "invalid_token"}, status_code=401)
    token = auth[len("Bearer "):]
    info = oidc_svc.userinfo(token)
    if info is None:
        return JSONResponse({"error": "invalid_token"}, status_code=401)
    return info
