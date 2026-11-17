"""Current shared-media references, serialized by the existing library index.

Lock order: homebg_index -> User/NavState -> blobs. PostgreSQL is authoritative;
no local-file fallback or history scan. Legacy file mode uses the existing index
flock through reference commit, but unlink + JSON + SQL is NOT crash-atomic.
"""
import json
import posixpath
import re
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException
from sqlalchemy import select

from app.models.user import User
from app.models.native_nav import NavState
from app.services import blob_store, homebg_media
from app.services.request_security import canonical_origin, trusted_origins

INDEX_KEY = 'homebg_index'


def local_key(value):
    """Normalize relative and configured same-origin aliases, never remote URLs."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parsed = urlsplit(value.replace('\\', '/'))
        if parsed.netloc or parsed.scheme:
            import os
            origins = trusted_origins() | {canonical_origin(os.getenv('STELLA_MAIN_ORIGIN', ''))}
            if parsed.scheme:
                origin = canonical_origin(parsed.scheme+'://'+parsed.netloc)
                if origin is None or origin not in origins:
                    return None
            elif not any(origin and canonical_origin(urlsplit(origin).scheme+'://'+parsed.netloc) == origin for origin in origins):
                return None
        elif not parsed.path.startswith('/'):
            return None
        path = posixpath.normpath(unquote(parsed.path))
        if not path.startswith(homebg_media.PREFIX):
            return None
        name = path.removeprefix(homebg_media.PREFIX)
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name) and '..' not in name:
            return 'homebg/'+name
    except (ValueError, TypeError):
        pass
    return None


def keys(value):
    if isinstance(value, dict):
        return {key for child in value.values() for key in keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in keys(child)}
    key = local_key(value)
    return {key} if key else set()


def _release_file_lock(db, transaction):
    if transaction.parent is None:
        lock = db.info.pop('homebg_reference_lock', None)
        if lock is not None:
            lock.close()


def lock_library(db):
    """Reuse the existing index row lock; caller owns commit/rollback."""
    from app.models.config import AppConfig
    if blob_store.enabled():
        from sqlalchemy.dialects.postgresql import insert
        db.execute(insert(AppConfig).values(key=INDEX_KEY, value='[]')
                   .on_conflict_do_nothing(index_elements=['key']))
        return db.execute(select(AppConfig).where(AppConfig.key == INDEX_KEY)
                          .with_for_update().execution_options(populate_existing=True)).scalar_one()
    # Hold the same existing index flock until the outer SQL transaction ends.
    # This serializes cooperating requests, not crash-atomic filesystem + SQL.
    if 'homebg_reference_lock' not in db.info:
        import fcntl
        from sqlalchemy import event
        from app.routers.homebg import HOMEBG_DIR
        db.connection()  # establish the outer transaction before registering
        lock = (HOMEBG_DIR / '.index.lock').open('a+b')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
        except BaseException:
            lock.close()
            raise
        db.info['homebg_reference_lock'] = lock
        if not db.info.get('homebg_reference_listener'):
            event.listen(db, 'after_transaction_end', _release_file_lock)
            db.info['homebg_reference_listener'] = True


def validate_new(db, incoming, previous=None):
    """New local references must exist; unchanged legacy missing URLs can survive."""
    for key in keys(incoming) - keys(previous):
        if blob_store.enabled():
            exists = blob_store.metadata(db, key) is not None
            if not exists and key == 'homebg/default-bg-kimono.jpeg':
                import os
                from pathlib import Path
                root = os.getenv('STELLA_PACKAGED_ASSETS_ROOT')
                if root:
                    root = Path(root).resolve()
                    path = root/key
                    exists = not path.is_symlink() and root in path.resolve().parents and path.is_file()
        else:
            from app.routers.homebg import HOMEBG_DIR
            path = HOMEBG_DIR/key.removeprefix('homebg/')
            exists = path.is_file() and not path.is_symlink()
        if not exists:
            raise HTTPException(409, {'code':'media_missing','message':'本地素材已删除或不存在，请重新选择；未保存'})


def preference_urls(db):
    """Only the current audited home field, not arbitrary/private settings."""
    from app.models.config import AppConfig
    values = db.scalars(select(AppConfig.value).where(AppConfig.key.startswith('client-preferences:')))
    result = []
    try:
        for raw in values:
            result.append((json.loads(raw).get('home') or {}).get('bgImage', ''))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(503, '账号首页偏好无效，无法安全检查素材引用') from None
    return result


def reject_referenced(db, entry):
    if not blob_store.enabled():
        from app.routers.homebg import HOMEBG_DIR
        try:
            media = json.loads((HOMEBG_DIR/('.'+entry['file']+'.media.json')).read_text())
            entry = dict(entry, media=media)
        except (OSError, ValueError):
            pass
    aliases = homebg_media.pg_keys(entry)
    reasons = []
    # Site background is the pinned owner's home_bg, not a separate writer.
    if any(keys(url) & aliases for url in db.scalars(select(User.home_bg))):
        reasons.append('首页/站点背景引用')
    if any(keys(data) & aliases for data in db.scalars(select(NavState.data))):
        reasons.append('已保存导航引用')
    if keys(preference_urls(db)) & aliases:
        reasons.append('账号首页偏好引用')
    if reasons:
        raise HTTPException(409, {'code':'media_in_use','message':'素材仍有引用，未删除任何文件','references':reasons})
