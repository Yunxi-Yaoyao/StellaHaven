"""Real TCP router authorization on the owning nonce PostgreSQL fixture."""
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, text
from app.database import engine, sessionLocal
from app.models import AuthSession, Node, User
from app.models.config import AppConfig
from app.models.node_file import FileAgent, FileJob
from app.security import make_access_token
from app.services import admin_security


@pytest.fixture
def auto(system, monkeypatch):
    # The normal CI runner has its own exact-parent listener/nonce admission.
    if os.getenv('STELLA_CI_OWNED_RECEIPT'):
        from deploy.ci.owned_pg import owned_target
        owned_target()
    else:
        nonce = os.environ['NODE_FILES_AUTO_NONCE']
        marker = Path(os.environ['NODE_FILES_AUTO_RECEIPT'])
        assert re.fullmatch('[a-f0-9]{32}', nonce)
        assert not marker.is_symlink() and marker.stat().st_uid == 0
        assert stat.S_IMODE(marker.stat().st_mode) == 0o600
        identity = json.loads(marker.read_text())
        assert identity['nonce'] == nonce and identity['database'] == os.environ['POSTGRES_DB'] == 'nodefiles_' + nonce
        with engine.connect() as conn:
            assert conn.execute(text('SELECT current_database(), current_user')).one() == (identity['database'], identity['database'])
    monkeypatch.delenv('STELLA_NODE_FILE_POLICY', raising=False)
    monkeypatch.setenv('STELLA_NODE_FILES_ENABLED', '1')
    monkeypatch.setenv('STELLA_OWNER_ID', str(system['uid']))
    other_uid, other_sid = uuid4(), uuid4()
    ids = list(range(940001, 940009))
    with sessionLocal() as db:
        pin = db.get(AppConfig, admin_security.STATE_KEY)
        old_pin = pin.value if pin else None
        if pin is None:
            pin = AppConfig(key=admin_security.STATE_KEY, value='{}')
            db.add(pin)
        pin.value = json.dumps({'owner_id': str(system['uid'])})
        db.add(User(id=other_uid, username='other-' + other_uid.hex, display_name='other'))
        db.flush()
        db.add(AuthSession(id=other_sid, user_id=other_uid, refresh_hash=uuid4().hex))
        for i, (platform, status, os_name) in zip(ids, [('linux','online',None),('linux','offline',None),('windows','online',None),('unknown','online',None),('linux','removed',None),('fnos','online','fnOS 1.0'),('fnos','online',None)]):
            db.add(Node(id=i, name='linux-name-is-not-authority', platform=platform, host='synthetic', status=status, os_name=os_name, token='auto-' + str(i) + '-' + uuid4().hex))
        db.commit()
        tokens = {i: db.get(Node, i).token for i in ids if db.get(Node, i) is not None}
    with httpx.Client(base_url=system['url'], cookies={'stella_at': make_access_token(str(other_uid),str(other_sid))}) as other, httpx.Client(base_url=system['url'], headers={'Authorization':'Bearer ' + tokens[ids[0]]}) as agent:
        yield {**system, 'ids':ids, 'tokens':tokens, 'agent':agent, 'other':other, 'other_uid':other_uid, 'other_sid':other_sid}
    with sessionLocal() as db:
        db.execute(delete(FileJob).where(FileJob.node_id.in_(ids)))
        db.execute(delete(FileAgent).where(FileAgent.node_id.in_(ids)))
        db.execute(delete(Node).where(Node.id.in_(ids)))
        db.execute(delete(AuthSession).where(AuthSession.user_id == other_uid))
        db.execute(delete(User).where(User.id == other_uid))
        db.get(User, system['uid']).is_active = True
        db.get(AuthSession, system['sid']).revoked = False
        pin = db.get(AppConfig, admin_security.STATE_KEY)
        if old_pin is None:
            db.delete(pin)
        else:
            pin.value = old_pin
        db.commit()


