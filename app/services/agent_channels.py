"""Explicit per-node assignments. AppConfig CAS, bounded receipts, no server probes.

All same-center entries must route node auth/config/tasks/report to the same DB
and signing identity. Registry membership is deployment trust, never provisioning.
"""
import hashlib
import hmac
import json
import uuid
from sqlalchemy import select, text
from fastapi import HTTPException
from app.models.config import AppConfig
from app.models.node import Node
from app.schemas.channel import ChannelWrite, ChannelReceipt

KEY = 'agent_report_channels.v1'
LOCK = 1937006972


def center_id():
    # Public RSA material only. No key generation or digest of a private key.
    from app.services.oidc import jwks
    key = jwks()['keys'][0]
    public = {k:key[k] for k in ('e','kty','n')}
    return hashlib.sha256(json.dumps(public, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def entries():
    from app.services.entry_registry import records, _origin
    pair = records()['stella']
    try:
        result = [dict(entry_id=key, origin=_origin(pair[key])) for key in ('public','private') if key in pair]
        from app.services.request_security import trusted_origins
        if any(e['origin'] not in trusted_origins() for e in result):
            raise ValueError('registry origin missing main-site Host trust')
        return result
    except ValueError:
        raise HTTPException(503, '上报通道需要已登记的精确 HTTPS 入口') from None


def _load(db, locked=False):
    if locked and db.get_bind().dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key':LOCK})
    row = db.get(AppConfig, KEY, populate_existing=True)
    return json.loads(row.value) if row else {'revision':0, 'assignments':{}, 'receipts':{}}


def _save(db, state):
    row = db.get(AppConfig, KEY)
    if row is None:
        row = AppConfig(key=KEY, value=''); db.add(row)
    row.value = json.dumps(state, separators=(',', ':'))
    db.flush()


def assignment(state, node_id):
    return state['assignments'].get(str(node_id), dict(revision=0,epoch='initial',mode='default',entry_id=None))


def _proof(node, value):
    from app.security import SECRET_KEY
    return hmac.new(SECRET_KEY.encode(), (str(node.id) + ':' + (node.token or '') + ':' + value).encode(), hashlib.sha256).hexdigest()


def _config(state, node):
    item = assignment(state,node.id)
    known = entries()
    return dict(revision=item['revision'], epoch=item['epoch'], mode=item['mode'],
                nonce=_nonce(node,item,known), center_id=center_id(),
                token_binding=_proof(node,'binding'), node_id=node.id, entries=known,
                selected_entry_id=item['entry_id'] or 'public')


def _nonce(node, item, known):
    # Bind receipt to the actual approved entry list too, not just assignment.
    return _proof(node,json.dumps(dict(assignment=item,entries=known),sort_keys=True,separators=(',',':')))


def config(db, node):
    return _config(_load(db),node)


def optional_config(db,node):
    # Old single-origin/no-public-key installations remain usable, never force a
    # new URL before an authenticated validated policy exists.
    try:
        return config(db,node)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return None


def read(db):
    state = _load(db)
    known = entries()
    nodes = []
    from app.services.server_status import node_status
    for node in db.scalars(select(Node).where(Node.status != 'removed').order_by(Node.id)):
        item = assignment(state,node.id)
        receipt = state['receipts'].get(str(node.id), {})
        active = (receipt.get('epoch') == item['epoch'] and receipt.get('revision') == item['revision']
                  and receipt.get('nonce') == _nonce(node,item,known))
        report = (node.control_channel or {}).get('report') or {}
        from app.schemas.control_channel import ReportTransaction
        from pydantic import ValidationError
        try:
            report = ReportTransaction.model_validate(report).model_dump(mode='json')
        except (ValidationError, ValueError, TypeError):
            report = {}
        nodes.append(dict(node_id=node.id,name=node.name, mode=item['mode'],entry_id=item['entry_id'],revision=item['revision'],
            state=receipt['state'] if active else 'pending', actual_origin=receipt.get('origin') if receipt.get('origin') in {e['origin'] for e in known} else None,
            http_ms=report.get('duration_ms'),http_origin=report.get('origin'),http_status=report.get('status'),sampled_at=report.get('sampled_at'),
            error=receipt.get('error') if active else None,online=node_status(node)=='online'))
    return dict(revision=state['revision'],default_entry_id='public',entries=known,nodes=nodes)


def update(db, fields):
    fields = ChannelWrite.model_validate(fields).model_dump()
    state = _load(db,True)
    if fields['revision'] != state['revision']:
        db.rollback(); raise HTTPException(409,'上报通道已变化，请刷新后重试')
    known = entries()
    if fields['mode']=='auto' and len(known)<2:
        db.rollback(); raise HTTPException(422,'自动选路至少需要两个已登记的 HTTPS 入口')
    if fields['mode']=='fixed' and fields['entry_id'] not in {e['entry_id'] for e in known}:
        db.rollback(); raise HTTPException(422,'入口未登记')
    ids=set(db.scalars(select(Node.id).where(Node.status != 'removed',Node.id.in_(fields['node_ids']))))
    if ids != set(fields['node_ids']):
        db.rollback(); raise HTTPException(422,'所选节点不存在或已移除')
    center_id()  # fail closed before persisting unusable policy
    state['revision'] += 1
    for node_id in fields['node_ids']:
        state['assignments'][str(node_id)] = dict(revision=state['revision'],epoch=uuid.uuid4().hex,
            mode=fields['mode'],entry_id=fields['entry_id'])
    _save(db,state); db.commit()
    return read(db)


def receipt(db,node,incoming,request_origin):
    incoming = ChannelReceipt.model_validate(incoming)
    state = _load(db,True)
    cfg = _config(state,node)
    allowed={e['origin'] for e in cfg['entries']}
    selected=next(e['origin'] for e in cfg['entries'] if e['entry_id']==cfg['selected_entry_id'])
    if (incoming.epoch!=cfg['epoch'] or incoming.revision!=cfg['revision'] or
        not hmac.compare_digest(incoming.nonce,cfg['nonce']) or incoming.center_id!=cfg['center_id'] or
        incoming.origin!=request_origin or request_origin not in allowed or
        (incoming.state=='applied' and cfg['mode']!='auto' and incoming.origin!=selected)):
        raise HTTPException(409,'过期或不匹配的通道确认')
    previous=state['receipts'].get(str(node.id),{})
    if previous.get('epoch')==incoming.epoch and incoming.sequence<=previous.get('sequence',0):
        raise HTTPException(409,'过期的通道确认序号')
    state['receipts'][str(node.id)] = incoming.model_dump()
    _save(db,state)


def probe(node, request_origin):
    if request_origin not in {e['origin'] for e in entries()}:
        raise HTTPException(403,'探测来源未登记')
    return dict(center_id=center_id(),node_id=node.id,token_binding=_proof(node,'binding'),origin=request_origin)
