"""Single-owner authentication; legacy management credentials are inactive.

AppConfig retains its owner pin and dormant hash/grants for rollback. No second
password or grant is authority. Private state stays excluded from generic config.
"""
import json
from fastapi import HTTPException
from sqlalchemy import text
from app.models.config import AppConfig

STATE_KEY = 'security.owner_admin.v1'


def decode_state(value):
    try:
        state = json.loads(value)
        if not isinstance(state, dict):
            raise ValueError('invalid state')
        state.setdefault('enabled', True)
        state.setdefault('version', 1)
        state.setdefault('grants', {})
        if type(state['enabled']) is not bool or type(state['version']) is not int or state['version'] < 1 or not isinstance(state['grants'], dict):
            raise ValueError('invalid state fields')
        return state
    except (ValueError, TypeError) as exc:
        raise HTTPException(503, '安全设置无效，请修复服务器配置') from exc


def read_state(db):
    # Ordinary authenticated reads must NOT serialize on a global row lock.
    row = db.query(AppConfig).filter(AppConfig.key == STATE_KEY).populate_existing().first()
    return row, decode_state(row.value if row else '{}')


def locked_state(db):
    # Serialize owner pin creation too: FOR UPDATE cannot lock an absent row.
    if db.get_bind().dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(1836289001)'))
    row = db.query(AppConfig).filter(AppConfig.key == STATE_KEY).with_for_update().populate_existing().first()
    if row is None:
        row = AppConfig(key=STATE_KEY, value='{}')
        db.add(row)
        db.flush()
    return row, decode_state(row.value)


def save(db, row, state):
    row.value = json.dumps(state, separators=(',', ':'))
    db.flush()


def security_status(db, session, state=None):
    """Compatible DTO for old clients, never a grant or anonymous authority."""
    require_admin(db, session)
    return {'enabled': False, 'configured': True, 'elevated': True,
            'expires_at': None, 'single_user': True, 'setup_required': False}


def owner_id(db, *, commit=True):
    """Never pick the first row or change a persisted identity implicitly."""
    import os
    from uuid import UUID
    from app.models.user import User
    row, state = read_state(db)
    if not state.get('owner_id'):
        row, state = locked_state(db)
    configured = os.getenv('STELLA_OWNER_ID', '')
    selected = state.get('owner_id') or configured
    if selected:
        try:
            uid = UUID(selected)
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(503, 'owner配置无效') from exc
        if configured and str(uid) != configured:
            raise HTTPException(503, 'owner配置与已固定身份不一致')
        user = db.get(User, uid)
        if not user or not user.is_active:
            raise HTTPException(503, 'owner不可用')
    else:
        users = db.query(User).limit(2).all()
        if len(users) != 1 or not users[0].is_active:
            raise HTTPException(503, '请显式配置唯一owner身份')
        uid = users[0].id
    if not state.get('owner_id'):
        state['owner_id'] = str(uid)
        save(db, row, state)
        # Registration owns User + pin + first AuthSession in one transaction.
        # Legacy login/read callers retain their existing bootstrap durability.
        if commit:
            db.commit()
    return uid


def require_owner(db, user, *, commit=True):
    if user.id != owner_id(db, commit=commit):
        raise HTTPException(403, '单用户模式仅允许owner登录')


def management_password_retired():
    raise HTTPException(410, {'code': 'management_password_retired',
                              'message': '独立管理密码已退役，请使用用户账号登录'})


# Internal compatibility entry points fail closed too; old hashes cannot grant.
def setup(db, user, user_password, new_password):
    management_password_retired()


def unlock(db, session, password):
    management_password_retired()


def lock(db, session):
    management_password_retired()


def change_protection(db, enabled, password):
    management_password_retired()


def change_admin_password(db, user, current_password, new_password):
    management_password_retired()


def daily_password_changed(db, new_password):
    # Caller verifies old user password and revokes AuthSessions atomically.
    # A dormant historical hash does not constrain the one active password.
    from app.services.backup_health import record_change
    record_change(db, action='security.password_change', actor_id=owner_id(db),
                  changed_fields=['security'], payload=None)


def require_admin(db, session):
    """Compatibility name for authenticated owner, including service callers.

    Reload persisted state so stale/forged objects cannot bypass revoke, expiry
    or owner checks. Cookie/ticket and origin checks stay at existing callers.
    """
    from app.models.user import AuthSession, User
    from app.services.session_policy import expired
    sid = getattr(session, 'id', None)
    if not sid:
        raise HTTPException(401, '会话已失效')
    # Preserve the pre-existing transaction serialization used by management
    # writers. It is not a password/grant check, and does not rewrite history.
    locked_state(db)
    persisted = db.get(AuthSession, sid, populate_existing=True)
    if not persisted or persisted.revoked or expired(persisted):
        raise HTTPException(401, '会话已失效')
    user = db.get(User, persisted.user_id, populate_existing=True)
    if not user or not user.is_active:
        raise HTTPException(401, '账号不可用')
    require_owner(db, user)
