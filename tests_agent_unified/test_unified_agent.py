"""Single-script bootstrap and real owned child regression tests (no app/DB)."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
from agent import stella_agent as a
from agent import node_files_delivery as d


@pytest.mark.parametrize('config', [None, {}, {'enabled': False, 'roots': {}, 'revision': 'a'*64},
    {'enabled': True, 'roots': {}, 'revision': 'a'*64},
    {'enabled': 1, 'roots': {'system': {'path': '/', 'write': True}}, 'revision': 'a'*64},
    {'enabled': True, 'roots': {'system': {'path': '/', 'write': 'true'}}, 'revision': 'a'*64}])
def test_config_old_disabled_or_malformed_never_grants(config):
    assert hasattr(a, '_file_roots'), 'missing explicit authenticated file configuration gate'
    assert a._file_roots(config) == {}


def test_explicit_config_and_legacy_roots():
    assert hasattr(a, '_file_roots'), 'missing config gate'
    roots = {'system': {'path': '/', 'write': True}}
    assert a._file_roots({'enabled': True, 'roots': roots, 'revision': 'a'*64}) == roots
    assert a._file_roots(None, '{"explicit":{"path":"/root","write":false}}') == {'explicit': {'path': '/root', 'write': False}}


def wait_until(predicate, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.02)
    assert predicate(), 'bounded wait exhausted'


@pytest.fixture
def center():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    manifest, bodies = d.build_release(Path(a.__file__).parent)
    state = {'config': {'enabled': True, 'roots': {'system': {'path': '/', 'write': True}}, 'revision': 'a'*64},
             'claims': 0, 'gets': [], 'tokens': [], 'delay': 0, 'bad': False,
             'identity': {'center_id': 'c'*64, 'node_id': 1}}
    state['manifest'], state['bodies'] = manifest, bodies
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def send(self, value, code=200):
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(code); self.end_headers()
            try: self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError): pass
        def do_GET(self):
            state['gets'].append(self.path)
            state['tokens'].append(self.headers.get('Authorization'))
            if state['delay']: time.sleep(state['delay'])
            if self.path == '/test/claims': self.send({'claims': state['claims']})
            elif self.path == '/agent/identity': self.send(state['identity'])
            elif self.path == '/agent/files/config': self.send(state['config'])
            elif self.path == '/agent/files/release': self.send(manifest)
            else:
                if self.path.startswith('/agent/files/requests/'):
                    self.send({'state': 'running'}); return
                body = bodies.get(self.path.rsplit('/', 1)[-1])
                self.send(b'tampered' if state['bad'] else body, 200 if body else 404)
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            if self.path == '/agent/files/claim':
                state['claims'] += 1
                self.send(state.pop('job', {}))
            elif '/admit?' in self.path:
                self.send({'state': 'committing'})
            elif self.path.endswith('/result'):
                state.setdefault('results', []).append(json.loads(body)); self.send({})
            else:
                self.send({})
        def do_PUT(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            state.setdefault('bytes', bytearray()).extend(body)
            self.send({'offset': len(state['bytes'])})
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    state['url'] = 'http://127.0.0.1:' + str(server.server_port)
    yield state
    server.shutdown(); server.server_close(); thread.join(2)


def test_owned_child_crash_restart_shutdown_identity_token_config(center, tmp_path):
    assert hasattr(a, '_FileSupervisor'), 'missing managed root file subprocess'
    spec = {'origin': center['url'], 'token': 'synthetic-secret-one', 'binding': center['identity'],
            'legacy': None, 'store': str(tmp_path / 'runtime')}
    manager = a._FileSupervisor(lambda: dict(spec), allow_loopback=True, refresh=.15, backoff=.15)
    try:
        wait_until(lambda: (manager.tick() or True) and center['claims'] > 0)
        first = manager.worker.pid
        assert 'synthetic-secret' not in Path(f'/proc/{first}/cmdline').read_text()
        assert 'synthetic-secret' not in Path(f'/proc/{first}/environ').read_text()
        os.kill(first, signal.SIGKILL)
        wait_until(lambda: (manager.tick() or True) and manager.worker is not None and manager.worker.pid != first)
        second = manager.worker.pid
        spec['token'] = 'synthetic-secret-two'
        wait_until(lambda: (manager.tick() or True) and manager.worker is not None and manager.worker.pid != second)
        assert not Path(f'/proc/{second}').exists()
        third = manager.worker.pid
        center['config'] = {'enabled': False, 'roots': {}, 'revision': 'b'*64}
        wait_until(lambda: (manager.tick() or True) and manager.worker is None)
        assert not Path(f'/proc/{third}').exists()
        center['config'] = {'enabled': True, 'roots': {'system': {'path': '/', 'write': True}}, 'revision': 'd'*64}
        wait_until(lambda: (manager.tick() or True) and manager.worker is not None)
        fourth = manager.worker.pid
        center['identity'] = {'center_id': 'e'*64, 'node_id': 2}
        wait_until(lambda: (manager.tick() or True) and manager.worker is None)
        assert not Path(f'/proc/{fourth}').exists()
    finally:
        manager.close()
    assert manager.worker is None and manager.preparing is None
    assert {'Bearer synthetic-secret-one', 'Bearer synthetic-secret-two'} <= set(center['tokens'])


def test_slow_package_network_does_not_block_ticks_or_shutdown(center, tmp_path):
    assert hasattr(a, '_FileSupervisor'), 'missing bounded independent file control'
    center['delay'] = 3
    manager = a._FileSupervisor(lambda: {'origin': center['url'], 'token': 'synthetic', 'binding': center['identity'],
        'legacy': None, 'store': str(tmp_path / 'runtime')}, allow_loopback=True)
    start = time.monotonic()
    for _ in range(100): manager.tick()
    assert time.monotonic() - start < .5
    pid = manager.preparing.pid
    manager.close()
    assert time.monotonic() - start < 2 and not Path(f'/proc/{pid}').exists()


def test_agent_owns_file_controller_without_legacy_env(center, tmp_path, monkeypatch):
    monkeypatch.delenv('STELLA_FILE_ROOTS', raising=False)
    agent = a.Agent.__new__(a.Agent)
    agent.url, agent.token, agent._installation = center['url'], 'synthetic', None
    monkeypatch.setattr(agent, '_installation_binding', lambda: None)
    agent._file_tick()
    assert hasattr(agent, '_file_supervisor'), 'Agent never starts central explicit grant controller'
    agent._file_supervisor.close()


def test_stdlib_client_without_site_packages(center, tmp_path):
    code = ('import sys;sys.path.insert(0,sys.argv[1]);import stella_agent as a; '
            'import node_files as n;w=n.FileWorker(sys.argv[2],"synthetic",n.Sandbox({}),client=a._FileHTTPClient({"origin":sys.argv[2],"token":"synthetic","allow_loopback":True})); '
            'w.tick();w.client.close()')
    result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', code, str(Path(a.__file__).parent), center['url']],
        env={'PATH': '/usr/bin:/bin'}, cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert center['claims'] == 1


def test_stdlib_complete_bootstrap_atomic_reuse_and_tamper(tmp_path):
    assert hasattr(a, '_FilePackage'), 'single-file upgrade cannot bootstrap file runtime'
    manifest, bodies = d.build_release(Path(a.__file__).parent)
    package = a._FilePackage(tmp_path / 'releases')
    calls = []
    def fetch(path, limit):
        calls.append(path)
        return bodies[path.rsplit('/', 1)[-1]]
    active = package.install(manifest, fetch)
    assert active.name == d.release_id(manifest)
    assert len(calls) == len(d.FILES)
    assert package.install(manifest, fetch) == active and len(calls) == len(d.FILES)
    pointer = (package.root / 'current.json').read_bytes()
    bad = json.loads(json.dumps(manifest))
    bad['files']['node_files.py']['sha256'] = '0' * 64
    with pytest.raises(ValueError):
        package.install(bad, fetch)
    assert (package.root / 'current.json').read_bytes() == pointer
    assert not list(package.root.glob('.stage-*'))
    (active / 'node_files.py').write_bytes(b'broken')
    with pytest.raises(ValueError):
        package.install(manifest, fetch)
    assert (package.root / 'current.json').read_bytes() == pointer


@pytest.mark.parametrize('mode', ['group-writable', 'foreign-owner'])
def test_package_refuses_replaceable_ancestor(tmp_path, mode):
    ancestor = tmp_path / 'ancestor'
    ancestor.mkdir()
    if mode == 'group-writable':
        ancestor.chmod(0o770)
    else:
        os.chown(ancestor, 65534, 65534)
    with pytest.raises(ValueError, match='unsafe file package'):
        a._FilePackage(ancestor / 'runtime')
    assert not (ancestor / 'runtime').exists()


@pytest.mark.parametrize('phase', ['prepare', 'worker', 'load-probe'])
def test_real_parent_sigkill_leaves_no_live_owned_children(center, tmp_path, phase):
    # Become a subreaper only in this disposable driver so orphaned descendants
    # are actually waited, not mistaken for cleaned-up live processes/zombies.
    spec = {'origin': center['url'], 'token': 'parent-death-synthetic',
            'binding': center['identity'], 'legacy': None, 'store': str(tmp_path / 'runtime')}
    if phase == 'prepare':
        center['delay'] = 3
    if phase == 'load-probe':
        body = center['bodies']['stella_agent.py'].replace(b'AGENT_VERSION = "0.6.20"', b'AGENT_VERSION = "0.6.21"', 1)
        body += ('\nfrom pathlib import Path\nPath(' + repr(str(tmp_path / 'probe-ready')) + ').write_text("ready")\nimport time\ntime.sleep(60)\n').encode()
        center['bodies']['stella_agent.py'] = body
        center['manifest']['version'] = '0.6.21'
        center['manifest']['files']['stella_agent.py'].update(version='0.6.21', size=len(body), sha256=hashlib.sha256(body).hexdigest())
    code = '''import ctypes,json,os,signal,subprocess,sys,time
ctypes.CDLL(None).prctl(36,1,0,0,0)
parent_code = """import json,sys,time
sys.path.insert(0,sys.argv[1]);import stella_agent as a
spec=json.loads(sys.argv[2]);m=a._FileSupervisor(lambda:spec,allow_loopback=True,refresh=.1)
while True:
 m.tick()
 child=m.worker if sys.argv[3]=='worker' else m.preparing
 ready=(sys.argv[3]=='prepare' or (sys.argv[3]=='load-probe' and a.os.path.exists(a.os.path.join(a.os.path.dirname(spec['store']),'probe-ready'))) or (sys.argv[3]=='worker' and json.loads(a._file_fetcher(dict(spec,allow_loopback=True))('/test/claims',1024))['claims']>0))
 if child is not None and ready:
  print(child.pid,flush=True);break
 time.sleep(.02)