def test_config_authenticated_linux_defaults_and_stable_revision(auto):
    a = auto
    response = a['agent'].get('/agent/files/config')
    assert response.status_code == 200, response.text
    value = response.json()
    assert value == {'enabled':True, 'roots':{'system':{'path':'/','write':True}}, 'revision':value['revision']}
    assert re.fullmatch('[a-f0-9]{64}', value['revision'])
    assert a['agent'].get('/agent/files/config').json() == value
    assert response.headers['cache-control'] == 'no-store'
    assert httpx.get(a['url'] + '/agent/files/config').status_code == 401
    assert httpx.get(a['url'] + '/agent/files/config', headers={'Authorization':'Bearer bad'}).status_code == 401
    # Cookies are not an Agent identity; a token in the URL is not accepted.
    assert a['client'].get('/agent/files/config').status_code == 401
    assert httpx.get(a['url'] + '/agent/files/config', params={'token':a['token']}).status_code == 401
    with sessionLocal() as db:
        assert db.get(FileAgent, a['ids'][0]) is None, 'configuration GET must not create presence'
        assert db.query(FileJob).filter(FileJob.node_id.in_(a['ids'])).count() == 0


def test_owner_nodes_automatic_grant_and_existing_request_api(auto):
    a = auto
    response = a['client'].get('/node-files/nodes')
    assert response.status_code == 200, response.text
    nodes = {node['id']:node for node in response.json()}
    assert set(a['ids']).intersection(nodes) == {940001,940002,940006}
    for node in (940001,940002,940006):
        assert nodes[node]['online'] is False, 'no file presence must remain offline'
        assert nodes[node]['roots'] == [{'id':'system','label':'系统目录','write':False,'blocked':False}]
    assert a['other'].get('/node-files/nodes').status_code == 403
    assert httpx.get(a['url'] + '/node-files/nodes').status_code == 401
    # Presence uses the existing pull protocol, not SSH or a second identity.
    claim = a['agent'].post('/agent/files/claim', json={'roots':{'system':True}})
    assert claim.status_code == 200 and claim.json() is None
    nodes = {node['id']:node for node in a['client'].get('/node-files/nodes').json()}
    assert nodes[940001]['online'] is True
    assert nodes[940001]['roots'][0]['write'] is True
    data = {'request_key':str(uuid4()),'node_id':940001,'root':'system','op':'create','path':'root/owned.txt'}
    response = a['client'].post('/node-files/requests', json=data)
    assert response.status_code == 201, response.text
    job = response.json()
    with sessionLocal() as db:
        row = db.get(FileJob, job['id'])
        assert row.request['path'] == 'root/owned.txt' and 'roots' not in row.request
        assert db.get(FileAgent, 940001).roots == {'system':True}
    assert a['other'].post('/node-files/requests', json={**data,'request_key':str(uuid4())}).status_code == 403
    claimed = a['agent'].post('/agent/files/claim', json={'roots':{'system':True}}).json()
    assert claimed['id'] == job['id']
    assert a['client'].post('/node-files/requests/' + job['id'] + '/cancel').json()['state'] == 'unknown'
    assert a['agent'].post('/agent/files/claim', json={'roots':{'system':True}}).json() is None
    assert a['client'].get('/node-files/by-key/' + data['request_key']).json()['state'] == 'unknown'
    assert a['client'].post('/node-files/requests', json={**data,'request_key':str(uuid4())}).status_code == 409


@pytest.mark.parametrize('index,enabled,status', [(0,True,200),(1,True,200),(2,False,200),(3,False,200),(4,False,401),(5,True,200),(6,False,200)])
def test_os_and_removed_agent_config(auto, index, enabled, status):
    a = auto
    response = httpx.get(a['url'] + '/agent/files/config', headers={'Authorization':'Bearer ' + a['tokens'][a['ids'][index]]})
    assert response.status_code == status
    if status == 200:
        assert response.json()['enabled'] is enabled
        assert response.json()['roots'] == ({'system':{'path':'/','write':True}} if enabled else {})
        assert re.fullmatch('[a-f0-9]{64}', response.json()['revision'])


