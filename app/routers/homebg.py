"""主页背景附件系统：独立的轻量附件区（不走笔记附件的引用计数）。

- 文件落盘 data/assets/homebg/，经 /assets/homebg/<file> 直接静态访问
- 元信息（显示名/格式/是否默认）存同目录 index.json——单用户场景不需要进关系库
- 默认背景（破晓主题那张）不可删除
"""
import json
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/homebg", tags=["homebg"])

HOMEBG_DIR = Path(__file__).resolve().parents[2] / "data" / "assets" / "homebg"
HOMEBG_DIR.mkdir(parents=True, exist_ok=True)
INDEX = HOMEBG_DIR / "index.json"

ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif", "mp4"}
MAX_SIZE = 80 * 1024 * 1024  # 80MB（mp4 背景也放得下）


def _load() -> list[dict]:
    if not INDEX.exists():
        return []
    return json.loads(INDEX.read_text(encoding="utf-8"))


def _save(entries: list[dict]) -> None:
    INDEX.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


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
    return {
        "id": e["id"],
        "name": e["name"],
        "ext": e["ext"],
        "url": f"/assets/homebg/{e['file']}",
        "isDefault": bool(e.get("isDefault")),
    }


@router.get("/")
def list_homebg():
    return [_public(e) for e in _load()]


@router.post("/upload")
async def upload_homebg(file: UploadFile):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"不支持的格式 .{ext}（仅 jpg/png/webp/gif/mp4）")
    data = await file.read()
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
    }
    entries = _load()
    entries.append(entry)
    _save(entries)
    return _public(entry)


class RenameBody(BaseModel):
    name: str


@router.patch("/{entry_id}")
def rename_homebg(entry_id: str, body: RenameBody):
    entries = _load()
    for e in entries:
        if e["id"] == entry_id:
            name = body.name.strip()
            if not name:
                raise HTTPException(400, "名字不能为空")
            e["name"] = name
            _save(entries)
            return _public(e)
    raise HTTPException(404, "背景不存在")


@router.delete("/{entry_id}")
def delete_homebg(entry_id: str):
    entries = _load()
    for i, e in enumerate(entries):
        if e["id"] == entry_id:
            if e.get("isDefault"):
                raise HTTPException(400, "默认背景不可删除")
            (HOMEBG_DIR / e["file"]).unlink(missing_ok=True)
            entries.pop(i)
            _save(entries)
            return {"ok": True}
    raise HTTPException(404, "背景不存在")
