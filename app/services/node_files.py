"""File-domain authority and lifecycle. Only Agent config carries OS roots."""
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy import select, text
from app.models.node import Node
from app.models.user import User, AuthSession
from app.models.node_file import FileAgent, FileJob
from app.services.session_policy import expired

WRITE_OPS = frozenset(('upload', 'edit', 'create', 'mkdir', 'rename', 'copy', 'move'))
TRANSFER_LIMIT = 32 * 1024 * 1024
CHUNK_SIZE = 64 * 1024


def automatic_owner(db):
    """Explicit deployment opt-in; read the existing owner pin without mutation."""
    if os.environ.get('STELLA_NODE_FILES_ENABLED') != '1' or 'STELLA_NODE_FILE_POLICY' in os.environ:
        return None
    configured = os.environ.get('STELLA_OWNER_ID', '')
    try:
        uid = UUID(configured)
        if str(uid) != configured:
            return None
        from app.services.admin_security import read_state
        _, state = read_state(db)
        if state.get('owner_id') not in (None, '', configured):
            return None
        user = db.get(User, uid)
        return configured if user and user.is_active else None
    except (ValueError, TypeError, AttributeError, HTTPException):
        return None


def automatic_policy(db, node):
    owner = automatic_owner(db)
    # Platform is managed metadata, never a node-name/IP heuristic. fnOS must
    # also have its actual distribution metadata, not just an installer choice.
    linux = node.platform == 'linux' or (node.platform == 'fnos' and
            isinstance(node.os_name, str) and node.os_name.casefold().startswith(('fnos', 'debian gnu/linux')))
    if not owner or not linux or node.status == 'removed' or not node.token:
        return None
    return {'owners': [owner], 'label': '系统目录', 'write': True,
            'identity': digest({'node': node.id, 'token': node.token})}


def agent_config(db, node):
    policy = automatic_policy(db, node)
    value = {'enabled': bool(policy),
             'roots': {'system': {'path': '/', 'write': True}} if policy else {}}
    return {**value, 'revision': digest({'config': value, 'authority': policy})}


def policies(db=None):
    # An explicitly configured legacy policy (even empty) overrides automatic
    # grants in full. With no opt-in or DB identity, keep the historical deny.
    filename = os.environ.get('STELLA_NODE_FILE_POLICY')
    if 'STELLA_NODE_FILE_POLICY' not in os.environ:
        if db is None or automatic_owner(db) is None:
            return {}
        result = {}
        for node in db.scalars(select(Node).where(Node.status != 'removed')):
            policy = automatic_policy(db, node)
            if policy:
                result[str(node.id)] = {'system': policy}
        return result
    if not filename:
        return {}
    try:
        with open(filename, encoding='utf-8') as f:
            value = json.load(f)
        if not isinstance(value, dict):
            raise ValueError()
        for roots in value.values():
            if not isinstance(roots, dict):
                raise ValueError()
            for policy in roots.values():
                if (not isinstance(policy, dict) or
                        not isinstance(policy.get('owners', []), list) or
                        any(not isinstance(owner, str) for owner in policy.get('owners', []))):
                    raise ValueError()
    except (OSError, ValueError, UnicodeError):
        raise HTTPException(503, 'invalid_file_policy') from None
    return value


def grant(owner, node, root, db=None):
    value = policies(db).get(str(node), {}).get(root)
    if not value or str(owner) not in value.get('owners', []):
        raise HTTPException(404, 'root_not_allowed')
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def spool(job):
    # Lazy and ID-only: no paths from users/agents reach the center filesystem.
    base = Path(os.environ.get('STELLA_NODE_FILE_STATE', 'data/node-files'))
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    return base / (str(UUID(job.id)) + '.bytes')


def node_agent(db, token):
    node = db.scalar(select(Node).where(Node.token == token, Node.status != 'removed'))
    if node is None:
        raise HTTPException(401, 'invalid_agent')
    return node


def live(db, node_id):
    agent = db.get(FileAgent, node_id)
    node = db.get(Node, node_id)
    if node is None or node.status != 'online' or agent is None or time.time() - agent.seen > 15:
        raise HTTPException(409, 'node_offline')
    return agent


