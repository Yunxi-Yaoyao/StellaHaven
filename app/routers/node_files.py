"""Dedicated pull protocol, metadata JSON and bounded raw byte transfers."""
import hashlib
import json
import secrets
import time
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request, Query, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.security import agent_token
from app.routers.auth import current_user
from app.models.node import Node
from app.models.node_file import FileAgent, FileJob
from app.schemas.node_file import AgentHello, FileRequest, FileResult, AgentFilesConfig
from app.services import node_files as svc
from app.routers.node_files_release import router as release_router

router = APIRouter(prefix='/node-files', tags=['node-files'])
agent_router = APIRouter(prefix='/agent/files', tags=['agent-files'])
agent_router.include_router(release_router)


async def bounded_body(request):
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > svc.CHUNK_SIZE:
            raise HTTPException(413, 'transfer_limit')
        data.extend(chunk)
    return data


def identity(request, user):
    return user.id, request.state.auth_session.id


@router.get('/nodes')
def nodes(user=Depends(current_user), db: Session = Depends(get_db)):
    result = []
    policies = svc.policies(db)
    for node in db.scalars(select(Node).where(Node.status != 'removed')):
        roots = []
        agent = db.get(FileAgent, node.id)
        for root, policy in policies.get(str(node.id), {}).items():
            if str(user.id) in policy.get('owners', []):
                blocked = db.scalar(select(FileJob.id).where(FileJob.node_id == node.id, FileJob.root == root, FileJob.state == 'unknown').limit(1)) is not None
                roots.append({'id': root, 'label': policy.get('label', root), 'write': policy.get('write') is True and bool(agent and agent.roots.get(root)), 'blocked': blocked})
        if roots:
            result.append({'id': node.id, 'name': node.name, 'online': bool(node.status == 'online' and agent and time.time() - agent.seen <= 15), 'roots': roots})
    return result


