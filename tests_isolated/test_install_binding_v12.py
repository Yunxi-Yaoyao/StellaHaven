"""V12 host/install path: real services + isolated SQLite, subprocess always fenced."""
import json
import pytest
from unittest.mock import Mock
from test_node_monitor_policy import db, node
from app.models.config import AppConfig
from app.services import node as svc

def test_install_uses_applied_owner_origin_not_legacy_host(db,monkeypatch):
    from app.services import access_entries, request_security
    monkeypatch.setattr(access_entries,'pinned_owner',lambda db:'owner')
    monkeypatch.setattr(request_security,'trusted_origins',lambda:{'https://new.example'})
    db.add(AppConfig(key=access_entries.KEY,value=json.dumps({'owner_id':'owner','settings':{'revision':1,'enabled':False,'public_origin':'https://new.example','private_origin':None}})))
    db.add(AppConfig(key='public_host',value='https://legacy.example'));db.commit()
    installer=Mock(return_value={'installed':True,'service':'stella-agent-'+'a'*24})
    monkeypatch.setattr(svc.host_svc,'install_host',installer)
    result=svc.install_host_node(db)
    assert installer.call_args.args==(result.token,'https://new.example')
    assert result.installed is True

@pytest.fixture
def approved(db,monkeypatch):
    from app.services import request_security
    monkeypatch.setenv('STELLA_MAIN_ORIGIN','https://new.example')
    monkeypatch.setattr(request_security,'trusted_origins',lambda:{'https://new.example'})

