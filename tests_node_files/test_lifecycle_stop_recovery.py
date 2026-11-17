"""P1 safety oracle: original independent fault injection, real UID/PG/HTTP."""
import hashlib, io, json, os, pwd, subprocess, sys, tarfile, time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
from tests_node_files.test_lifecycle_protocol import make_fixture, real_identity_transport

OUT=Path(os.environ['NODE_FILES_EVIDENCE'])
ART=Path('/opt/hermes-workstation/docs/records/2026-10-23-stella-production-feedback/node-files-completion/lifecycle/build')
OUTER='f2e67e8aee4e842cbb66cd62b82dc0bd15f5e3404d1cf9288f89cd224465969a'
INNER='1a7008d9ee39f40c793c89b41c71d8e549fc22af712ad2c56c91ac3fb62ff969'

def unprivileged(system,tmp_path,monkeypatch):
    account=pwd.getpwnam('nobody')
    lc,lifecycle,adapter,main_unit,env=make_fixture(system,tmp_path,monkeypatch)
    for p in (tmp_path,*tmp_path.parents,lifecycle.code.parent,lifecycle.config.parent,lifecycle.config):
        if p==Path('/mnt') or p.is_relative_to('/mnt'):p.chmod(0o755)
    os.chown(lifecycle.code,account.pw_uid,account.pw_gid)
    os.chown(lifecycle.code/'stella_agent.py',account.pw_uid,account.pw_gid)
    monkeypatch.setattr(lc.pwd,'getpwnam',lambda name:account)
    lifecycle=lc.Lifecycle(lifecycle.iid,code_base=lifecycle.code.parent,config_base=lifecycle.config.parent,unit_base=lifecycle.unit.parent,systemd=adapter,allow_loopback=True)
    adapter.uid,adapter.gid=account.pw_uid,account.pw_gid
    return lc,lifecycle,adapter

def test_failed_activation_retains_recovery_and_controlled_stop(system,tmp_path,monkeypatch):
    lc,lifecycle,adapter=unprivileged(system,tmp_path,monkeypatch)
    owned=tmp_path/'synthetic-authorized-root';owned.mkdir(mode=0o700);os.chown(owned,adapter.uid,adapter.gid)
    filesenv=lifecycle.config/'files.env';filesenv.write_text('STELLA_FILE_ROOTS='+json.dumps(json.dumps({'fixture':{'path':str(owned),'write':True}}))+'\n');filesenv.chmod(0o600)
    package=tmp_path/'exact.tar';pin=lc.build_package(Path(lc.__file__).parent,package)
    original_info,original_call=adapter.info,adapter.call
    injected={'readback':False,'stop':False}
    def info(service):
        if adapter.restarts and not injected['readback']:
            injected['readback']=True
            raise lc.LifecycleError('owned_unknown_start_readback')
        return original_info(service)
    def call(*args,**kwargs):
        if args[0]=='stop' and not injected['stop']:
            injected['stop']=True
            adapter.events.append(['stop','injected-nonzero-no-effect'])
            return SimpleNamespace(returncode=1)
        return original_call(*args,**kwargs)
    monkeypatch.setattr(adapter,'info',info);monkeypatch.setattr(adapter,'call',call)
    try:
        with pytest.raises(lc.LifecycleError):
            lifecycle.install(package,pin['sha256'],pin['release'],sys.executable)
        assert injected == {'readback':True,'stop':True}
        assert adapter.process.poll() is None
        pid=adapter.process.pid
        proc=Path('/proc/'+str(pid)+'/status').read_text()
        assert set(next(s for s in proc.splitlines() if s.startswith('Uid:')).split()[1:]) == {'65534'}
        assert lifecycle.unit.exists() and lifecycle.state_path.exists() and (lifecycle.base/'releases/current.json').exists(), 'stop failure must not delete recovery metadata'
        state=lifecycle.state()
        assert state['recovery_unknown']['candidate']['package_sha256']==pin['sha256']
        assert state['recovery_unknown']['previous'] is None
        status=lifecycle.status()
        assert status['recovery_unknown'] and status['roots_granted'] is None and not status['authenticated_ready']
        # The same uncertainty still leaves the real worker able to write ONLY its synthetic grant.
        response=system['client'].post('/node-files/requests',json={'request_key':str(uuid4()),'node_id':930001,'root':'fixture','op':'create','path':'after-failed-install'})
        assert response.status_code==201,response.text
        for _ in range(80):
            result=system['client'].get('/node-files/requests/'+response.json()['id']).json()
            if result['state'] in ('done','failed','unknown'):break
            time.sleep(.05)
        assert result['state']=='done' and (owned/'after-failed-install').read_bytes()==b''
        # Unknown install may not blindly restart business processing.
        restarts=adapter.restarts
        with pytest.raises(lc.LifecycleError,match='recovery_unknown'):
            lifecycle.install(package,pin['sha256'],pin['release'],sys.executable)
        assert adapter.restarts==restarts
        # Reconstruct helper: recovery must survive beyond the original Python object.
        again=lc.Lifecycle(lifecycle.iid,code_base=lifecycle.code.parent,config_base=lifecycle.config.parent,unit_base=lifecycle.unit.parent,systemd=adapter,allow_loopback=True)
        stopped=again.stop()
        assert adapter.process.poll() is not None and not Path('/proc/'+str(pid)).exists()
        assert stopped['systemd']['ActiveState']=='inactive' and stopped['systemd']['MainPID']=='0'
        assert not stopped['installed']
        (OUT/'recovery-real-worker.json').write_text(json.dumps({'injected':injected,'pid':pid,'uid':65534,'preserved_state':state,'status':status,'synthetic_write':result,'second_stop':stopped,'events':adapter.events,'pid_absent':True},indent=2))
    finally:
        adapter.halt()
        if adapter.process:
            assert adapter.process.poll() is not None
            (OUT/'recovery-cleanup.json').write_text(json.dumps({'pid':adapter.process.pid,'proc_absent':not Path('/proc/'+str(adapter.process.pid)).exists()}))