@pytest.mark.parametrize('setting', ['off','missing','invalid-flag','missing-owner','malformed-owner','noncanonical-owner','unknown-owner','inactive-owner','pin-mismatch','legacy-empty','legacy-unset-path','legacy-override'])
def test_disable_invalid_owner_and_explicit_legacy_override(auto, monkeypatch, tmp_path, setting):
    a = auto
    before = a['agent'].get('/agent/files/config').json()
    if setting == 'off': monkeypatch.setenv('STELLA_NODE_FILES_ENABLED','0')
    elif setting == 'missing': monkeypatch.delenv('STELLA_NODE_FILES_ENABLED')
    elif setting == 'invalid-flag': monkeypatch.setenv('STELLA_NODE_FILES_ENABLED','true')
    elif setting == 'missing-owner': monkeypatch.delenv('STELLA_OWNER_ID')
    elif setting == 'malformed-owner': monkeypatch.setenv('STELLA_OWNER_ID','not-a-uuid')
    elif setting == 'noncanonical-owner': monkeypatch.setenv('STELLA_OWNER_ID',' ' + str(a['uid']))
    elif setting == 'unknown-owner': monkeypatch.setenv('STELLA_OWNER_ID',str(uuid4()))
    elif setting == 'inactive-owner':
        with sessionLocal() as db:
            db.get(User,a['uid']).is_active = False
            db.commit()
    elif setting == 'pin-mismatch': monkeypatch.setenv('STELLA_OWNER_ID',str(a['other_uid']))
    else:
        policy = tmp_path / 'explicit-legacy.json'
        value = {'940001':{'legacy':{'owners':[str(a['uid'])],'label':'legacy','write':False}}} if setting == 'legacy-override' else {}
        policy.write_text(json.dumps(value))
        monkeypatch.setenv('STELLA_NODE_FILE_POLICY','' if setting == 'legacy-unset-path' else str(policy))
    response = a['agent'].get('/agent/files/config')
    assert response.status_code == 200, response.text
    value = response.json()
    assert value == {'enabled':False,'roots':{},'revision':value['revision']}
    assert value['revision'] != before['revision']
    assert a['agent'].get('/agent/files/config').json() == value
    response = a['client'].get('/node-files/nodes')
    if setting in {'malformed-owner','noncanonical-owner','unknown-owner','pin-mismatch'}:
        assert response.status_code == 503
    elif setting == 'inactive-owner':
        assert response.status_code == 401
    else:
        assert response.status_code == 200, response.text
        nodes = {node['id']:node for node in response.json()}
        if setting == 'legacy-override':
            assert nodes[940001]['roots'] == [{'id':'legacy','label':'legacy','write':False,'blocked':False}]
        else:
            assert not set(a['ids']).intersection(nodes)


def admit_write(a):
    assert a['agent'].post('/agent/files/claim',json={'roots':{'system':True}}).status_code == 200
    data = {'request_key':str(uuid4()),'node_id':940001,'root':'system','op':'create','path':'root/owned.txt'}
    response = a['client'].post('/node-files/requests',json=data)
    assert response.status_code == 201, response.text
    job = response.json()
    lease = a['agent'].post('/agent/files/claim',json={'roots':{'system':True}}).json()
    assert lease['id'] == job['id']
    return job, lease, data


@pytest.mark.parametrize('change',['off','legacy-deny','owner-inactive','owner-change','token-rotation','removed','nonlinux','session-revoke'])
def test_running_write_invalidated_without_reissue(auto, monkeypatch, tmp_path, change):
    a = auto
    job, lease, data = admit_write(a)
    before = a['agent'].get('/agent/files/config').json()
    headers = {'Authorization':'Bearer ' + a['tokens'][940001]}
    if change == 'off': monkeypatch.setenv('STELLA_NODE_FILES_ENABLED','0')
    elif change == 'legacy-deny':
        policy = tmp_path / 'deny.json'
        policy.write_text('{}')
        monkeypatch.setenv('STELLA_NODE_FILE_POLICY',str(policy))
    else:
        with sessionLocal() as db:
            if change == 'owner-inactive': db.get(User,a['uid']).is_active = False
            elif change == 'owner-change':
                db.get(AppConfig, admin_security.STATE_KEY).value = json.dumps({'owner_id':str(a['other_uid'])})
                monkeypatch.setenv('STELLA_OWNER_ID',str(a['other_uid']))
            elif change == 'token-rotation':
                replacement = 'rotated-' + uuid4().hex
                db.get(Node,940001).token = replacement
                headers = {'Authorization':'Bearer ' + replacement}
            elif change == 'removed': db.get(Node,940001).status = 'removed'
            elif change == 'nonlinux': db.get(Node,940001).platform = 'windows'
            elif change == 'session-revoke': db.get(AuthSession,a['sid']).revoked = True
            db.commit()
    if change == 'removed':
        assert a['agent'].get('/agent/files/config').status_code == 401
        # The original owner reconciliation still invalidates removed-node work.
        assert a['client'].get('/node-files/requests/' + job['id']).status_code == 404
    else:
        response = httpx.get(a['url'] + '/agent/files/requests/' + job['id'],params={'lease':lease['lease']},headers=headers)
        assert response.status_code == 200 and response.json() == {'state':'unknown'}, response.text
        config = httpx.get(a['url'] + '/agent/files/config',headers=headers).json()
        if change != 'session-revoke': assert config['revision'] != before['revision']
        if change == 'token-rotation': assert a['agent'].get('/agent/files/config').status_code == 401
        late = httpx.post(a['url'] + '/agent/files/requests/' + job['id'] + '/admit',params={'lease':lease['lease']},headers=headers)
        assert late.status_code == 409
        late = httpx.post(a['url'] + '/agent/files/requests/' + job['id'] + '/result',json={'lease':lease['lease'],'result':{}},headers=headers)
        assert late.status_code == 409
        assert httpx.post(a['url'] + '/agent/files/claim',json={'roots':{'system':True}},headers=headers).json() is None
    with sessionLocal() as db:
        row = db.get(FileJob,job['id'])
        assert row.state == 'unknown' and row.lease == lease['lease']
        assert row.error in {'authority_changed','session_changed'}
        assert row.request['path'] == data['path']


