"""Database-only OTP attempt state, fixed namespace and at most three slots.

Caller commits successful redemption with the login/reset/bind effect. Rejected
attempts commit here so request cleanup cannot roll back the security budget.
"""
from functools import wraps
import hashlib
import hmac
import json
import math
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from app.models.config import AppConfig
from app.models.user import EmailCode

STATE_KEY = 'security.email_attempts.v1'
PURPOSES = frozenset({'login', 'reset', 'bind'})
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300
CODE_MINUTES = 10
MAX_DELIVERIES = 2
EMPTY_STATE = '{"version":1,"failures":[],"deliveries":[],"slots":{}}'


def now():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fingerprint(row):
    return digest(str(row.id) + ':' + row.code)


def decode_state(value):
    if len(value) > 4096:
        raise ValueError('oversized state')
    state = json.loads(value)
    if (not isinstance(state, dict) or set(state) != {'version', 'failures', 'deliveries', 'slots'}
            or type(state['version']) is not int or state['version'] != 1):
        raise ValueError('state shape')
    for field, maximum in [('failures', MAX_ATTEMPTS), ('deliveries', MAX_DELIVERIES)]:
        stamps = state[field]
        if (not isinstance(stamps, list) or len(stamps) > maximum or
                any(type(t) not in (int, float) or not math.isfinite(t) or t < 0 or t > now().timestamp() + WINDOW_SECONDS for t in stamps)):
            raise ValueError('invalid budget')
    slots = state['slots']
    if not isinstance(slots, dict) or not set(slots).issubset(PURPOSES):
        raise ValueError('invalid slots')
    for slot in slots.values():
        if (not isinstance(slot, dict) or set(slot) != {'email', 'code', 'id', 'attempts'} or
                type(slot['attempts']) is not int or not 0 <= slot['attempts'] <= MAX_ATTEMPTS):
            raise ValueError('invalid slot')
        if not isinstance(slot['id'], str) or str(UUID(slot['id'])) != slot['id']:
            raise ValueError('invalid code identity')
        for field in ('email', 'code'):
            hashed = slot[field]
            if not isinstance(hashed, str) or len(hashed) != 64 or any(c not in '0123456789abcdef' for c in hashed):
                raise ValueError('invalid fingerprint')
    return state


def locked_state(db):
    try:
        if db.get_bind().dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
            db.execute(insert(AppConfig).values(key=STATE_KEY, value=EMPTY_STATE)
                       .on_conflict_do_nothing(index_elements=[AppConfig.key]))
        row = db.query(AppConfig).filter(AppConfig.key == STATE_KEY).with_for_update().populate_existing().first()
        if row is None:
            row = AppConfig(key=STATE_KEY, value=EMPTY_STATE)
            db.add(row)
            db.flush()
        state = decode_state(row.value)
        stamp = now().timestamp()
        for field in ('failures', 'deliveries'):
            state[field] = [t for t in state[field] if stamp - t < WINDOW_SECONDS]
        return row, state
    except (SQLAlchemyError, ValueError, TypeError, KeyError):
        db.rollback()
        raise HTTPException(503, '邮箱安全状态不可用') from None


def save(db, row, state):
    row.value = json.dumps(state, separators=(',', ':'))
    db.flush()


def check_budget(state):
    if len(state['failures']) >= MAX_ATTEMPTS:
        retry = max(1, min(WINDOW_SECONDS, math.ceil(WINDOW_SECONDS - (now().timestamp() - min(state['failures'])))))
        raise HTTPException(429, '尝试过多，请稍后重试', headers={'Retry-After':str(retry)})


def database_guard(function):
    @wraps(function)
    def guarded(db, *args, **kwargs):
        try:
            return function(db, *args, **kwargs)
        except SQLAlchemyError:
            db.rollback()
            raise HTTPException(503, '邮箱安全状态不可用') from None
    return guarded


@database_guard
def issue_code(db, email, purpose, resend=False):
    config, state = locked_state(db)
    check_budget(state)
    row = db.query(EmailCode).filter(EmailCode.email == email).with_for_update().populate_existing().first()
    slot = state['slots'].get(purpose)
    if not resend and row and slot and slot['email'] == digest(email) and slot['code'] == fingerprint(row) and row.expires_at.replace(tzinfo=timezone.utc) > now():
        return None
    if resend:
        if not row or not slot or slot['email'] != digest(email) or slot['code'] != fingerprint(row):
            raise HTTPException(404, '没有此用途的验证码，请重新发送')
        if row.resent_at and (now() - row.resent_at.replace(tzinfo=timezone.utc)).total_seconds() < WINDOW_SECONDS:
            raise HTTPException(429, '喵~ 5 分钟内只能重发一次', headers={'Retry-After':str(WINDOW_SECONDS)})
    if len(state['deliveries']) >= MAX_DELIVERIES:
        retry = max(1, min(WINDOW_SECONDS, math.ceil(WINDOW_SECONDS - (now().timestamp() - min(state['deliveries'])))))
        raise HTTPException(429, '喵~ 5 分钟内发送次数已达上限', headers={'Retry-After':str(retry)})
    if slot:
        db.query(EmailCode).filter(EmailCode.id == UUID(slot['id'])).delete(synchronize_session=False)
    state['deliveries'].append(now().timestamp())
    code = f'{secrets.randbelow(1000000):06d}'
    db.query(EmailCode).filter(EmailCode.email == email).delete(synchronize_session=False)
    row = EmailCode(id=uuid4(), email=email, code=code, expires_at=now()+timedelta(minutes=CODE_MINUTES),
                    resent_at=now() if resend else None)
    db.add(row)
    state['slots'][purpose] = {'email':digest(email), 'code':fingerprint(row), 'id':str(row.id), 'attempts':0}
    save(db, config, state)
    db.commit()
    return code


@database_guard
def consume_code(db, email, purpose, candidate):
    config, state = locked_state(db)
    check_budget(state)
    row = db.query(EmailCode).filter(EmailCode.email == email).with_for_update().populate_existing().first()
    slot = state['slots'].get(purpose)
    if not row or not slot or slot['email'] != digest(email) or slot['code'] != fingerprint(row):
        raise HTTPException(404, '没有此用途的验证码，请重新发送')
    if row.expires_at.replace(tzinfo=timezone.utc) <= now():
        raise HTTPException(410, '验证码过期了，请重新发送')
    if slot['attempts'] >= MAX_ATTEMPTS:
        raise HTTPException(404, '验证码已失效，请重新发送')
    slot['attempts'] += 1
    if not hmac.compare_digest(row.code.encode(), candidate.strip().encode()):
        state['failures'].append(now().timestamp())
        if slot['attempts'] >= MAX_ATTEMPTS:
            db.delete(row)
        save(db, config, state)
        db.commit()
        raise HTTPException(401, '验证码不对喵~')
    db.delete(row)
    state['slots'].pop(purpose)
    save(db, config, state)