@router.post('/requests', status_code=201)
def create(data: FileRequest, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    return svc.public(svc.create(db, *identity(request, user), data))


@router.get('/by-key/{request_key}')
def by_key(request_key: str, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    owner, session = identity(request, user)
    job = db.scalar(select(FileJob).where(FileJob.owner == str(owner), FileJob.session == str(session), FileJob.request_key == request_key))
    if job is None:
        raise HTTPException(404, 'request_not_found')
    job = svc.owned(db, job.id, owner, session)
    if svc.digest(svc.grant(owner, job.node_id, job.root, db)) != job.policy:
        raise HTTPException(409, 'authority_changed')
    return svc.public(job)


@router.get('/requests/{job_id}')
def read(job_id: str, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    job = svc.owned(db, job_id, *identity(request, user))
    if svc.digest(svc.grant(user.id, job.node_id, job.root, db)) != job.policy:
        raise HTTPException(409, 'authority_changed')
    return svc.public(job)


@router.post('/requests/{job_id}/cancel')
def cancel(job_id: str, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    job = svc.owned(db, job_id, *identity(request, user))
    if job.state in ('uploading', 'pending', 'running', 'committing'):
        job.state = 'unknown' if job.state in ('running', 'committing') and job.request['op'] in svc.WRITE_OPS else 'cancelled'
        job.error = 'cancelled'
        svc.spool(job).unlink(missing_ok=True)
        db.commit()
    return svc.public(job)


@router.get('/requests/{job_id}/download')
def download(job_id: str, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    job = svc.owned(db, job_id, *identity(request, user))
    if job.state != 'done' or job.request['op'] != 'download':
        raise HTTPException(409, 'download_not_ready')
    if svc.digest(svc.grant(user.id, job.node_id, job.root, db)) != job.policy:
        raise HTTPException(409, 'authority_changed')
    filename = job.request['path'].split('/')[-1]
    path = svc.spool(job)
    if not path.is_file() or path.stat().st_size != job.result['size']:
        raise HTTPException(410, 'download_expired')
    session_id = request.state.auth_session.id
    db.commit()
    def body():
        from app.models.user import AuthSession
        from app.services.session_policy import expired
        with path.open('rb') as source:
            while True:
                db.expire_all()
                session = db.get(AuthSession, session_id)
                if not session or session.revoked or expired(session) or svc.digest(svc.grant(user.id, job.node_id, job.root, db)) != job.policy:
                    return
                chunk = source.read(svc.CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk
    return StreamingResponse(body(), media_type='application/octet-stream', headers={'Content-Length': str(job.result['size']), 'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''), 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store', 'X-File-SHA256': job.result['sha256']})


@agent_router.get('/config', response_model=AgentFilesConfig)
def config(request: Request, response: Response, token: str = Depends(agent_token), db: Session = Depends(get_db)):
    # This new endpoint has no legacy query-token clients. Other file routes
    # retain their existing compatibility dependency unchanged.
    if request.headers.get('authorization') is None:
        raise HTTPException(401, 'invalid_agent')
    node = svc.node_agent(db, token)
    response.headers['Cache-Control'] = 'no-store'
    return svc.agent_config(db, node)


@agent_router.post('/claim')
def claim(hello: AgentHello, token: str = Depends(agent_token), db: Session = Depends(get_db)):
    node = svc.node_agent(db, token)
    agent = db.get(FileAgent, node.id)
    if agent is None:
        agent = FileAgent(node_id=node.id, seen=time.time(), roots=hello.roots)
        db.add(agent)
    else:
        agent.seen, agent.roots = time.time(), hello.roots
    db.commit()
    # Claimed operations are never reissued, even across worker/center restarts.
    for job in db.scalars(select(FileJob).where(FileJob.node_id == node.id, FileJob.state == 'pending').order_by(FileJob.expires).with_for_update(skip_locked=True)):
        if not svc.valid(db, job):
            continue
        job.state, job.lease = 'running', secrets.token_hex(24)
        db.commit()
        return {'id': job.id, 'lease': job.lease, 'request': job.request}
    return None


@agent_router.get('/requests/{job_id}')
def status(job_id: str, lease: str = Query(min_length=32, max_length=64), token: str = Depends(agent_token), db: Session = Depends(get_db)):
    node = svc.node_agent(db, token)
    job = svc.agent_job(db, job_id, node.id, lease)
    presence = db.get(FileAgent, node.id)
    if presence is not None:
        presence.seen = time.time()  # Authenticated in-flight worker, not stale idle presence.
    svc.valid(db, job)
    db.commit()
    return {'state': job.state}


@agent_router.put('/requests/{job_id}/bytes')
async def receive_bytes(job_id: str, request: Request, offset: int = Query(ge=0), lease: str = Query(min_length=32, max_length=64), token: str = Depends(agent_token), db: Session = Depends(get_db)):
    data = await bounded_body(request)
    return await run_in_threadpool(append_download_bytes, db, token, job_id, lease, offset, data)


def append_download_bytes(db, token, job_id, lease, offset, data):
    # PG locks and local IO must never run on the ASGI event loop.
    db.expire_all()
    node = svc.node_agent(db, token)
    job = svc.agent_job(db, job_id, node.id, lease)
    if not svc.valid(db, job) or job.request['op'] not in ('download', 'preview'):
        raise HTTPException(409, 'inactive_request')
    if offset + len(data) > (256 * 1024 if job.request['op'] == 'preview' else svc.TRANSFER_LIMIT):
        raise HTTPException(413, 'transfer_limit')
    if offset != job.bytes_received:
        raise HTTPException(409, 'offset_conflict')
    svc.spool_budget(db, len(data))
    with svc.spool(job).open('ab') as target:
        target.write(data)
    job.bytes_received += len(data)
    db.commit()
    return {'offset': job.bytes_received}


@agent_router.post('/requests/{job_id}/result')
def finish(job_id: str, data: FileResult, token: str = Depends(agent_token), db: Session = Depends(get_db)):
    node = svc.node_agent(db, token)
    job = svc.agent_job(db, job_id, node.id, data.lease)
    if job.state in ('done', 'failed'):
        return {'state': job.state}
    if not svc.valid(db, job):
        raise HTTPException(409, 'inactive_request')
    if len(json.dumps(data.result).encode()) > 768 * 1024:
        raise HTTPException(413, 'result_limit')
    if data.error:
        job.state = 'unknown' if data.error == 'commit_uncertain' and job.request['op'] in svc.WRITE_OPS else 'failed'
        job.error = data.error
    else:
        if job.request['op'] in ('download', 'preview'):
            path = svc.spool(job)
            if not path.exists():
                path.touch(mode=0o600)
            sha = hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(svc.CHUNK_SIZE), b''):
                    sha.update(chunk)
            hash_key = 'etag' if job.request['op'] == 'preview' else 'sha256'
            if data.result != {'size': job.bytes_received, hash_key: sha.hexdigest()}:
                raise HTTPException(409, 'transfer_mismatch')
            if job.request['op'] == 'preview':
                try:
                    value = path.read_bytes().decode('utf-8')
                    if '\x00' in value:
                        raise ValueError()
                except (UnicodeError, ValueError):
                    raise HTTPException(422, 'binary_or_encoding') from None
        job.state, job.result = 'done', data.result
    db.commit()
    if job.request['op'] in ('upload', 'edit') or job.state in ('failed', 'unknown'):
        svc.spool(job).unlink(missing_ok=True)
    return {'state': job.state}


@router.put('/requests/{job_id}/upload')
async def stage_upload(job_id: str, request: Request, offset: int = Query(ge=0), user=Depends(current_user), db: Session = Depends(get_db)):
    data = await bounded_body(request)
    owner, session = identity(request, user)
    return await run_in_threadpool(append_upload_bytes, db, owner, session, job_id, offset, data)


def append_upload_bytes(db, owner, session, job_id, offset, data):
    db.expire_all()
    job = svc.owned(db, job_id, owner, session)
    if job.state != 'uploading' or not svc.valid(db, job):
        raise HTTPException(409, 'inactive_request')
    if offset + len(data) > job.request['size']:
        raise HTTPException(413, 'transfer_limit')
    if offset != job.bytes_received:
        raise HTTPException(409, 'offset_conflict')
    svc.spool_budget(db, len(data))
    with svc.spool(job).open('ab') as target:
        target.write(data)
    job.bytes_received += len(data)
    db.commit()
    return {'offset': job.bytes_received}


@router.post('/requests/{job_id}/seal')
def seal_upload(job_id: str, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    job = svc.owned(db, job_id, *identity(request, user))
    if job.state != 'uploading' or not svc.valid(db, job):
        raise HTTPException(409, 'inactive_request')
    path = svc.spool(job)
    if not path.exists():
        path.touch(mode=0o600)
    sha = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(svc.CHUNK_SIZE), b''):
            sha.update(chunk)
    if job.bytes_received != job.request['size'] or sha.hexdigest() != job.request['sha256']:
        raise HTTPException(409, 'transfer_mismatch')
    job.state = 'pending'
    db.commit()
    return svc.public(job)


@agent_router.get('/requests/{job_id}/upload')
def agent_upload(job_id: str, lease: str = Query(min_length=32, max_length=64), token: str = Depends(agent_token), db: Session = Depends(get_db)):
    node = svc.node_agent(db, token)
    job = svc.agent_job(db, job_id, node.id, lease)
    if not svc.valid(db, job) or job.request['op'] not in ('upload', 'edit'):
        raise HTTPException(409, 'inactive_request')
    path, length = svc.spool(job), job.bytes_received
    db.commit()  # Release row lock before worker status/admission callbacks.
    def chunks():
        with path.open('rb') as source:
            while True:
                db.expire_all()
                if not svc.valid(db, job):
                    return
                chunk = source.read(svc.CHUNK_SIZE)
                db.commit()
                if not chunk:
                    return
                yield chunk
    return StreamingResponse(chunks(), media_type='application/octet-stream', headers={'Content-Length': str(length), 'Cache-Control': 'no-store'})


@agent_router.post('/requests/{job_id}/admit')
def admit(job_id: str, lease: str = Query(min_length=32, max_length=64), token: str = Depends(agent_token), db: Session = Depends(get_db)):
    node = svc.node_agent(db, token)
    job = svc.agent_job(db, job_id, node.id, lease)
    if job.state not in ('running', 'committing') or not svc.valid(db, job) or job.request['op'] not in svc.WRITE_OPS:
        raise HTTPException(409, 'inactive_request')
    job.state = 'committing'
    db.commit()
    return {'state': job.state}
