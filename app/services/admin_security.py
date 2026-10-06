"""Independent management authentication persisted in PostgreSQL AppConfig.

Private keys are deliberately NOT exposed via generic configuration routes.
"""
import json
from datetime import datetime, timedelta, timezone
from app.security import hash_password, verify_password
from app.services.session_policy import expires_at as session_expires_at

ADMIN_TTL = timedelta(minutes=10)
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
    # Serialize creation too: FOR UPDATE alone cannot lock an absent row.
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
    if state is None:
        _, state = read_state(db)
    configured = bool(state.get('password_hash'))
    grant = state['grants'].get(str(session.id), {})
    expiry = grant.get('expires_at')
    elevated = bool(configured and (not state['enabled'] or (
        grant.get('version') == state['version'] and expiry and
        datetime.fromisoformat(expiry) > datetime.now(timezone.utc))))
    return {'enabled': state['enabled'], 'configured': configured,
            'elevated': elevated, 'expires_at': expiry if elevated and state['enabled'] else None,
            'single_user': True, 'setup_required': not configured}

def owner_id(db):
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
        db.commit()
    return uid

def require_owner(db, user):
    if user.id != owner_id(db):
        raise HTTPException(403, '单用户模式仅允许owner登录')

def validate_new_password(user, password):
    if not 10 <= len(password) <= 256:
        raise HTTPException(400, '管理密码须为10至256位')
    if verify_password(password, user.password_hash):
        raise HTTPException(400, '管理密码必须独立于日常密码')

def invalidate(state):
    state['version'] += 1
    state['grants'] = {}

def verify_limited(db, row, state, password, hashed):
    import math
    now = datetime.now(timezone.utc).timestamp()
    failures = [stamp for stamp in state.get('failures', []) if now - stamp < 60]
    if len(failures) >= 5:
        retry = max(1, min(60, math.ceil(60 - (now - min(failures)))))
        raise HTTPException(429, '尝试过多，请稍后重试', headers={'Retry-After': str(retry)})
    if not password or not verify_password(password, hashed):
        state['failures'] = (failures + [now])[-5:]
        save(db, row, state)
        db.commit()  # failures survive all workers and rejected-request rollbacks
        raise HTTPException(401, '密码错误')
    state['failures'] = []

def setup(db, user, user_password, new_password):
    row, state = locked_state(db)
    if state.get('password_hash'):
        raise HTTPException(409, '管理密码已设置')
    verify_limited(db, row, state, user_password, user.password_hash)
    validate_new_password(user, new_password)
    state['password_hash'] = hash_password(new_password)
    state['enabled'] = True
    invalidate(state)
    save(db, row, state)
    from app.services.backup_health import record_change
    record_change(db, action='security.setup', actor_id=user.id,
                  changed_fields=['security'], payload=None)
    db.commit()

def unlock(db, session, password):
    row, state = locked_state(db)
    if not state.get('password_hash'):
        raise HTTPException(403, {'code': 'admin_setup_required', 'message': '请先设置管理密码'})
    verify_limited(db, row, state, password, state['password_hash'])
    now = datetime.now(timezone.utc)
    # Drop expired entries, bound state even for owners with many old sessions.
    grants = {sid: g for sid, g in state['grants'].items()
              if datetime.fromisoformat(g['expires_at']) > now and g['version'] == state['version']}
    if len(grants) >= 100:
        oldest = min(grants, key=lambda sid: grants[sid]['expires_at'])
        del grants[oldest]
    until = min(now + ADMIN_TTL, session_expires_at(session))
    grants[str(session.id)] = {'expires_at': until.isoformat(), 'version': state['version']}
    state['grants'] = grants
    save(db, row, state)
    from app.services.backup_health import record_change
    record_change(db, action='security.unlock', actor_id=session.user_id,
                  changed_fields=['security'], payload=None)
    db.commit()

def lock(db, session):
    row, state = locked_state(db)
    state['grants'].pop(str(session.id), None)
    save(db, row, state)
    from app.services.backup_health import record_change
    record_change(db, action='security.lock', actor_id=session.user_id,
                  changed_fields=['security'], payload=None)
    db.commit()

def check_management_password(db, row, state, password):
    if not state.get('password_hash'):
        raise HTTPException(403, {'code': 'admin_setup_required', 'message': '请先设置管理密码'})
    verify_limited(db, row, state, password, state['password_hash'])

def change_protection(db, enabled, password):
    row, state = locked_state(db)
    check_management_password(db, row, state, password)
    state['enabled'] = enabled
    invalidate(state)
    save(db, row, state)
    from app.services.backup_health import record_change
    record_change(db, action='security.update', actor_id=state['owner_id'],
                  changed_fields=['security', 'protection'], payload=None)
    db.commit()

def change_admin_password(db, user, current_password, new_password):
    row, state = locked_state(db)
    check_management_password(db, row, state, current_password)
    validate_new_password(user, new_password)
    state['password_hash'] = hash_password(new_password)
    invalidate(state)
    save(db, row, state)
    from app.services.backup_health import record_change
    record_change(db, action='security.password_change', actor_id=user.id,
                  changed_fields=['security'], payload=None)
    db.commit()

def daily_password_changed(db, new_password):
    row, state = locked_state(db)
    if state.get('password_hash') and verify_password(new_password, state['password_hash']):
        raise HTTPException(400, '日常密码不能与管理密码相同')
    invalidate(state)
    save(db, row, state)

    from app.services.backup_health import record_change
    record_change(db, action='security.password_change', actor_id=state['owner_id'],
                  changed_fields=['security'], payload=None)
def require_admin(db, session):
    from app.services.session_policy import expired
    if session.revoked or expired(session):
        raise HTTPException(401, '会话已失效')
    _, state = locked_state(db)
    status = security_status(db, session, state)
    if not status['configured'] or not status['elevated']:
        code = 'admin_setup_required' if not status['configured'] else 'admin_elevation_required'
        raise HTTPException(403, {'code': code, 'message': '请设置独立管理密码' if not status['configured'] else '请验证独立管理密码'})