@pytest.mark.parametrize('fault', ['nonzero', 'timeout', 'active', 'pid', 'unknown'])
@pytest.mark.parametrize('operation', ['update', 'stop'])
def test_uncertain_stop_keeps_exact_old_and_candidate_identity(system,tmp_path,monkeypatch,fault,operation):
    lc,lifecycle,adapter=unprivileged(system,tmp_path,monkeypatch)
    package=tmp_path/'old.tar';old=lc.build_package(Path(lc.__file__).parent,package)
    try:
        lifecycle.install(package,old['sha256'],old['release'],sys.executable)
        pointer=lifecycle.base/'releases/current.json'
        saved={p:p.read_bytes() for p in (pointer,lifecycle.unit,lifecycle.state_path)}
        old_state=lifecycle.state()
        source=tmp_path/'candidate';source.mkdir()
        for name in ('stella_agent.py','node_files.py','node_files_delivery.py','node_files_lifecycle.py'):
            data=(Path(lc.__file__).parent/name).read_bytes()
            if name=='node_files.py':data=data.replace(b"FILE_MODULE_VERSION = '1.0.0'",b"FILE_MODULE_VERSION = '1.0.3'")
            (source/name).write_bytes(data)
        candidate_package=tmp_path/'candidate.tar';candidate=lc.build_package(source,candidate_package)
        original_info,original_call=adapter.info,adapter.call
        injected={'startup':False,'stop':False,'readback':False}
        def info(service):
            if operation=='update' and adapter.restarts==2 and not injected['startup']:
                injected['startup']=True
                raise lc.LifecycleError('owned_unknown_start_readback')
            value=original_info(service)
            if injected['stop'] and not injected['readback'] and fault in ('active','pid','unknown'):
                injected['readback']=True
                if fault=='unknown':raise lc.LifecycleError('owned_unknown_stop_readback')
                if fault=='pid':value['ActiveState']='inactive'
                return value
            return value
        def call(*args,**kwargs):
            if args[0]=='stop' and not injected['stop']:
                injected['stop']=True
                adapter.events.append(['stop','injected-'+fault+'-no-effect'])
                if fault=='timeout':raise subprocess.TimeoutExpired('owned stop',45)
                return SimpleNamespace(returncode=1 if fault=='nonzero' else 0)
            return original_call(*args,**kwargs)
        monkeypatch.setattr(adapter,'info',info);monkeypatch.setattr(adapter,'call',call)
        with pytest.raises(lc.LifecycleError):
            if operation=='update':lifecycle.install(candidate_package,candidate['sha256'],candidate['release'],sys.executable)
            else:lifecycle.stop()
        assert injected['stop'] and adapter.process.poll() is None
        state=lifecycle.state();recovery=state.get('recovery_unknown')
        assert recovery, 'stop uncertainty must remain explicit and durable'
        if operation=='update':
            assert recovery['previous']==old_state
            assert recovery['old_pointer'].encode()==saved[pointer]
            assert recovery['old_unit'].encode()==saved[lifecycle.unit]
            assert recovery['candidate']['package_sha256']==candidate['sha256']
            assert json.loads(pointer.read_bytes())['release']==candidate['release']
        else:
            assert recovery['candidate']==old_state
            assert pointer.read_bytes()==saved[pointer]
        pid=adapter.process.pid
        status=lifecycle.status()
        assert status['recovery_unknown'] and status['roots_granted'] is None
        with pytest.raises(lc.LifecycleError,match='recovery_unknown'):
            lifecycle.install(package,old['sha256'],old['release'],sys.executable)
        lifecycle.stop()
        assert not Path('/proc/'+str(pid)).exists() and adapter.process.poll() is not None
        assert lifecycle.state_path.read_bytes()==saved[lifecycle.state_path]
        assert lifecycle.unit.read_bytes()==saved[lifecycle.unit]
        assert pointer.read_bytes()==saved[pointer]
        assert lifecycle.status()['systemd']['MainPID']=='0' and not adapter.enabled
        (OUT/('recovery-'+operation+'-'+fault+'.json')).write_text(json.dumps({'fault':fault,'operation':operation,'pid':pid,'pid_absent':True,'recovery':recovery,'old_pointer_unit_state_exact':True,'events':adapter.events},indent=2))
    finally:
        adapter.halt()


