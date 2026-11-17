"""Management-only backup writes/downloads; GET status is an owner read."""
from contextlib import contextmanager
import os
import shlex
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from app.database import get_db
from app.routers.auth import current_user, admin_user
from app.schemas.backups import (Config, ConfigPatch, BackupRequest, Confirmation, Job, Status,
                                 ClientPreferences, ClientPreferencesWrite)
from app.services.backup_center import Conflict
from app.services.backup_storage import Busy
from app.services.backup_archive import InvalidArchive
from app.services.backup_preferences import read_preferences, write_preferences

router = APIRouter(prefix='/operations/backups', tags=['backups'])


def center(request: Request):
    instance = getattr(request.app.state, 'backup_center', None)
    if instance is None:
        raise HTTPException(503, '备份执行器未启动')
    return instance


@contextmanager
def errors():
    try:
        yield
    except Busy:
        raise HTTPException(409, {'code': 'backup_busy', 'message': '已有备份操作正在执行'}) from None
    except Conflict:
        raise HTTPException(409, {'code': 'revision_conflict', 'message': '设置已改变，请重新读取'}) from None
    except FileNotFoundError:
        raise HTTPException(404, '此节点/目录不存在该备份') from None
    except (ValueError, ValidationError, InvalidArchive):
        raise HTTPException(422, '配置、确认或备份校验无效') from None
    except OSError as exc:
        from app.services.backup_center import safe_error
        raise HTTPException(422, safe_error(exc)) from None


def release(db, user):
    # Copy before rollback: never re-read expired ORM user fields afterward.
    owner = user.id
    db.rollback()
    return owner


@router.get('', response_model=Status)
def status(request: Request, user=Depends(current_user)):
    with errors():
        return center(request).status()


@router.patch('/config', response_model=Config)
def patch(data: ConfigPatch, request: Request, user=Depends(admin_user), db: Session = Depends(get_db)):
    release(db, user)
    with errors():
        return center(request).patch(data.model_dump(exclude_unset=True))


@router.get('/client-preferences', response_model=ClientPreferences, response_model_exclude_none=True)
def client_preferences(request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    owner = release(db, user)
    with errors():
        return read_preferences(center(request).engine, owner)


@router.put('/client-preferences', response_model=ClientPreferences, response_model_exclude_none=True)
# Pure account-owned presentation choices need login, not management elevation; backup operations below remain admin-only.
def save_client_preferences(data: ClientPreferencesWrite, request: Request, user=Depends(current_user), db: Session = Depends(get_db)):
    owner = release(db, user)
    with errors():
        return write_preferences(center(request).engine, owner, data.model_dump(exclude_unset=True))


@router.post('', response_model=Job, status_code=202)
def backup(data: BackupRequest, request: Request, user=Depends(admin_user), db: Session = Depends(get_db)):
    release(db, user)
    with errors():
        return center(request).submit('backup', data.scope)


def record_for(instance, id):
    row = next((r for r in instance.store().records() if r['id'] == id), None)
    if row is None:
        raise FileNotFoundError('backup missing')
    return row


@router.head('/{id}/download')
def download_head(id: str, request: Request, user=Depends(admin_user), db: Session = Depends(get_db)):
    """Short metadata preflight; real GET separately authenticates/verifies ZIP.

    Never hashes/decompresses the archive here: a native browser owns the long
    stream, not a JavaScript Blob or the JSON control-request timeout.
    """
    release(db, user)
    with errors():
        with center(request).store().open_record(id, verify=False) as (row, stream):
            if os.fstat(stream.fileno()).st_size != row['bytes']:
                raise InvalidArchive('archive size mismatch')
            return Response(media_type='application/zip', headers={
                'Cache-Control': 'no-store', 'Content-Length': str(row['bytes']),
                'Content-Disposition': 'attachment; filename="' + row['filename'] + '"',
                'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer'})


@router.get('/{id}/download')
def download(id: str, request: Request, user=Depends(admin_user), db: Session = Depends(get_db)):
    release(db, user)
    with errors():
        lease = center(request).store().open_record(id)
        row, stream = lease.__enter__()
    def content():
        try:
            while chunk := stream.read(256 * 1024):
                yield chunk
        finally:
            lease.__exit__(None, None, None)
    return StreamingResponse(content(), media_type='application/zip', headers={
        'Cache-Control': 'no-store', 'Content-Length': str(row['bytes']),
        'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
        'Content-Disposition': 'attachment; filename="' + row['filename'] + '"'})


@router.post('/{id}/verify', response_model=Job, status_code=202)
def verify(id: str, request: Request, user=Depends(admin_user), db: Session = Depends(get_db)):
    release(db, user)
    with errors():
        instance = center(request)
        row = record_for(instance, id)
        return instance.submit('verify', row['scope'], id)


@router.post('/{id}/restore', response_model=Job, status_code=202)
def restore(id: str, data: Confirmation, request: Request, user=Depends(admin_user), db: Session = Depends(get_db)):
    release(db, user)
    with errors():
        instance = center(request)
        row = record_for(instance, id)
        if data.confirm != row['filename']:
            raise ValueError('confirmation mismatch')
        if row['scope'] == 'all':
            command = ('python tools/backup_restore.py --archive ' + shlex.quote(str(instance.store().path / row['filename']))
                       + ' --sha256 ' + row['sha256']
                       + ' --host <离线目标主机> --port <端口> --user <目标角色> --database <空库名>'
                       + ' --password-file <0600密码文件> --data-directory <新数据目录> --maintenance'
                       + ' --confirm-target <主机:端口/空库名>')
            raise HTTPException(409, {'code': 'maintenance_required', 'message': '全站恢复必须停止目标应用，并使用离线命令恢复至空数据库和新资源目录；网页不会drop现库。', 'command': command})
        return instance.submit('restore', 'settings', id, confirm=data.confirm)


@router.delete('/{id}', status_code=204)
def delete(id: str, data: Confirmation, request: Request, user=Depends(admin_user), db: Session = Depends(get_db)):
    release(db, user)
    with errors():
        center(request).delete(id, data.confirm)
    return Response(status_code=204)
