"""Terminal asynchronous result admission for trusted, already-authorized producers.

Caller owns authorization and transaction. No HTTP endpoint and no background
poller: call exactly when a real backup/manual-job result is durably committed.
Retries share one source/operation identity; no ordinary-save success spam.
"""
import re
from datetime import datetime, timezone
from sqlalchemy import text
from app.models.alert import Notification
from app.services import alerts
from app.services.alert_history import notification_out


def publish_result(db, *, source, operation_id, outcome, title, body, node_ids=(), now=None):
    if source not in ('backup', 'manual_test', 'import', 'export') or outcome not in ('success', 'failure'):
        raise ValueError('只接入真实异步作业的完成或失败结果')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', operation_id):
        raise ValueError('作业身份无效')
    if not title or len(title)>120 or len(body)>500:
        raise ValueError('通知文本长度无效')
    ids = list(dict.fromkeys(node_ids))
    if len(ids)>32 or any(type(n) is not int or n<=0 for n in ids):
        raise ValueError('节点集合无效')
    key = f'{source}:{operation_id}'
    db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'), {'key':key})
    existing = db.query(Notification).filter_by(dedupe_key=key).first()
    if existing is not None:
        return existing
    note = Notification(title=title,body=body,severity='info' if outcome=='success' else 'warning',
        kind=source+'_result',link=None,read=False,ts=now or datetime.now(timezone.utc),dedupe_key=key,
        context={'source':source,'operation_id':operation_id,'outcome':outcome,'node_ids':ids})
    db.add(note);db.flush()
    payload = {'type':'notification',**notification_out(note)}
    payload['ts']=note.ts.isoformat()
    db.info.setdefault('alert_dispatch',[]).append((payload,None,db.get_nested_transaction()))
    return note
