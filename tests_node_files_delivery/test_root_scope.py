"""Explicit / policy only; filesystem probes run in an owned mount/chroot."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from agent import node_files as nf

REPO = Path(__file__).resolve().parents[1]


def root_probe(tmp_path, case):
    """Load only candidate code, then bind/chroot to fabricated scratch /.

    No operation is ever issued against the host /. UID is dropped before any
    Sandbox operation; this is not a service install or a privilege grant.
    """
    root = tmp_path / 'owned-root'
    root.mkdir(mode=0o755)
    (root / 'etc').mkdir(mode=0o755)
    (root / 'etc' / 'ordinary.conf').write_text('fixture-only=yes\n')
    (root / 'etc' / 'ordinary.conf').chmod(0o644)
    (root / 'writable').mkdir(mode=0o700)
    os.chown(root / 'writable', 65534, 65534)
    (root / 'denied').mkdir(mode=0o700)
    (root / 'etc' / 'no-read').write_text('synthetic-not-a-credential')
    (root / 'etc' / 'no-read').chmod(0o600)
    (root / 'link').symlink_to('etc', target_is_directory=True)
    (root / 'etc' / 'link').symlink_to('ordinary.conf')
    os.link(root / 'etc' / 'ordinary.conf', root / 'etc' / 'hard')
    (root / 'etc' / 'single.conf').write_text('fixture-only=yes\n')
    (root / 'etc' / 'single.conf').chmod(0o644)
    os.mkfifo(root / 'pipe', 0o644)
    with (root / 'large').open('wb') as file:
        file.truncate(nf.TRANSFER_LIMIT + 1)
    (root / 'large').chmod(0o644)
    if case == 'root-permission':
        root.chmod(0o000)
    code = '''import importlib.util,json,os,subprocess,sys,uuid,hashlib,ctypes
spec=importlib.util.spec_from_file_location('root_candidate',sys.argv[1]);nf=importlib.util.module_from_spec(spec);spec.loader.exec_module(nf)
subprocess.run(['/usr/bin/mount','--bind',sys.argv[2],sys.argv[2]],check=True)
os.chroot(sys.argv[2]);os.chdir('/');os.setgroups([]);os.setgid(65534);os.setuid(65534)
s=nf.Sandbox({'system':{'path':'/'}})
case=sys.argv[3]
def denied(call,expected=None):
    try:call()
    except nf.FileError as e:
        if expected:assert str(e)==expected,(str(e),expected)
        return str(e)
    raise AssertionError('unexpected access')
if case=='browse':
    entries=s.execute({'op':'list','root':'system','path':''})['entries'];assert 'etc' in [e['name'] for e in entries]
    assert 'single.conf' in [e['name'] for e in s.execute({'op':'list','root':'system','path':'etc'})['entries']]
    assert s.execute({'op':'preview','root':'system','path':'etc/single.conf'})['text']=='fixture-only=yes\\n'
    assert b''.join(s.stream('system','etc/single.conf'))==b'fixture-only=yes\\n'
    denied(lambda:s.execute({'op':'list','root':'system','path':'','limit':1}),'directory_limit')
    denied(lambda:s.execute({'op':'preview','root':'system','path':'large'}),'preview_limit')
    denied(lambda:list(s.stream('system','large')),'transfer_limit')
    denied(lambda:s.execute({'op':'create','root':'system','path':'writable/refused'}),'read_only_root')
    assert not os.path.exists('/writable/refused')
elif case=='negative':
    for p in ['link/single.conf','etc/link','etc/hard','pipe']:
        denied(lambda:s.execute({'op':'preview','root':'system','path':p}));denied(lambda:list(s.stream('system',p)))
    for p in ['../etc','/etc','etc/../etc','etc//x','etc/./x','etc\\x00x']:
        denied(lambda:s.execute({'op':'list','root':'system','path':p}),'invalid_path')
    denied(lambda:s.execute({'op':'preview','root':'system','path':''}),'invalid_path')
    denied(lambda:s.execute({'op':'list','root':'unknown','path':''}),'root_denied')
    w=nf.Sandbox({'separate':{'path':'/writable','write':True}})
    w.execute({'op':'create','root':'separate','path':'explicit-only'});assert open('/writable/explicit-only','rb').read()==b''
elif case=='permissions':
    errors=[denied(lambda:s.execute({'op':'list','root':'system','path':'denied'}),'permission_denied'),denied(lambda:s.execute({'op':'preview','root':'system','path':'etc/no-read'}),'permission_denied'),denied(lambda:list(s.stream('system','etc/no-read')),'permission_denied')]
    assert errors==['permission_denied']*3
elif case=='root-permission':
    denied(lambda:s.execute({'op':'list','root':'system','path':''}),'permission_denied')
else:raise AssertionError(case)
print(json.dumps({'case':case,'uid':os.geteuid(),'root':'owned fabricated chroot','host_file_reads':False,'passed':True}))
'''
    prefix = ['/usr/bin/unshare', '--mount', '--propagation', 'private']
    if os.environ.get('STELLA_CI_OWNED_RECEIPT'):
        from deploy.ci.owned_pg import owned_target
        owned_target()
        # Self-bind adds no isolation to this already private fabricated root.
        # Keep actual chroot/UID65534 and every original permission assertion.
        code = code.replace("subprocess.run(['/usr/bin/mount','--bind',sys.argv[2],sys.argv[2]],check=True)\n", '')
        prefix = []
    result = subprocess.run([*prefix, sys.executable, '-I', '-B', '-c', code, str(REPO / 'agent' / 'node_files.py'), str(root), case], env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    if os.environ.get('NODE_FILES_EVIDENCE'):
        (Path(os.environ['NODE_FILES_EVIDENCE']) / ('root-' + case + '.json')).write_text(json.dumps(receipt, indent=2))
    return receipt


def test_explicit_root_browses_only_owned_mount_root(tmp_path):
    assert root_probe(tmp_path, 'browse')['passed']


def test_root_keeps_links_special_paths_and_write_grants_closed(tmp_path):
    assert root_probe(tmp_path, 'negative')['uid'] == 65534


def test_root_reports_actual_uid_permission_denials(tmp_path):
    assert root_probe(tmp_path, 'permissions')['passed']


def test_initial_root_open_reports_actual_uid_permission_denial(tmp_path):
    assert root_probe(tmp_path, 'root-permission')['passed']


def test_explicit_slash_is_read_only_and_default_remains_empty(monkeypatch):
    monkeypatch.delenv('STELLA_FILE_ROOTS', raising=False)
    assert nf.Sandbox.from_env().roots() == []
    monkeypatch.setenv('STELLA_FILE_ROOTS', '{"system":{"path":"/"}}')
    sandbox = nf.Sandbox.from_env()
    assert sandbox.allowed == {'system': {'path': '/', 'write': False}}
    assert sandbox.roots() == [{'id': 'system', 'write': False}]
    with pytest.raises(nf.FileError, match='read_only_root'):
        sandbox.execute({'op': 'create', 'root': 'system', 'path': 'no-write'})


def test_installed_generation_retains_explicit_root_policy_without_granting_it(tmp_path, monkeypatch):
    from agent import node_files_delivery as delivery
    manifest, bodies = delivery.build_release(REPO / 'agent')
    store = delivery.ReleaseStore(tmp_path / 'owned-generation')
    store.install(manifest, lambda name, info: bodies[name])
    module, _ = delivery.installed_module(store)
    assert module.Sandbox.from_env().roots() == []
    monkeypatch.setenv('STELLA_FILE_ROOTS', '{"system":{"path":"/"}}')
    assert module.Sandbox.from_env().roots() == [{'id': 'system', 'write': False}]
    monkeypatch.setattr(module.sys, 'platform', 'win32')
    assert module.Sandbox.from_env().roots() == []


@pytest.mark.parametrize('path', ['', 'relative', '//', '/etc/', '/a//b', '/a/../b', '/a/./b', '/a\\b', '/a\x00b'])
def test_slash_exception_does_not_accept_other_invalid_roots(path):
    with pytest.raises(nf.FileError, match='invalid_local_policy'):
        nf.Sandbox({'system': {'path': path}})
