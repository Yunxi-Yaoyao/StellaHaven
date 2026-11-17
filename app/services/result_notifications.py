"""Small durable terminal-result handoff using existing AppConfig storage.

Only trusted producers stage safe scalar summaries on their RESULT transaction.
Delivery uses independent owned Sessions, never joins an externally committed
Connection (which would dispatch WS on SAVEPOINT release). Pending rows survive
crashes, are deleted atomically with the notification, and are retried by the
existing backup maintenance timer. No new worker, schema, public API or email.
"""
import base64
import hashlib
import json
import logging
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.notifications import publish_result

logger = logging.getLogger(__name__)
PREFIX = 'result_notice_v1:'
BATCH = 16


def stage_result(conn, *, source, operation_id, outcome, title, body, node_ids=()):
    """Persist an immutable intent in the caller's transaction; never commit."""
    import re
    if source not in ('backup', 'manual_test') or outcome not in ('success', 'failure'):
        raise ValueError('unsupported terminal producer')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', operation_id):
        raise ValueError('invalid operation identity')
    ids = list(dict.fromkeys(node_ids))
    if not title or len(title) > 120 or len(body) > 500 or len(ids) > 32 or any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError('invalid result summary')
    digest = base64.urlsafe_b64encode(hashlib.sha256(f'{source}:{operation_id}'.encode()).digest()).decode().rstrip('=')
    payload = dict(source=source, operation_id=operation_id, outcome=outcome,
                   title=title, body=body, node_ids=ids)
    conn.execute(text('INSERT INTO app_config (key,value) VALUES (:key,:value) ON CONFLICT (key) DO NOTHING'),
                 {'key': PREFIX + digest, 'value': json.dumps(payload)})


def deliver_pending(engine):
    """Best effort, <=16 rows / 3s admission budget; failures retain intents.

    SQL statements and lock waits have independent finite deadlines. Notification
    faults cannot change the already committed business result. WS is only the
    existing post-commit invalidation; durable bell readback is authoritative.
    """
    delivered = 0
    deadline = time.monotonic() + 3
    try:
        with engine.connect() as conn:
            conn.execute(text("SET LOCAL statement_timeout='1000ms'"))
            keys = conn.execute(text('SELECT key FROM app_config WHERE key LIKE :prefix ORDER BY key LIMIT :limit'),
                                {'prefix': PREFIX + '%', 'limit': BATCH}).scalars().all()
        for key in keys:
            if time.monotonic() >= deadline:
                break
            try:
                with Session(engine) as db, db.begin():
                    db.execute(text("SET LOCAL statement_timeout='1000ms'"))
                    db.execute(text("SET LOCAL lock_timeout='200ms'"))
                    value = db.execute(text('SELECT value FROM app_config WHERE key=:key FOR UPDATE SKIP LOCKED'),
                                       {'key': key}).scalar_one_or_none()
                    if value is None:
                        continue
                    publish_result(db, **json.loads(value))
                    db.execute(text('DELETE FROM app_config WHERE key=:key'), {'key': key})
                delivered += 1
            except Exception:
                logger.warning('result_notification_delivery_deferred')
    except Exception:
        logger.warning('result_notification_delivery_deferred')
    return delivered