while True: time.sleep(1)
"""
p=subprocess.Popen([sys.executable,'-I','-B','-c',parent_code,*sys.argv[1:]],stdout=subprocess.PIPE,text=True)
children=[]
try:
 child=int(p.stdout.readline());children.append(child)
 p.kill();p.wait(timeout=3)
 end=time.monotonic()+5
 while time.monotonic()<end:
  try:
   pid,status=os.waitpid(-1,os.WNOHANG)
   if pid:
    children.remove(pid) if pid in children else None
    continue
  except ChildProcessError:break
  time.sleep(.02)
 assert not children,('orphan not reaped',children)
 assert not open('/proc/self/task/'+str(os.getpid())+'/children').read().strip(),'live adopted load probe survived'
 assert not os.path.exists('/proc/'+str(child)),('orphan pid still present',child)
 print(json.dumps({'parent_sigkill':True,'phase':sys.argv[3],'child_reaped':True}))
finally:
 if p.poll() is None:p.kill();p.wait()
 for pid in ([child] if 'child' in locals() else []):
  try:os.killpg(pid,signal.SIGKILL)
  except ProcessLookupError:pass
 while True:
  try:os.waitpid(-1,0)
  except ChildProcessError:break
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code,
        str(Path(a.__file__).parent), json.dumps(spec), phase],
        env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['child_reaped']


@pytest.mark.unified_root_fixture
def test_root_uid_actual_fabricated_slash_read_write_and_denied_controls(tmp_path):
    # Real chroot, no bind/unshare/SYS_ADMIN. Only fabricated root contains data.
    root = tmp_path / 'fabricated-root'
    (root / 'root').mkdir(parents=True, mode=0o700)
    (root / 'root' / 'private').write_text('synthetic-private-root-file')
    (root / 'root' / 'private').chmod(0o600)
    (root / 'escape').symlink_to('/proc')
    code = '''import sys,os,hashlib,uuid,ctypes,json
sys.path.insert(0,sys.argv[1]);import node_files as nf
os.chroot(sys.argv[2]);os.chdir('/')
assert os.geteuid()==0
s=nf.Sandbox({'system':{'path':'/','write':True}})
assert s.execute({'op':'preview','root':'system','path':'root/private'})['text']=='synthetic-private-root-file'
data=b'root-child-write'
req={'op':'upload','root':'system','path':'root/written','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
s.write_stream(req,[data],lambda:True,lambda:True)
assert open('/root/written','rb').read()==data
assert os.stat('/root/written').st_uid==0
for r in [dict(req,root='foreign'),dict(req,path='../root/private'),dict(req,path='escape/stat')]:
 try:s.execute(dict(r,op='preview'))
 except nf.FileError:pass
 else:raise AssertionError('root boundary bypass')
ro=nf.Sandbox({'system':{'path':'/','write':False}})
try:ro.execute({'op':'create','root':'system','path':'root/denied'})
except nf.FileError as e:assert str(e)=='read_only_root'
else:raise AssertionError('read-only grant bypass')
assert not os.path.exists('/root/denied')
print(json.dumps({'uid':os.geteuid(),'chroot':True,'read_write':True,'negative_controls':4}))
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code,
        str(Path(a.__file__).parent), str(root)], env={'PATH': '/usr/bin:/bin'},
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {'uid': 0, 'chroot': True, 'read_write': True, 'negative_controls': 4}
    assert (root / 'root' / 'written').read_bytes() == b'root-child-write'


@pytest.mark.unified_root_fixture
def test_automatic_root_child_reads_and_writes_only_owned_fixture(center, tmp_path):
    private = tmp_path / 'root-private'
    private.mkdir(mode=0o700)
    source = private / 'read.txt'
    source.write_bytes(b'synthetic-root-only-read')
    source.chmod(0o600)
    destination = private / 'created.txt'
    spec = {'origin': center['url'], 'token': 'synthetic-root-worker',
            'binding': center['identity'], 'legacy': None, 'store': str(tmp_path / 'runtime')}
    manager = a._FileSupervisor(lambda: dict(spec), allow_loopback=True, refresh=.15)
    def job(op, path, root='system'):
        center['job'] = {'id': 'owned-' + op, 'lease': 'a' * 48,
                         'request': {'protocol': 1, 'op': op, 'root': root, 'path': str(path).lstrip('/')}}
    try:
        job('preview', source)
        wait_until(lambda: (manager.tick() or True) and len(center.get('results', [])) == 1)
        assert manager.worker is not None
        status = Path(f'/proc/{manager.worker.pid}/status').read_text()
        assert set(next(line for line in status.splitlines() if line.startswith('Uid:')).split()[1:]) == {'0'}
        assert bytes(center['bytes']) == source.read_bytes()
        assert 'error' not in center['results'][0]
        job('create', destination)
        wait_until(lambda: (manager.tick() or True) and len(center['results']) == 2)
        assert destination.read_bytes() == b'' and destination.stat().st_uid == 0
        assert 'error' not in center['results'][1]
        job('create', private / 'denied', root='ungranted')
        wait_until(lambda: (manager.tick() or True) and len(center['results']) == 3)
        assert center['results'][2]['error'] == 'read_only_root'
        assert not (private / 'denied').exists()
    finally:
        child = manager.worker
        manager.close()
        if child is not None:
            assert not Path(f'/proc/{child.pid}').exists()
    assert '/agent/files/config' in center['gets'] and '/agent/files/release' in center['gets']
