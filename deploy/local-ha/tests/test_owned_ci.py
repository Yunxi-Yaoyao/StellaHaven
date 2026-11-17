"""Owned CI admission negatives; stdlib-only, no existing database is opened."""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('owned_pg_contract', ROOT/'deploy/ci/owned_pg.py')
pg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pg)
INV = importlib.util.spec_from_file_location('owned_inventory_contract', ROOT/'deploy/ci/owned_inventory.py')
inv = importlib.util.module_from_spec(INV)
INV.loader.exec_module(inv)


class Stream:
    def __init__(self, data):
        self.data, self.output = data, b''

    def recv(self, count):
        value, self.data = self.data[:min(count, 3)], self.data[min(count, 3):]
        return value

    def sendall(self, data):
        self.output += data


def packet(user, database, extra=b''):
    data = struct.pack('!I', 196608) + b'user\0' + user.encode() + b'\0database\0' + database.encode() + b'\0' + extra + b'\0'
    return struct.pack('!I', len(data)+4) + data


class OwnedCIAdmission(unittest.TestCase):
    def env(self):
        return {'CI':'true','GITLAB_CI':'true','CI_JOB_ID':'230001','POSTGRES_HOST':'postgres',
                'POSTGRES_PORT':'5432','POSTGRES_DB':'stella','POSTGRES_USER':'stalla','POSTGRES_PASSWORD':'synthetic-only'}

    def address(self, value='192.168.200.2'):
        return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(value,5432))]

    def test_only_explicit_exact_ci_service_before_driver_import(self):
        with patch.dict(os.environ,self.env(),clear=True), patch.object(pg.socket,'getaddrinfo',return_value=self.address()):
            self.assertEqual(pg.ci_service(),'192.168.200.2')
        for key, value in {'CI':'1','GITLAB_CI':'false','CI_JOB_ID':'0','POSTGRES_HOST':'127.0.0.1',
                           'POSTGRES_PORT':'25432','POSTGRES_DB':'stella_test','POSTGRES_USER':'postgres',
                           'POSTGRES_PASSWORD':'','DATABASE_URL':'postgresql://unapproved'}.items():
            with self.subTest(key=key), patch.dict(os.environ,{**self.env(),key:value},clear=True), self.assertRaises(ValueError):
                pg.ci_service()

    def test_sidecar_dns_is_single_private_non_loopback(self):
        for values in ([],self.address('127.0.0.1'),self.address('8.8.8.8'),self.address()+self.address('192.168.200.3')):
            with self.subTest(values=values), patch.dict(os.environ,self.env(),clear=True), patch.object(pg.socket,'getaddrinfo',return_value=values), self.assertRaises(ValueError):
                pg.ci_service()

    def test_marker_exact_job_address_system_nonce_and_private_mode(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            path = Path(tmp)/'owned-ci-pg.json'
            good = {'format':1,'job':'230001','nonce':'a'*32,'system':'123456','address':'192.168.200.2'}
            with patch.dict(os.environ,{**self.env(),'TMPDIR':tmp},clear=True), patch.object(pg.socket,'getaddrinfo',return_value=self.address()):
                path.write_text(json.dumps(good));path.chmod(0o600)
                self.assertEqual(pg.admitted_marker(),good)
                for key,value in {'format':2,'job':'230002','nonce':'short','system':'not-number','address':'192.168.200.3','extra':True}.items():
                    with self.subTest(key=key):
                        path.write_text(json.dumps({**good,key:value}))
                        with self.assertRaises(ValueError):pg.admitted_marker()
                path.write_text(json.dumps(good));path.chmod(0o644)
                with self.assertRaises(ValueError):pg.admitted_marker()
                path.unlink();other=Path(tmp)/'other';other.write_text(json.dumps(good));path.symlink_to(other)
                with self.assertRaises(ValueError):pg.admitted_marker()
                Path(tmp).chmod(0o755)
                with self.assertRaises(ValueError):pg.marker_path()

    def test_startup_exact_role_database_and_fragmented_reads(self):
        name='nodefiles_'+'b'*32
        data=packet(name,name)
        self.assertEqual(pg.startup(Stream(data),name),data)
        for user,database,extra in [('stalla',name,b''),(name,'stella_test',b''),(name,name,b'user\0duplicate\0')]:
            with self.subTest(user=user,database=database), self.assertRaises(ValueError):
                pg.startup(Stream(packet(user,database,extra)),name)

    def test_tls_and_gss_cannot_tunnel_past_admission(self):
        name='navqa_'+'c'*32
        negotiation=b''.join(struct.pack('!II',8,n) for n in (80877103,80877104))
        stream=Stream(negotiation+packet(name,name))
        self.assertEqual(pg.startup(stream,name),packet(name,name))
        self.assertEqual(stream.output,b'NN')
        for data in (struct.pack('!II',8,80877102),struct.pack('!I',16385),struct.pack('!II',8,196609),b''):
            with self.subTest(data=data),self.assertRaises(ValueError):pg.startup(Stream(data),name)

    def test_fixture_token_requires_exact_parent_owned_listener_not_just_nonce(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            nonce=secrets.token_hex(16);name='navqa_'+nonce
            relay=pg.Relay('192.168.200.2',name)
            path=Path(tmp)/('owner-'+nonce+'.json')
            port=str(relay.server_address[1])
            data={'format':1,'nonce':nonce,'database':name,'port':port,'pid':os.getpid()}
            path.write_text(json.dumps(data));path.chmod(0o600)
            env={**self.env(),'TMPDIR':tmp,'STELLA_CI_OWNED_RECEIPT':str(path),'STELLA_CI_OWNED_NONCE':nonce,
                 'POSTGRES_HOST':'127.0.0.1','POSTGRES_DB':name,'POSTGRES_USER':name,'POSTGRES_PORT':port}
            code='import sys;sys.path.insert(0,sys.argv[1]);from owned_pg import owned_target;print(owned_target())'
            def run(values):
                return subprocess.run([sys.executable,'-S','-c',code,str(ROOT/'deploy/ci')],env=values,capture_output=True,text=True,timeout=5)
            try:
                result=run(env);self.assertEqual(result.returncode,0,result.stderr)
                for key,value in {'CI':'false','GITLAB_CI':'false','CI_JOB_ID':'','STELLA_CI_OWNED_NONCE':'0'*32,
                                  'POSTGRES_DB':'stella_test','POSTGRES_USER':'stalla','POSTGRES_HOST':'postgres','POSTGRES_PORT':'5432'}.items():
                    with self.subTest(key=key):self.assertNotEqual(run({**env,key:value}).returncode,0)
                path.write_text(json.dumps({**data,'pid':os.getpid()+1}))
                self.assertNotEqual(run(env).returncode,0)
                path.write_text(json.dumps(data));relay.close()
                self.assertNotEqual(run(env).returncode,0,'a dead/non-parent listener must not validate')
            finally:
                if relay.thread.is_alive():relay.close()

    def test_new_files_in_both_owned_directories_are_discovered_once(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root=Path(tmp)
            for directory in inv.FILES_DIRECTORIES:
                (root/directory).mkdir()
                for name in ('test_z.py','test_new_negative.py'):(root/directory/name).touch()
            expected=[[d+'/'+f] for d in ('tests_node_files','tests_node_files_delivery','tests_agent_unified','tests_agent_refresh_timeout') for f in ('test_new_negative.py','test_z.py')]
            self.assertEqual(inv.files_commands(root),expected)
            self.assertEqual(len({tuple(c) for c in inv.files_commands(root)}),8)
            self.assertTrue(all(inv.owned_command(c) for c in expected))
            self.assertFalse(inv.owned_command(['tests_isolated/test_unrelated_pg.py']))

    def test_unified_files_are_mandatory_in_existing_seven_shards(self):
        import runpy
        runner = runpy.run_path(str(ROOT/'deploy/ci/run-backend-shard.py'))
        commands = [c for i in range(1, 8) for c in runner['plan'](ROOT, i, 7)]
        expected = [[str(p.relative_to(ROOT))] for p in sorted((ROOT/'tests_agent_unified').glob('test_*.py'))]
        self.assertEqual(len(expected), 4)
        for command in expected:
            self.assertEqual(commands.count(command), 1)
            self.assertTrue(inv.owned_command(command))
        self.assertEqual(commands.count(['tests_node_files/test_auto_config.py']), 1)

    def test_no_files_mount_case_is_silently_manual_or_skipped(self):
        self.assertEqual(inv.MANUAL_NODEIDS,{'tests_isolated/test_native_nav_completion_pg.py::test_actual_readonly_source_rehearsal_roundtrip':'manual private-input rehearsal; NAV_LEGACY_TRANSFER must be supplied by its owner'})
        self.assertEqual(len(inv.files_commands(ROOT)),25)
        self.assertTrue(all(inv.owned_command(c) for c in inv.files_commands(ROOT)))


if __name__=='__main__':
    unittest.main()