@pytest.fixture
def client(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.monitor import node_router, current_user, admin_user, get_db
    app=FastAPI();app.include_router(node_router)
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[current_user]=lambda:None
    app.dependency_overrides[admin_user]=lambda:None
    with TestClient(app,base_url='https://new.example') as c:yield c

def test_install_command_reuses_approved_url_and_is_no_store(client,db,approved):
    target=node(db,token='fixture-token-not-a-real-credential')
    r=client.post(f'/nodes/{target.id}/install-command',headers={'Host':'attacker.example'})
    assert r.status_code==200,r.text
    assert r.headers['cache-control']=='no-store'
    assert r.json()['url']=='https://new.example'
    assert target.token in r.json()['command']
    assert 'undefined' not in r.json()['command']

def test_other_center_running_does_not_block_own_instance(client,approved,monkeypatch):
    monkeypatch.setattr(svc.host_svc,'supports_local_install',lambda:True)
    monkeypatch.setattr(svc.host_svc,'is_agent_installed',lambda:True)
    monkeypatch.setattr(svc.host_svc,'install_host',lambda *a:{'installed':True})
    r=client.post('/nodes/host/install')
    assert r.status_code==201,r.text
    assert r.json()['status']=='pending'

@pytest.mark.parametrize('status',['pending','offline'])
def test_non_normal_detail_denied_without_history_read(db,monkeypatch,status):
    from fastapi import HTTPException
    target=node(db,status=status)
    history=Mock(side_effect=AssertionError('must not read detail history'))
    monkeypatch.setattr(svc.repo,'get_latest_metrics',history)
    with pytest.raises(HTTPException) as exc:svc.get_node_detail(db,target.id)
    assert exc.value.status_code==409
    history.assert_not_called()

@pytest.mark.parametrize('scope',['container','unprivileged','timeout','installer_failure'])
def test_host_install_has_explicit_safe_failure(monkeypatch,scope):
    import subprocess
    from app.services import host
    monkeypatch.setattr(host,'supports_local_install',lambda:scope!='container')
    monkeypatch.setattr(host.os,'geteuid',lambda:1000 if scope=='unprivileged' else 0)
    monkeypatch.setattr(host.platform,'system',lambda:'Linux')
    monkeypatch.setattr(host.shutil,'which',lambda name:'/usr/bin/'+name)
    fake=Mock(side_effect=subprocess.TimeoutExpired('installer',180)) if scope=='timeout' else Mock(return_value=subprocess.CompletedProcess([],1,'','secret should not escape'))
    monkeypatch.setattr(host.subprocess,'run',fake)
    with pytest.raises(ValueError) as exc:host.install_host('fixture-token','https://new.example')
    expected={'container':'容器','unprivileged':'root','timeout':'超时','installer_failure':'退出码'}[scope]
    assert expected in str(exc.value)
    assert 'fixture-token' not in str(exc.value)
    assert 'secret should not escape' not in str(exc.value)
    if scope in ('container','unprivileged'):fake.assert_not_called()

def test_real_first_registration_queues_own_host_after_owner_commit(client,db,approved,monkeypatch):
    monkeypatch.setenv('STELLA_COOKIE_SECURE','true')
    from app.routers.auth import router
    from app.models.user import User,AuthSession
    from app.services.node_monitor_policy import host_node
    User.__table__.create(db.get_bind());AuthSession.__table__.create(db.get_bind())
    client.app.include_router(router)
    monkeypatch.setattr(svc.host_svc,'supports_local_install',lambda:True)
    observed=[]
    def install(token,url):
        assert db.query(User).count()==1
        assert host_node(db).token==token
        observed.append(url)
        raise ValueError('root 权限不足，请在真实宿主机运行命令')
    monkeypatch.setattr(svc.host_svc,'install_host',install)
    r=client.post('/auth/register',json={'username':'owner','password':'isolated-fixture-password'})
    assert r.status_code==201,r.text
    assert r.cookies.get('stella_at')
    assert db.query(User).count()==1
    from app.routers.auth import current_user
    del client.app.dependency_overrides[current_user]
    me=client.get('/auth/me')
    assert me.status_code==200,me.text
    assert me.json()['id']==r.json()['id']
    # The fixture must really replay its Secure cookie, not lower production flags.
    assert 'secure' in r.headers['set-cookie'].lower()
    assert len(observed)==1
    info=client.get('/nodes/host').json()
    assert info['node_id']==host_node(db).id
    assert info['installed'] is False
    assert info['installation']['status']=='failed'
    assert 'root' in info['installation']['message']
    # Registration cannot duplicate the owner or enqueue another installation.
    assert client.post('/auth/register',json={'username':'owner2','password':'isolated-fixture-password'}).status_code==403
    assert len(observed)==1

def test_container_prepare_binds_actual_host_without_running_installer(client,db,approved,monkeypatch):
    monkeypatch.setattr(svc.host_svc,'supports_local_install',lambda:False)
    installer=Mock(side_effect=AssertionError('container must not install'))
    monkeypatch.setattr(svc.host_svc,'install_host',installer)
    r=client.post('/nodes/host/prepare')
    assert r.status_code==201,r.text
    identity=r.json()['id']
    assert client.post('/nodes/host/prepare').json()['id']==identity
    info=client.get('/nodes/host').json()
    assert info['node_id']==identity
    assert info['installation_url']=='https://new.example'
    assert client.post(f'/nodes/{identity}/install-command').status_code==200
    assert client.post('/nodes/host/install').status_code==409
    installer.assert_not_called()

@pytest.mark.parametrize('kind',['absent','invalid_saved','untrusted'])
def test_no_install_address_never_uses_request_or_legacy(db,client,monkeypatch,kind):
    from app.services import access_entries,request_security
    monkeypatch.delenv('STELLA_MAIN_ORIGIN',raising=False)
    monkeypatch.delenv('STELLA_ENTRY_REGISTRY',raising=False)
    monkeypatch.setattr(request_security,'trusted_origins',lambda:{'https://new.example'})
    db.add(AppConfig(key='public_host',value='https://legacy.example'))
    if kind=='invalid_saved':
        monkeypatch.setenv('STELLA_MAIN_ORIGIN','https://new.example')
        db.add(AppConfig(key=access_entries.KEY,value='{}'))
    if kind=='untrusted':monkeypatch.setenv('STELLA_MAIN_ORIGIN','https://not-approved.example')
    db.commit();target=node(db,token='fixture-token')
    r=client.post(f'/nodes/{target.id}/install-command',headers={'Host':'new.example','X-Forwarded-Host':'new.example'})
    assert r.status_code in (409,503),r.text
    assert 'command' not in r.json()
    info=client.get('/nodes/host').json()
    assert info['installation_url'] is None
    assert info['installation_address_error']

def test_initialize_only_enqueues_and_uses_fresh_background_session(db,approved,monkeypatch):
    from fastapi import BackgroundTasks
    installer=Mock(side_effect=AssertionError('must not install synchronously'))
    monkeypatch.setattr(svc.host_svc,'install_host',installer)
    monkeypatch.setattr(svc.host_svc,'supports_local_install',lambda:True)
    tasks=BackgroundTasks();svc.initialize_host_install(db,tasks)
    installer.assert_not_called()
    assert len(tasks.tasks)==1
    assert tasks.tasks[0].args[0] is db.get_bind()
    assert tasks.tasks[0].args[0] is not db
    assert svc.host_installation(db)['status']=='queued'

def test_busy_install_route_rejects_duplicate_tasks(client,db,approved,monkeypatch):
    monkeypatch.setattr(svc.host_svc,'supports_local_install',lambda:True)
    svc._host_install_state(db,'installing','fixture running')
    installer=Mock();monkeypatch.setattr(svc.host_svc,'install_host',installer)
    r=client.post('/nodes/host/install')
    assert r.status_code==409,r.text
    installer.assert_not_called()

def test_changed_address_background_failure_is_visible(db,approved,monkeypatch):
    from fastapi import BackgroundTasks
    monkeypatch.setattr(svc.host_svc,'supports_local_install',lambda:True)
    tasks=BackgroundTasks();svc.initialize_host_install(db,tasks)
    monkeypatch.delenv('STELLA_MAIN_ORIGIN')
    task=tasks.tasks[0];task.func(*task.args)
    assert svc.host_installation(db)['status']=='failed'
    assert '地址' in svc.host_installation(db)['message']

def test_online_detail_is_available_and_stale_online_is_denied(db,monkeypatch):
    from datetime import datetime,timezone,timedelta
    from fastapi import HTTPException
    obj=node(db,status='online',last_seen_at=datetime.now(timezone.utc))
    monkeypatch.setattr(svc.repo,'get_latest_metrics',lambda *a:[])
    monkeypatch.setattr(svc.repo,'get_latest_sys_metric',lambda *a:None)
    assert svc.get_node_detail(db,obj.id).status=='online'
    obj.last_seen_at=datetime.now(timezone.utc)-timedelta(minutes=10);db.commit()
    with pytest.raises(HTTPException):svc.get_node_detail(db,obj.id)
