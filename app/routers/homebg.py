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

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from app.routers.auth import current_user
from app.models.user import User
from app.services import homebg_media
from pydantic import BaseModel

router = APIRouter(prefix="/homebg", tags=["homebg"])

HOMEBG_DIR = Path(__file__).resolve().parents[2] / "data" / "assets" / "homebg"
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


_seed_default()


def _public(e: dict) -> dict:
    url = f"/assets/homebg/{e['file']}"
    try:
        media = homebg_media.metadata(HOMEBG_DIR, url)
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
def get_media(url: str):
    """Public read-only metadata for already-public local assets."""
    try:
        return homebg_media.metadata(HOMEBG_DIR, url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, '背景不存在') from exc


def _visible(e: dict, user: User) -> bool:
    return bool(e.get('isSystem') or e.get('isDefault') or e.get('owner') in (None, str(user.id)))


@router.post('/{entry_id}/optimize')
def optimize_homebg(entry_id: str, user: User = Depends(current_user)):
    for e in _load():
        if e['id'] == entry_id and _visible(e, user):
            try:
                return homebg_media.schedule(HOMEBG_DIR, f"/assets/homebg/{e['file']}")
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(404, '背景不存在') from exc
    raise HTTPException(404, '背景不存在')


@router.get("/")
def list_homebg(user: User = Depends(current_user)):
    """系统自带的全员可见；用户上传的只出自己的（数据隔离）"""
    return [_public(e) for e in _load() if _visible(e, user)]


@router.post("/upload")
async def upload_homebg(file: UploadFile, user: User = Depends(current_user)):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的格式 .{ext}（仅 jpg/png/webp/gif/mp4）")
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
def rename_homebg(entry_id: str, body: RenameBody, user: User = Depends(current_user)):
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
def delete_homebg(entry_id: str, user: User = Depends(current_user)):
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