@pytest.mark.parametrize('contents', ['{broken', '[]', '{"940001":null}', '{"940001":{"system":null}}', '{"940001":{"system":{"owners":"bad"}}}', None])
def test_malformed_legacy_policy_fails_closed_with_service_error(auto, monkeypatch, tmp_path, contents):
    a = auto
    policy = tmp_path / 'broken.json'
    if contents is not None:
        policy.write_text(contents)
    monkeypatch.setenv('STELLA_NODE_FILE_POLICY',str(policy))
    response = a['client'].get('/node-files/nodes')
    assert response.status_code == 503, response.text
    assert response.json() == {'detail':'invalid_file_policy'}
    assert a['agent'].get('/agent/files/config').json()['enabled'] is False


def test_new_linux_node_inherits_without_local_policy_edit(auto):
    a = auto
    before = a['agent'].get('/agent/files/config').json()
    token = 'new-node-' + uuid4().hex
    with sessionLocal() as db:
        db.add(Node(id=940008,name='future node',platform='linux',status='online',host='synthetic-new',token=token))
        db.commit()
    response = httpx.get(a['url']+'/agent/files/config',headers={'Authorization':'Bearer '+token})
    assert response.status_code == 200 and response.json()['roots'] == before['roots']
    assert response.json()['revision'] != before['revision'], 'node authority is part of revision'
    nodes = {node['id']:node for node in a['client'].get('/node-files/nodes').json()}
    assert nodes[940008]['online'] is False
    assert nodes[940008]['roots'] == [{'id':'system','label':'系统目录','write':False,'blocked':False}]


@pytest.mark.parametrize('op',['list','create'])
def test_pending_work_cancelled_before_claim_after_disable(auto, monkeypatch, op):
    a = auto
    a['agent'].post('/agent/files/claim',json={'roots':{'system':True}}).raise_for_status()
    data = {'request_key':str(uuid4()),'node_id':940001,'root':'system','op':op,'path':'root/not-executed'}
    response = a['client'].post('/node-files/requests',json=data)
    assert response.status_code == 201
    job = response.json()
    monkeypatch.setenv('STELLA_NODE_FILES_ENABLED','0')
    assert a['agent'].post('/agent/files/claim',json={'roots':{'system':True}}).json() is None
    with sessionLocal() as db:
        row = db.get(FileJob,job['id'])
        assert row.state == 'cancelled' and row.lease is None
    assert a['client'].post('/node-files/requests',json=data).status_code == 404


def test_config_schema_is_closed_and_never_loosens_file_paths(auto):
    from pydantic import TypeAdapter, ValidationError
    from app.schemas.node_file import AgentFilesConfig, FileRequest
    from app.api_response_contracts import schema_holes
    adapter = TypeAdapter(AgentFilesConfig)
    assert schema_holes(adapter.json_schema()) == []
    revision = auto['agent'].get('/agent/files/config').json()['revision']
    adapter.validate_python({'enabled':False,'roots':{},'revision':revision})
    for value in [
        {'enabled':True,'roots':{},'revision':revision},
        {'enabled':False,'roots':{'system':{'path':'/','write':True}},'revision':revision},
        {'enabled':True,'roots':{'system':{'path':'/root','write':True}},'revision':revision},
        {'enabled':True,'roots':{'system':{'path':'/','write':False}},'revision':revision},
        {'enabled':False,'roots':{'other':{}},'revision':revision},
        {'enabled':False,'roots':{},'revision':'bad'},
        {'enabled':1,'roots':{'system':{'path':'/','write':True}},'revision':revision},
        {'enabled':0,'roots':{},'revision':revision},
        {'enabled':True,'roots':{'system':{'path':'/','write':1}},'revision':revision},
    ]:
        with pytest.raises(ValidationError): adapter.validate_python(value)
    with pytest.raises(ValidationError):
        FileRequest(request_key=uuid4(),node_id=940001,root='system',op='preview',path='/root/seed.txt')


