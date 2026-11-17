"""Revalidate runtime writes after workspace/state waits, before state mutation.

Lock order is notes graph -> workspace -> state -> session -> user -> grant.
The latter rows stay locked until the caller commits. Session revocation and
capability replacement therefore cannot commit between this check and the write.
No global admin-state lock is acquired (logout can hold it while updating SID).
"""
from fastapi import HTTPException
from app.models.config import AppConfig
from app.models.user import AuthSession, User
from app.services import web_project_runtime as runtime


def authorize_locked_write(db, owner, root, sid, capability, source):
    session = db.query(AuthSession).filter_by(id=sid).populate_existing().with_for_update().first()
    user = db.query(User).filter_by(id=owner).populate_existing().with_for_update().first()
    row = db.query(AppConfig).filter_by(key=runtime.key(capability)).populate_existing().with_for_update().first()
    if not session or not user or session.user_id != owner or not row:
        raise HTTPException(403, '网页保存授权已失效')
    # All possibly blocking row locks have been acquired. Re-read TTL, epoch,
    # owner pin and identity now, not from the earlier HTTP dependency snapshot.
    grant, _ = runtime.authorize(db, capability, source=source)
    if (grant['owner'] != str(owner) or grant['root'] != str(root)
            or grant['sid'] != str(sid) or grant['source'] != source):
        raise HTTPException(403, '网页保存授权不匹配')