def valid(db, job, *, commit=True):
    if job.state not in ('uploading', 'pending', 'running', 'committing'):
        return False
    reason = None
    user, session = db.get(User, UUID(job.owner)), db.get(AuthSession, UUID(job.session))
    try:
        policy = grant(job.owner, job.node_id, job.root, db)
        agent = live(db, job.node_id)
        if job.policy != digest(policy) or job.root not in agent.roots or (job.request['op'] in WRITE_OPS and agent.roots[job.root] is not True):
            reason = 'authority_changed'
    except HTTPException:
        reason = 'authority_changed'
    if not user or not user.is_active or not session or str(session.user_id) != job.owner or session.revoked or expired(session):
        reason = 'session_changed'
    if time.time() >= job.expires:
        reason = 'deadline'
    if reason:
        job.state = 'unknown' if job.state in ('running', 'committing') and job.request['op'] in WRITE_OPS else 'cancelled'
        job.error = reason
        spool(job).unlink(missing_ok=True)
        if commit:
            db.commit()
        return False
    return True


def owned(db, job_id, owner, session):
    job = db.scalar(select(FileJob).where(FileJob.id == job_id, FileJob.owner == str(owner), FileJob.session == str(session)).with_for_update())
    if job is None:
        raise HTTPException(404, 'request_not_found')
    valid(db, job)
    return job


def agent_job(db, job_id, node_id, lease):
    job = db.scalar(select(FileJob).where(FileJob.id == job_id, FileJob.node_id == node_id).with_for_update())
    if job is None or not job.lease or not secrets.compare_digest(job.lease, lease):
        raise HTTPException(404, 'request_not_found')
    return job


def public(job):
    result = job.result if job.state == 'done' else None
    if result is not None and job.request['op'] == 'preview':
        path = spool(job)
        if not path.is_file() or time.time() > job.expires + 600:
            raise HTTPException(410, 'preview_expired')
        with path.open('rb') as source:
            data = source.read(256 * 1024 + 1)
        if len(data) > 256 * 1024 or hashlib.sha256(data).hexdigest() != result['etag']:
            raise HTTPException(409, 'preview_changed')
        result = {**result, 'text': data.decode('utf-8')}
    return {'id': job.id, 'request_key': job.request_key, 'node_id': job.node_id, 'root': job.root, 'state': job.state, 'op': job.request['op'], 'result': result, 'error': job.error}


def maintenance(db):
    # Payload retention is bounded independently of the durable metadata journal.
    for job in db.scalars(select(FileJob).where(FileJob.expires < time.time() - 600)):
        path = spool(job)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def spool_budget(db, additional):
    db.execute(text('SELECT pg_advisory_xact_lock(6816371620261023)'))
    base = Path(os.environ.get('STELLA_NODE_FILE_STATE', 'data/node-files'))
    used = sum(p.stat().st_size for p in base.glob('*.bytes') if p.is_file())
    if used + additional > 128 * 1024 * 1024:
        raise HTTPException(413, 'spool_quota')


def create(db, owner, session, data):
    # Serialize root admission across sessions/processes on the actual PG journal.
    key_lock = int.from_bytes(hashlib.sha256(f'{owner}:{session}:{data.request_key}'.encode()).digest()[:8], 'big', signed=True)
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key_lock})
    lock = int.from_bytes(hashlib.sha256(f'{data.node_id}:{data.root}'.encode()).digest()[:8], 'big', signed=True)
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock})
    maintenance(db)
    request = data.model_dump(mode='json')
    policy = grant(owner, data.node_id, data.root, db)
    old = db.scalar(select(FileJob).where(FileJob.owner == str(owner), FileJob.session == str(session), FileJob.request_key == str(data.request_key)))
    if old:
        if old.request != request:
            raise HTTPException(409, 'request_key_conflict')
        if old.policy != digest(policy):
            raise HTTPException(409, 'authority_changed')
        valid(db, old)
        return old
    agent = live(db, data.node_id)
    if data.root not in agent.roots:
        raise HTTPException(409, 'agent_root_not_allowed')
    if data.op in WRITE_OPS and (policy.get('write') is not True or agent.roots[data.root] is not True):
        raise HTTPException(403, 'read_only_root')
    # One in-flight job per session/node/root. Unknown writes block further writes.
    for job in db.scalars(select(FileJob).where(FileJob.node_id == data.node_id, FileJob.root == data.root, FileJob.state.in_(['uploading', 'pending', 'running', 'committing', 'unknown'])).with_for_update()):
        valid(db, job, commit=False)
        if job.state in ('uploading', 'pending', 'running', 'committing') or (job.state == 'unknown' and data.op in WRITE_OPS):
            raise HTTPException(409, 'request_busy_or_unknown')
    job = FileJob(id=str(uuid4()), owner=str(owner), session=str(session), request_key=str(data.request_key), node_id=data.node_id, root=data.root, policy=digest(policy), request=request, state='uploading' if data.op in ('upload', 'edit') else 'pending', expires=time.time() + 60, bytes_received=0)
    db.add(job)
    db.commit()
    return job
