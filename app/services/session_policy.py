"""No schema changes: timestamps are UTC; expired rows remain as history.

Remembered sessions end 30 days after login, never sliding. Other sessions end
30 minutes after explicit activity. Reads/refresh/polling are NOT activity.
Browser trusted input and CLI operations should POST /auth/activity (at most
once per minute). This opt-in cannot resurrect an expired/revoked session.
"""
from datetime import datetime, timedelta, timezone

REMEMBER_TTL = timedelta(days=30)
IDLE_TTL = timedelta(minutes=30)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def expires_at(session) -> datetime:
    return utc(session.created_at) + REMEMBER_TTL if session.remember else utc(session.last_seen) + IDLE_TTL


def expired(session, now: datetime | None = None) -> bool:
    return expires_at(session) <= utc(now or datetime.now(timezone.utc))
