"""Runtime ownership tests: real methods; no subprocess or remote operations."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import pytest
ROOT = Path(__file__).resolve().parents[1]

def load(tmp_path):
    source = (ROOT/'agent/stella_agent.py').read_text()
    for base in ('/opt/stella-agents','/etc/stella-agents','/usr/local/libexec'):
        source = source.replace(base,str(tmp_path)+base)
    ns = {'__name__':'isolated_agent_v11','__file__':str(ROOT/'agent/stella_agent.py')}
    exec(compile(source,ns['__file__'],'exec'),ns)
    return ns

def test_unscoped_code_cannot_launch_legacy_uninstall(tmp_path):
    ns = load(tmp_path); obj = ns['Agent'].__new__(ns['Agent'])
    with patch.dict(os.environ,{},clear=True):
        with pytest.raises(ValueError,match='unscoped uninstall refused'): obj._instance_uninstall_argv()

def test_instance_uninstall_uses_only_local_manifest_and_exact_helper(tmp_path):
    ns = load(tmp_path); obj = ns['Agent'].__new__(ns['Agent'])
    iid = ns['hashlib'].sha256(('stella-instance-v1:'+'a'*64).encode()).hexdigest()[:24]
    code = tmp_path/'opt/stella-agents'/iid; code.mkdir(parents=True)
    ns['__file__'] = str(code/'stella_agent.py')
    manifest = tmp_path/'etc/stella-agents'/iid/'instance.json'; manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(dict(format=1,center_id='a'*64,node_id=7,instance_id=iid,service='stella-agent-'+iid,slot='')))
    with patch.dict(os.environ,{'STELLA_INSTANCE_ID':iid,'STELLA_INSTANCE_MANIFEST':str(manifest)},clear=True):
        assert obj._instance_uninstall_argv() == ['sudo','-n',str(tmp_path/'usr/local/libexec'/('stella-agent-'+iid)),'--schedule']
        value = json.loads(manifest.read_text()); value['instance_id'] = 'b'*24; manifest.write_text(json.dumps(value))
        with pytest.raises(ValueError): obj._instance_uninstall_argv()

def test_instance_channel_policy_cannot_rebind_on_first_configuration(tmp_path):
    ns = load(tmp_path); obj = ns['Agent'].__new__(ns['Agent'])
    obj._installation = dict(center_id='a'*64,node_id=7)
    obj._channel_policy = None
    policy = dict(revision=0,epoch='initial',nonce='c'*64,center_id='b'*64,token_binding='d'*64,node_id=7,
                  mode='default',selected_entry_id='public',entries=[dict(entry_id='public',origin='https://center.invalid')])
    with pytest.raises(ValueError,match='installation'): obj._channel_validate(policy)

def test_instance_update_honors_installer_lock(tmp_path):
    import fcntl
    ns = load(tmp_path); obj = ns['Agent'].__new__(ns['Agent'])
    obj._installation = dict(instance_id='a'*24)
    ns['__file__'] = str(tmp_path/'stella_agent.py')
    called = []
    obj._download_and_restart_owned = lambda info: called.append(info)
    with (tmp_path/'.update.lock').open('w') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        obj._download_and_restart({'version':'9.0.0'})
    assert called == []
    obj._download_and_restart({'version':'9.0.0'})
    assert called == [{'version':'9.0.0'}]

def test_foreign_center_identity_blocks_config_and_task_control(tmp_path):
    ns = load(tmp_path); obj = ns['Agent'].__new__(ns['Agent'])
    obj._installation = dict(center_id='a'*64,node_id=7)
    obj.token = 'fixture-token'
    obj._get = lambda *args,**kwargs: dict(center_id='b'*64,node_id=7)
    with pytest.raises(ValueError): obj._assert_instance_identity()