@pytest.mark.parametrize('platform,os_name,enabled', [
    ('fnos','debian gnu/linux 12 (bookworm)',True),
    ('fnos','DEBIAN GNU/LINUX 12 (bookworm)',True),
    ('fnos','Windows 11',False), ('fnos','Ubuntu Linux',False),
    ('fnos','NAS Debian GNU/Linux 12',False),
    ('fnos',' Debian GNU/Linux 12',False), ('fnos','',False),
    ('fnos',None,False), ('unknown','Debian GNU/Linux 12',False),
    ('windows','Debian GNU/Linux 12',False),
])
def test_fnos_distribution_prefix_is_anchored_and_managed(auto, platform, os_name, enabled):
    with sessionLocal() as db:
        node = db.get(Node, 940001)
        node.platform, node.os_name = platform, os_name
        db.commit()
    response = auto['agent'].get('/agent/files/config')
    assert response.status_code == 200, response.text
    assert response.json()['enabled'] is enabled
    assert response.json()['roots'] == ({'system':{'path':'/','write':True}} if enabled else {})
    nodes = {node['id']:node for node in auto['client'].get('/node-files/nodes').json()}
    assert (940001 in nodes) is enabled


@pytest.mark.parametrize('boundary', ['off','inactive-owner','removed','empty-token'])
def test_fnos_debian_keeps_authority_denials(auto, monkeypatch, boundary):
    from app.services.node_files import automatic_policy
    with sessionLocal() as db:
        node = db.get(Node, 940001)
        node.platform, node.os_name = 'fnos', 'Debian GNU/Linux 12 (bookworm)'
        if boundary == 'off': monkeypatch.setenv('STELLA_NODE_FILES_ENABLED','0')
        elif boundary == 'inactive-owner': db.get(User,auto['uid']).is_active = False
        elif boundary == 'removed': node.status = 'removed'
        else: node.token = ''
        db.commit()
        assert automatic_policy(db, node) is None
    response = auto['agent'].get('/agent/files/config')
    assert response.status_code == (401 if boundary in {'removed','empty-token'} else 200)
    if response.status_code == 200:
        assert response.json()['enabled'] is False and response.json()['roots'] == {}


def test_fnos_debian_report_automatic_config_and_real_root_worker(auto, tmp_path, monkeypatch):
    """fnOS reports the real /etc/os-release Debian PRETTY_NAME, not fnOS."""
    a = auto
    with sessionLocal() as db:
        node = db.get(Node, 940001)
        node.platform = 'fnos'
        node.os_name = 'Debian GNU/Linux 12 (bookworm)'
        db.commit()
    response = a['agent'].get('/agent/files/config')
    assert response.status_code == 200, response.text
    value = response.json()
    assert value == {'enabled':True, 'roots':{'system':{'path':'/','write':True}}, 'revision':value['revision']}
    assert a['agent'].post('/agent/files/claim', json={'roots':{'system':True}}).json() is None
    with sessionLocal() as db:
        assert db.get(FileAgent, 940001).roots == {'system':True}
        node = db.get(Node, 940001)
        assert (node.platform, node.os_name) == ('fnos', 'Debian GNU/Linux 12 (bookworm)')
    nodes = {node['id']:node for node in a['client'].get('/node-files/nodes').json()}
    assert nodes[940001]['online'] is True
    assert nodes[940001]['roots'] == [{'id':'system','label':'系统目录','write':True,'blocked':False}]
    evidence = Path(os.environ['NODE_FILES_EVIDENCE']) / 'fnos-debian-worker'
    evidence.mkdir()
    monkeypatch.setenv('NODE_FILES_EVIDENCE', str(evidence))
    test_default_config_real_root_worker_reads_and_writes_fabricated_root(a, tmp_path)


