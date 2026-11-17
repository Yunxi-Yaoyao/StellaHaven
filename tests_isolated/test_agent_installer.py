"""Real Linux shell entry point; only scratch paths + fake service/account tools.
No real systemd/sudoers/users/packages and no non-loopback networking.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'fixture-not-a-real-token'
CENTER_A, CENTER_B = 'a' * 64, 'b' * 64

def instance_id(center):
    return hashlib.sha256(('stella-instance-v1:' + center).encode()).hexdigest()[:24]

FAKE = '''#!PYTHON
import json, os, pathlib, sys
root = pathlib.Path(os.environ['FIXTURE_ROOT'])
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with (root/'calls').open('a') as f: f.write(json.dumps([name]+args)+'\\n')
users = root/'users.json'
state = json.loads(users.read_text()) if users.exists() else {}
if name == 'id':
    if args == ['-u']: print('0')
    elif args[-1] in state: print(state[args[-1]])
    else: sys.exit(1)
elif name == 'useradd':
    state[args[-1]] = 65001 + len(state); users.write_text(json.dumps(state))
elif name == 'userdel':
    state.pop(args[-1],None); users.write_text(json.dumps(state))
elif name == 'systemctl':
    if args[0] == 'show': print('')
    if args[0] == 'restart' and os.environ.get('FAIL_RESTART') == '1': sys.exit(1)
elif name == 'visudo': pass
else: raise SystemExit('unexpected side effect command')
'''

class LinuxInstances(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='stella-instance-v11-', dir=os.environ.get('TMPDIR'))
        self.root = Path(self.tmp.name)
        self.bin = self.root/'bin'; self.bin.mkdir()
        for name in ('systemctl','useradd','userdel','id','visudo','systemd-run'):
            path = self.bin/name
            path.write_text(FAKE.replace('#!PYTHON','#!'+sys.executable)); path.chmod(0o755)
        (self.bin/'python3').symlink_to(sys.executable)
        self.env = {'PATH':str(self.bin), 'FIXTURE_ROOT':str(self.root), 'TMPDIR':str(self.root)}
        self.center, self.node, self.mode = CENTER_A, 7, ''
        self.body = b'#!/usr/bin/env python3\nAGENT_VERSION = "0.6.17"\nprint("fixture")\n'
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                if self.path == '/agent/identity':
                    if fixture.mode == '401' or self.headers.get('Authorization') != 'Bearer '+TOKEN:
                        self.send_response(401); self.end_headers(); return
                    data = dict(center_id=fixture.center,node_id=fixture.node,source_version='0.6.17',
                                source_sha256=hashlib.sha256(fixture.body).hexdigest(),source_size=len(fixture.body))
                    if fixture.mode == 'noidentity': data.pop('center_id')
                    body = json.dumps(data).encode()
                elif self.path == '/agent/script':
                    body = b'<html>bad</html>' if fixture.mode == 'corrupt' else fixture.body
                else: self.send_response(404); self.end_headers(); return
                self.send_response(200); self.end_headers(); self.wfile.write(body)
        self.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.url = 'http://127.0.0.1:'+str(self.server.server_port)
        # Absolute destination constants are relocated before the real script runs.
        source = (ROOT/'agent/install.sh').read_text()
        for base in ('/opt/stella-agents','/etc/stella-agents','/etc/systemd/system','/etc/sudoers.d','/usr/local/libexec'):
            source = source.replace(base,str(self.root)+base)
        self.script = self.root/'install.sh'; self.script.write_text(source)
        self.legacy = self.root/'opt/stella-agent/agent.env'
        self.legacy.parent.mkdir(parents=True); self.legacy.write_bytes(b'legacy opaque sentinel')
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()
    def install(self, extra_env=None, origin=None, extra_args=()):
        self.assertIn('STELLA_INSTANCE_INSTALLER', self.script.read_text(), 'Instance-safe entry point is missing; do not execute legacy writer')
        result = subprocess.run(['/bin/bash',str(self.script),'--url',origin or self.url,'--token',TOKEN,'--no-deps',*extra_args],
            env={**self.env,**(extra_env or {})},text=True,capture_output=True,timeout=15)
        self.assertNotIn(TOKEN,result.stdout+result.stderr)
        self.assertEqual(self.legacy.read_bytes(),b'legacy opaque sentinel')
        return result
    def calls(self):
        return [json.loads(line) for line in (self.root/'calls').read_text().splitlines()] if (self.root/'calls').exists() else []
    def code(self, center=CENTER_A): return self.root/'opt/stella-agents'/instance_id(center)
    def snapshot(self):
        return {str(p.relative_to(self.root)):p.read_bytes() for folder in ('opt','etc','usr')
                for p in (self.root/folder).rglob('*') if p.is_file()}
    def test_same_center_two_origins_same_node_reuses_instance(self):
        first = self.install(); self.assertEqual(first.returncode,0,first.stdout+first.stderr)
        second = self.install(origin=self.url.replace('127.0.0.1','localhost'))
        self.assertEqual(second.returncode,0,second.stdout+second.stderr)
        envfile=self.root/'etc/stella-agents'/instance_id(CENTER_A)/'agent.env'
        self.assertIn('STELLA_URL='+json.dumps(self.url),envfile.read_text(), 'Origin alias repair must preserve the installed report/cache identity')
        self.assertTrue((self.code()/'stella_agent.py').exists())
        self.assertEqual(len(list((self.root/'opt/stella-agents').iterdir())),1)
        self.assertTrue(all('stella-agent' not in c[1:] for c in self.calls() if c[0]=='systemctl'))

    def test_different_centers_coexist_with_distinct_users_and_no_legacy_writes(self):
        self.assertEqual(self.install().returncode,0)
        first = self.snapshot()
        self.center = CENTER_B
        result = self.install(); self.assertEqual(result.returncode,0,result.stderr)
        for path,data in first.items(): self.assertEqual((self.root/path).read_bytes(),data)
        users = json.loads((self.root/'users.json').read_text())
        self.assertEqual(len(users),2)
        self.assertTrue(self.code(CENTER_B).exists())
    def test_same_center_different_node_refuses_without_changes(self):
        self.assertEqual(self.install().returncode,0)
        before = self.snapshot(); self.node = 8
        self.assertNotEqual(self.install().returncode,0); self.assertEqual(self.snapshot(),before)
    def test_auth_identity_and_corrupt_source_fail_before_resident_writes(self):
        for mode in ('401','noidentity','corrupt'):
            with self.subTest(mode=mode):
                self.mode = mode; before = self.snapshot()
                self.assertNotEqual(self.install().returncode,0)
                self.assertEqual(self.snapshot(),before)
                self.assertFalse(any(c[0]=='useradd' for c in self.calls()))
    def test_upgrade_failure_restores_bytes_modes_and_owner(self):
        self.assertEqual(self.install().returncode,0)
        before = self.snapshot()
        original = (self.code()/'stella_agent.py').stat()
        self.body += b'# upgrade\n'
        self.assertNotEqual(self.install({'FAIL_RESTART':'1'}).returncode,0)
        self.assertEqual(self.snapshot(),before)
        restored = (self.code()/'stella_agent.py').stat()
        self.assertEqual((restored.st_mode,restored.st_uid),(original.st_mode,original.st_uid))
    def test_uninstall_exact_instance_leaves_other_center_and_legacy_bytes(self):
        self.assertEqual(self.install().returncode,0)
        self.center = CENTER_B; self.assertEqual(self.install().returncode,0)
        before = self.snapshot()
        helper = self.root/'usr/local/libexec'/('stella-agent-'+instance_id(CENTER_A))
        result = subprocess.run([sys.executable,'-I',str(helper),'--remove'],env=self.env,text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(self.code().exists())
        for path,data in before.items():
            if instance_id(CENTER_A) not in path: self.assertEqual((self.root/path).read_bytes(),data)
        self.assertTrue(self.code(CENTER_B).exists())
        self.assertEqual(self.legacy.read_bytes(),b'legacy opaque sentinel')
        stopped = [c for c in self.calls() if c[:2]==['systemctl','stop']]
        self.assertEqual(stopped,[['systemctl','stop','stella-agent-'+instance_id(CENTER_A)]])
    def test_foreign_target_and_symlink_fail_closed(self):
        self.code().mkdir(parents=True); marker = self.code()/'foreign'; marker.write_bytes(b'foreign')
        before = self.snapshot(); self.assertNotEqual(self.install().returncode,0)
        self.assertEqual(self.snapshot(),before)
    def test_duplicate_concurrent_lock_refuses_before_changes(self):
        import fcntl
        self.assertEqual(self.install().returncode,0)
        before = self.snapshot()
        lock = self.root/'etc/stella-agents'/('.'+instance_id(CENTER_A)+'.lock')
        with lock.open('r+') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertNotEqual(self.install().returncode,0)
        self.assertEqual(self.snapshot(),before)
    def test_same_name_foreign_unit_is_not_adopted_even_with_valid_manifest(self):
        self.assertEqual(self.install().returncode,0)
        unit = self.root/'etc/systemd/system'/('stella-agent-'+instance_id(CENTER_A)+'.service')
        unit.write_text('[Service]\nUser=foreign\nExecStart=/some/other/program\n')
        before = self.snapshot()
        self.assertNotEqual(self.install().returncode,0)
        self.assertEqual(self.snapshot(),before)

    def test_explicit_slot_allows_second_node_without_rebinding_default(self):
        self.assertEqual(self.install().returncode,0)
        before = self.snapshot(); self.node = 8
        result = self.install(extra_args=('--instance','second'))
        self.assertEqual(result.returncode,0,result.stderr)
        for path,data in before.items(): self.assertEqual((self.root/path).read_bytes(),data)
        self.assertEqual(len(list((self.root/'opt/stella-agents').iterdir())),2)

if __name__ == '__main__': unittest.main()