@pytest.mark.parametrize('foreign', ['unit-bytes','fragment'])
def test_recovery_never_stops_foreign_unit(system,tmp_path,monkeypatch,foreign):
    lc,lifecycle,adapter=unprivileged(system,tmp_path,monkeypatch)
    package=tmp_path/'package.tar';pins=lc.build_package(Path(lc.__file__).parent,package)
    try:
        lifecycle.install(package,pins['sha256'],pins['release'],sys.executable)
        original=adapter.call
        def failed(*args,**kw):
            if args[0]=='stop':return SimpleNamespace(returncode=1)
            return original(*args,**kw)
        monkeypatch.setattr(adapter,'call',failed)
        with pytest.raises(lc.LifecycleError):lifecycle.stop()
        assert lifecycle.state().get('recovery_unknown')
        monkeypatch.setattr(adapter,'call',original)
        if foreign=='unit-bytes':lifecycle.unit.write_text('[Service]\nExecStart=/unknown\n')
        else:
            old_info=adapter.info
            def info(service):return dict(old_info(service),FragmentPath='/unknown/foreign.service')
            monkeypatch.setattr(adapter,'info',info)
        before=list(adapter.events)
        with pytest.raises(lc.LifecycleError,match='foreign_companion_unit'):lifecycle.stop()
        assert adapter.events==before and adapter.process.poll() is None
    finally:
        adapter.halt()


@pytest.mark.parametrize('orphan', ['residual-unit','active-pid','active-zero-pid','unknown'])
def test_stateless_orphan_never_claims_uninstalled_or_stops_unknown(system,tmp_path,monkeypatch,orphan):
    lc,lifecycle,adapter,_,_=make_fixture(system,tmp_path,monkeypatch)
    if orphan=='residual-unit':lifecycle.unit.write_text('[Service]\nExecStart=/unknown\n')
    old_info=adapter.info
    def info(service):
        value=old_info(service)
        if orphan=='active-pid':value.update(ActiveState='active',MainPID='99999999')
        elif orphan=='active-zero-pid':value.update(ActiveState='active')
        elif orphan=='unknown':value.pop('MainPID')
        return value
    monkeypatch.setattr(adapter,'info',info)
    for action in (lifecycle.status,lifecycle.stop):
        with pytest.raises(lc.LifecycleError,match='recovery_unknown'):action()
    assert adapter.events==[]