def test_default_config_real_root_worker_reads_and_writes_fabricated_root(auto, tmp_path):
    """Real separate UID0 worker + HTTP/PG; no host / operation or service install."""
    import hashlib
    import select
    import subprocess
    import sys
    a = auto
    root = tmp_path / 'fabricated-system'
    root.mkdir()
    (root/'root').mkdir(mode=0o700)
    (root/'root'/'seed.txt').write_text('synthetic root-owned body\n')
    (root/'root'/'seed.txt').chmod(0o600)
    (root/'root'/'escape').symlink_to('../outside')
    config = tmp_path / 'private-worker.json'
    config.write_text(json.dumps({'url':a['url'],'token':a['tokens'][940001],'fabricated_root':str(root)}))
    config.chmod(0o600)
    repo = Path(__file__).resolve().parents[1]
    env = {'PATH':'/usr/bin:/bin','HOME':str(tmp_path),'TMPDIR':str(tmp_path),'PYTHONPATH':str(repo),'PYTHONDONTWRITEBYTECODE':'1'}
    events = []
    with (tmp_path/'worker-errors.log').open('w') as errors:
        child = subprocess.Popen([sys.executable,'-B','-u',str(repo/'tests_node_files/auto_root_worker.py'),str(config)],env=env,cwd=tmp_path,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True)
        def read_event():
            assert select.select([child.stdout],[],[],15)[0], 'worker event timeout'
            line = child.stdout.readline()
            assert line, (tmp_path/'worker-errors.log').read_text()
            event = json.loads(line)
            events.append(event)
            return event
        def run(op,path='',body=None,**extra):
            data = {'request_key':str(uuid4()),'node_id':940001,'root':'system','op':op,'path':path,**extra}
            if body is not None: data.update(size=len(body),sha256=hashlib.sha256(body).hexdigest())
            admitted = a['client'].post('/node-files/requests',json=data)
            assert admitted.status_code == 201, admitted.text
            job = admitted.json()
            if body is not None:
                assert a['client'].put('/node-files/requests/'+job['id']+'/upload',params={'offset':0},content=body).status_code == 200
                assert a['client'].post('/node-files/requests/'+job['id']+'/seal').status_code == 200
            child.stdin.write('tick\n'); child.stdin.flush()
            assert read_event() == {'event':'tick'}
            response = a['client'].get('/node-files/requests/'+job['id'])
            assert response.status_code == 200, response.text
            result = response.json()
            assert result['state'] in {'done','failed'},result
            return result
        try:
            ready = read_event()
            assert ready['event'] == 'ready' and ready['uid'] == 0 and ready['pid'] != os.getpid()
            assert ready['app_imported'] is False
            assert ready['roots'] == {'system':{'path':'/','write':True}}
            assert ready['module_sha256'] == hashlib.sha256((repo/'agent/node_files.py').read_bytes()).hexdigest()
            listing = run('list','root')
            assert 'seed.txt' in [entry['name'] for entry in listing['result']['entries']]
            preview = run('preview','root/seed.txt')
            assert preview['result']['text'] == 'synthetic root-owned body\n'
            assert run('create','root/created.txt')['state'] == 'done'
            assert (root/'root'/'created.txt').read_bytes() == b''
            assert run('upload','root/upload.txt',body=b'uploaded synthetic root bytes')['state'] == 'done'
            assert (root/'root'/'upload.txt').read_bytes() == b'uploaded synthetic root bytes'
            assert run('edit','root/seed.txt',body=b'edited root body',etag=preview['result']['etag'])['state'] == 'done'
            assert (root/'root'/'seed.txt').read_bytes() == b'edited root body'
            assert stat.S_IMODE((root/'root'/'seed.txt').stat().st_mode) == 0o600
            assert run('rename','root/created.txt',destination='root/renamed.txt')['state'] == 'done'
            downloaded = run('download','root/seed.txt')
            response = a['client'].get('/node-files/requests/'+downloaded['id']+'/download')
            assert response.status_code == 200 and response.content == b'edited root body'
            assert response.headers['x-file-sha256'] == hashlib.sha256(response.content).hexdigest()
            assert run('preview','root/escape/never')['state'] == 'failed'
            child.stdin.write('stop\n');child.stdin.flush()
            assert read_event() == {'event':'stopped'}
            assert child.wait(timeout=10) == 0
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
            assert not Path('/proc/'+str(child.pid)).exists()
            evidence = Path(os.environ['NODE_FILES_EVIDENCE'])
            (evidence/'automatic-root-worker-events.json').write_text(json.dumps(events,indent=2))
            (evidence/'automatic-root-worker-errors.log').write_text((tmp_path/'worker-errors.log').read_text())
    with sessionLocal() as db:
        jobs = db.query(FileJob).filter(FileJob.node_id==940001).all()
        assert jobs and all(row.state in {'done','failed'} for row in jobs)
        assert all(not row.request['path'].startswith('/') for row in jobs)
        assert all('text' not in (row.result or {}) for row in jobs)
