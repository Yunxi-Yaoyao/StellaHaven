"""Compatibility URLs: uploaded backgrounds/avatars remain public as before.

Mount this router BEFORE /assets StaticFiles. PG misses never consult upload
folders. Legacy mode uses the same existing local files without PG access.
"""
import os
import re
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.services import blob_store

router = APIRouter(tags=['assets'])
ROOT = Path(__file__).resolve().parents[2] / 'data' / 'assets'
SAFE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*')
# Explicit operator-provided read-only packaged root, only this fixed name.
PACKAGED_NAMES = {'homebg/default-bg-kimono.jpeg'}


@router.api_route('/assets/homebg/{filename}', methods=['GET', 'HEAD'])
def background_asset(filename: str, request: Request, db: Session = Depends(get_db)):
    return dynamic_asset('homebg', filename, request, db)


@router.api_route('/assets/avatars/{filename}', methods=['GET', 'HEAD'])
def avatar_asset(filename: str, request: Request, db: Session = Depends(get_db)):
    return dynamic_asset('avatars', filename, request, db)


def dynamic_asset(kind: str, filename: str, request: Request, db: Session):
    if kind not in ('avatars', 'homebg') or not SAFE.fullmatch(filename) or '..' in filename:
        raise HTTPException(404, 'Asset not found')
    key = kind + '/' + filename
    if blob_store.enabled():
        if blob_store.metadata(db, key) is not None:
            return blob_store.response(db, key, request)
        packaged = os.getenv('STELLA_PACKAGED_ASSETS_ROOT')
        if not packaged or key not in PACKAGED_NAMES:
            raise HTTPException(404, 'Asset not found')
        root = Path(packaged).resolve()
    else:
        root = ROOT.resolve()
    target = root / key
    if target.is_symlink() or root not in target.resolve().parents or not target.is_file():
        raise HTTPException(404, 'Asset not found')
    return FileResponse(target)
