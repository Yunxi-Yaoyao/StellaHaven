"""主页背景附件系统：独立的轻量附件区（不走笔记附件的引用计数）。

- 文件落盘 data/assets/homebg/，经 /assets/homebg/<file> 直接静态访问
- 元信息（显示名/格式/是否默认）存同目录 index.json——单用户场景不需要进关系库
- 默认背景（破晓主题那张）不可删除
"""
import json
import fcntl
import os
from contextlib import contextmanager
from functools import wraps
import shutil
from pathlib import Path
from uuid import uuid4
import mimetypes
from copy import deepcopy
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from app.database import get_db
from app.models.config import AppConfig
from app.services import blob_store

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from app.routers.auth import current_user
from app.models.user import User
from app.services import homebg_media
from pydantic import BaseModel

router = APIRouter(prefix="/homebg", tags=["homebg"])

HOMEBG_DIR = Path(__file__).resolve().parents[2] / "data" / "assets" / "homebg"
if not blob_store.enabled():
    HOMEBG_DIR.mkdir(parents=True, exist_ok=True)
INDEX = HOMEBG_DIR / "index.json"

ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif", "mp4"}
MAX_SIZE = 80 * 1024 * 1024  # 80MB（mp4 背景也放得下）


@contextmanager
def _index_lock():
    with (HOMEBG_DIR / '.index.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _locked(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if blob_store.enabled():
            return fn(*args, **kwargs)
        with _index_lock():
            return fn(*args, **kwargs)
    return wrapped


def _load() -> list[dict]:
    if not INDEX.exists():
        return []
    return json.loads(INDEX.read_text(encoding="utf-8"))


def _save(entries: list[dict]) -> None:
    temp = INDEX.with_name('.index.' + uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, INDEX)
    finally:
        temp.unlink(missing_ok=True)


@_locked
def _seed_default() -> None:
    """首次启动：把全局资源区的 bg-kimono 收编为默认背景（不可删）"""
    entries = _load()
    if any(e.get("isDefault") for e in entries):
        return
    src = HOMEBG_DIR.parent / "bg-kimono.jpeg"
    if not src.exists():
        return
    dst = HOMEBG_DIR / "default-bg-kimono.jpeg"
    if not dst.exists():
        shutil.copy2(src, dst)
    entries.insert(0, {
        "id": "default",
        "name": "bg-kimono",
        "ext": "jpeg",
        "file": dst.name,
        "isDefault": True,
    })
    _save(entries)


if not blob_store.enabled():
    _seed_default()


PG_INDEX_KEY = 'homebg_index'


def _pg_load(db):
    value = db.execute(select(AppConfig.value).where(AppConfig.key == PG_INDEX_KEY)).scalar_one_or_none()
    return json.loads(value) if value else []


@contextmanager
def _pg_index(db):
    # ha_state.locked_state opens a different transaction. AppConfig uses THIS
    # session so initialization, index and blobs publish atomically.
    db.execute(insert(AppConfig).values(key=PG_INDEX_KEY, value='[]')
               .on_conflict_do_nothing(index_elements=['key']))
    row = db.execute(select(AppConfig).where(AppConfig.key == PG_INDEX_KEY)
                     .with_for_update().execution_options(populate_existing=True)).scalar_one()
    entries = json.loads(row.value)
    yield entries
    row.value = json.dumps(entries, ensure_ascii=False)
    db.flush()


def _pg_upload(db, file, user, ext):
    entry = dict(id=uuid4().hex[:12], name=(file.filename or '未命名').rsplit('.', 1)[0],
                 ext=ext, file=uuid4().hex + '.' + ext, isDefault=False, owner=str(user.id))
    try:
        with _pg_index(db) as entries:
            info = blob_store.put(db, 'homebg/' + entry['file'], file.file,
                                  mimetypes.guess_type(entry['file'])[0] or 'application/octet-stream', MAX_SIZE)
            entry.update(size=info['size'], sha256=info['sha256'])
            entry['media'] = homebg_media.pg_optimize(db, entry['file'], MAX_SIZE)
            entries.append(entry)
        db.commit()
    except blob_store.BlobTooLarge as exc:
        db.rollback()
        raise HTTPException(400, '文件超过 80MB') from exc
    except Exception:
        db.rollback()
        raise
    return _public(entry)


def _public(e: dict) -> dict:
    url = f"/assets/homebg/{e['file']}"
    try:
        media = deepcopy(e.get('media') or homebg_media._base(url)) if blob_store.enabled() else homebg_media.metadata(HOMEBG_DIR, url)
    except (ValueError, FileNotFoundError):
        media = dict(url=url, status='missing', poster=None, thumbnail=None,
                     variants={'original': url})
    return {
        "media": media,
        "id": e["id"],
        "name": e["name"],
        "ext": e["ext"],
        "url": f"/assets/homebg/{e['file']}",
        "isDefault": bool(e.get("isDefault")),
        "isSystem": bool(e.get("isSystem")),
        "owner": e.get("owner"),
    }


@router.get('/media')
def get_media(url: str, db: Session = Depends(get_db)):
    """Public read-only metadata for already-public local assets."""
    try:
        if blob_store.enabled():
            name = url.removeprefix(homebg_media.PREFIX)
            if not url.startswith(homebg_media.PREFIX) or not homebg_media.SAFE_NAME.fullmatch(name) or '..' in name:
                raise ValueError('Invalid background URL')
            for e in _pg_load(db):
                if e['file'] == name:
                    return _public(e)['media']
            raise FileNotFoundError(name)
        return homebg_media.metadata(HOMEBG_DIR, url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, '背景不存在') from exc


def _visible(e: dict, user: User) -> bool:
    return bool(e.get('isSystem') or e.get('isDefault') or e.get('owner') in (None, str(user.id)))


@router.post('/{entry_id}/optimize')
def optimize_homebg(entry_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if blob_store.enabled():
        with _pg_index(db) as entries:
            entry = next((e for e in entries if e['id'] == entry_id and _visible(e, user)), None)
            if entry is None:
                raise HTTPException(404, '背景不存在')
            entry['media'] = homebg_media.pg_optimize(db, entry['file'], MAX_SIZE)
            result = deepcopy(entry['media'])
        db.commit()
        return result
    for e in _load():
        if e['id'] == entry_id and _visible(e, user):
            try:
                return homebg_media.schedule(HOMEBG_DIR, f"/assets/homebg/{e['file']}")
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(404, '背景不存在') from exc
    raise HTTPException(404, '背景不存在')


@router.get("/")
def list_homebg(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """系统自带的全员可见；用户上传的只出自己的（数据隔离）"""
    return [_public(e) for e in (_pg_load(db) if blob_store.enabled() else _load()) if _visible(e, user)]


@router.post("/upload")
async def upload_homebg(file: UploadFile, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的格式 .{ext}（仅 jpg/png/webp/gif/mp4）")
    if blob_store.enabled():
        return await run_in_threadpool(_pg_upload, db, file, user, ext)
    data = await file.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise HTTPException(400, "文件超过 80MB")
    fname = f"{uuid4().hex[:12]}.{ext}"
    (HOMEBG_DIR / fname).write_bytes(data)
    entry = {
        "id": uuid4().hex[:12],
        "name": (file.filename or "未命名").rsplit(".", 1)[0],
        "ext": ext,
        "file": fname,
        "isDefault": False,
        "owner": str(user.id),  # 归属上传者
    }
    with _index_lock():
        entries = _load()
        entries.append(entry)
        _save(entries)
    response = _public(entry)
    response['media'] = homebg_media.schedule(HOMEBG_DIR, response['url'])
    return response


class RenameBody(BaseModel):
    name: str


@router.patch("/{entry_id}")
@_locked
def rename_homebg(entry_id: str, body: RenameBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if blob_store.enabled():
        with _pg_index(db) as entries:
            e = next((e for e in entries if e['id'] == entry_id), None)
            if e is None or (e.get('owner') not in (None, str(user.id)) and not user.is_admin):
                raise HTTPException(404, '背景不存在')
            if not body.name.strip():
                raise HTTPException(400, '名字不能为空')
            e['name'] = body.name.strip()
            result = _public(e)
        db.commit()
        return result
    entries = _load()
    for e in entries:
        if e["id"] == entry_id:
            # 归属校验：只有上传者或 admin 能改名
            if e.get("owner") not in (None, str(user.id)) and not user.is_admin:
                raise HTTPException(404, "背景不存在")
            name = body.name.strip()
            if not name:
                raise HTTPException(400, "名字不能为空")
            e["name"] = name
            _save(entries)
            return _public(e)
    raise HTTPException(404, "背景不存在")


@router.delete("/{entry_id}")
@_locked
def delete_homebg(entry_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if blob_store.enabled():
        with _pg_index(db) as entries:
            e = next((e for e in entries if e['id'] == entry_id), None)
            if e is None or (e.get('owner') not in (None, str(user.id)) and not user.is_admin):
                raise HTTPException(404, '背景不存在')
            if e.get('isDefault') or e.get('isSystem'):
                raise HTTPException(400, '系统自带背景不可删除')
            for key in homebg_media.pg_keys(e):
                blob_store.delete(db, key)
            entries.remove(e)
        db.commit()
        return {'ok': True}
    entries = _load()
    for i, e in enumerate(entries):
        if e["id"] == entry_id:
            if e.get("isDefault") or e.get("isSystem"):
                raise HTTPException(400, "系统自带背景不可删除")
            if e.get("owner") not in (None, str(user.id)) and not user.is_admin:
                raise HTTPException(404, "背景不存在")
            (HOMEBG_DIR / e["file"]).unlink(missing_ok=True)
            entries.pop(i)
            _save(entries)
            return {"ok": True}
    raise HTTPException(404, "背景不存在")
