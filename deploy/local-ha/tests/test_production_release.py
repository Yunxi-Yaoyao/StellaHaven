"""Production release tests are isolated: never SSH or Docker a real host."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class ProductionTests(unittest.TestCase):
    def test_real_production_entrypoint_exists(self):
        self.assertTrue((ROOT / 'production_release.py').exists(), 'real production transport required')

    def test_standby_first_and_drift_blocks_active(self):
        p = load('production_release')
        class Transport:
            def __init__(self, drift=False):
                self.events = []; self.drift = drift
            def call(self, node, op, **kw):
                self.events.append((node, op))
                if op == 'probe':
                    primary = node == 'nyarch'
                    if self.drift and ('nas', 'release') in self.events:
                        primary = not primary
                    roles = {'nyarch':primary if node=='nyarch' else not primary,
                             'nas':primary if node=='nas' else not primary}
                    return dict(node=node, primary=primary, roles=roles, manifest='a'*64, signing='b'*64,
                                revision='b7c8d9e0f1a2', status='healthy')
                return {'status':'deployed', 'container_id':node, 'digest':'sha256:'+'c'*64}
        t = Transport()
        result = p.orchestrate(t, {'manifest_sha256':'a'*64, 'signing_sha256':'b'*64,
                                  'schema_revision':'b7c8d9e0f1a2'})
        self.assertEqual(result['status'], 'deployed')
        self.assertEqual([n for n, op in t.events if op == 'release'], ['nas','nyarch'])
        t = Transport(True)
        result = p.orchestrate(t, {'manifest_sha256':'a'*64, 'signing_sha256':'b'*64,
                                  'schema_revision':'b7c8d9e0f1a2'})
        self.assertEqual(result['status'], 'blocked')
        self.assertNotIn(('nyarch','release'), t.events)

    def test_conflicting_peer_role_observations_block_release(self):
        p = load('production_release')
        class Transport:
            def call(self, node, op, **kw):
                if op != 'probe': raise AssertionError('must not release')
                return dict(status='healthy', node=node, primary=node=='nyarch',
                            roles={'nyarch':False, 'nas':True}, manifest='a'*64,
                            signing='b'*64, revision='rev')
        result = p.orchestrate(Transport(), {'manifest_sha256':'a'*64,
                              'signing_sha256':'b'*64, 'schema_revision':'rev'})
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('observations', result['reason'])

    def test_inventory_rejects_unsafe_mount_and_node(self):
        import copy
        p = load('production_release')
        mounts = [{'Source':p.BASE + str(i), 'Destination':d, 'RW':d=='/tmp'} for i,d in enumerate(
            ['/app/data','/tmp','/data/secret_key','/run/secrets/app-password','/run/secrets/oidc-private.json','/shadow-start.py'])]
        inv = dict(scope='stella-production-app-v1',forward_compatible=True,manifest_sha256='a'*64,
                   signing_sha256='b'*64,schema_revision='b7c8d9e0f1a2',nodes={})
        for n, ip in p.NODES.items():
            inv['nodes'][n] = dict(host=ip,alias='stella-prod-'+n,mounts=mounts,command=['/shadow-start.py'],memory=1024,nano_cpus=1000,startup_sha256='c'*64)
        p.validate_inventory(inv)
        for field, value in [('host','127.0.0.1'),('alias','-oProxyCommand=bad'),('memory',0)]:
            bad=copy.deepcopy(inv); bad['nodes']['nas'][field]=value
            with self.assertRaises(ValueError): p.validate_inventory(bad)
        for source in ['/etc','/var/lib/stella-ha-runtime/nas/pgdata',p.BASE+'../escape']:
            bad=copy.deepcopy(inv); bad['nodes']['nas']['mounts'][0]['Source']=source
            with self.assertRaises(ValueError): p.validate_inventory(bad)
        bad=copy.deepcopy(inv); bad['nodes']['nas']['mounts'][0]['RW']=True
        with self.assertRaises(ValueError): p.validate_inventory(bad)

    def test_transport_uses_strict_ssh_and_stdin_only(self):
        import tempfile, json
        from unittest.mock import patch
        from types import SimpleNamespace
        p=load('production_release')
        with tempfile.TemporaryDirectory() as d:
            key=Path(d)/'key'; key.write_text('test-only')
            t=p.SSHTransport({'nodes':{'nas':{'alias':'stella-prod-nas','host':'10.66.0.3'}}},str(key),str(key),'digest')
            with patch.object(p.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='{"status":"unchanged"}')) as run, patch.dict(p.os.environ,{'CI_REGISTRY_PASSWORD':'secret-test-marker','CI_REGISTRY_USER':'user'}):
                t.call('nas','release')
                args,kw=run.call_args
                self.assertIn('StrictHostKeyChecking=yes',args[0])
                self.assertIn('yaoyao@10.66.0.3',args[0])
                self.assertNotIn('secret-test-marker',' '.join(args[0]))
                self.assertEqual(json.loads(kw['input'])['request']['registry_password'],'secret-test-marker')

    def test_busy_candidate_port_is_rejected(self):
        import socket
        p=load('node_production')
        with socket.socket() as s:
            s.bind(('127.0.0.1',0)); s.listen()
            with self.assertRaises(OSError): p.port_free(s.getsockname()[1])

    def test_closed_listener_timewait_does_not_block_restart(self):
        import socket
        p=load('node_production')
        server=socket.socket();server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        server.bind(('127.0.0.1',0));port=server.getsockname()[1];server.listen()
        client=socket.create_connection(('127.0.0.1',port));accepted,_=server.accept()
        accepted.shutdown(socket.SHUT_WR)
        self.assertEqual(client.recv(1),b'')
        accepted.close();client.close();server.close()
        p.port_free(port)

    def test_content_identity_handles_index_vs_config(self):
        p=load('node_production')
        a={'Id':'sha256:'+'a'*64,'RootFS':{'Layers':['layer']},'Config':{'Cmd':['app']},'Architecture':'amd64','Os':'linux'}
        b=dict(a,Id='sha256:'+'b'*64)
        self.assertTrue(p.same_image_content(a,b))
        self.assertFalse(p.same_image_content(a,dict(b,RootFS={'Layers':['other']})))

    def test_node_swap_health_failure_restores_old_id(self):
        import json
        from unittest.mock import patch
        p=load('node_production')
        image=p.REGISTRY+'@sha256:'+'c'*64
        class FakeNode(p.Node):
            def __init__(self, fail=False):
                self.name='stella-app-shadow-nas'; self.node='nas'; self.cfg={}
                self.r={'image':image,'registry_user':'test','registry_password':'test'}
                self.expected={'nyarch':True,'nas':False}; self.fail=fail
                self.containers={self.name:{'Id':'old','Image':'old-image','Name':'/'+self.name,'Config':{'Cmd':[]},'State':{'Running':True}}}
                self.events=[]
            def inspect(self,name):
                return next(c for k,c in self.containers.items() if k==name or c['Id']==name)
            def validate(self,c,*args,**kw): return c
            def pg_guard(self): return 'pg-unchanged'
            def probe(self,*args,**kw): return {'roles':self.expected}
            def guard(self,*args): return None
            def image_matches(self,actual,info): return actual=='new-image'
            def health(self,name,port,expected=True):
                if self.fail and name==self.name and self.inspect(name)['Id']=='replacement':
                    raise ValueError('unhealthy replacement')
                return {'http':{'live':200,'ready_primary':503}}
            def create(self,old,name,image_id,port):
                id='candidate' if port==25132 else 'replacement'
                self.containers[name]={'Id':id,'Image':'new-image','Name':'/'+name,'Config':{'Cmd':[]},'State':{'Running':False}}
                self.events.append(('create',id)); return id
            def action(self,*args,**kw): return self.command(['docker',*args])
            def command(self,args,*more,**kw):
                self.events.append(tuple(args[1:]))
                if args[1:3]==['image','inspect']:
                    return json.dumps([{'Id':'sha256:'+'c'*64,'RepoDigests':[image]}])
                if args[1] in ('login','pull'): return ''
                c=self.inspect(args[-2] if args[1]=='rename' else args[-1])
                if args[1]=='rename':
                    key=c['Name'][1:]; del self.containers[key]
                    c['Name']='/'+args[-1]; self.containers[args[-1]]=c
                elif args[1]=='rm': del self.containers[c['Name'][1:]]
                else: c['State']['Running']=args[1]=='start'
                return ''
        for fail in (False,True):
            n=FakeNode(fail)
            with patch.object(p,'run',side_effect=n.command): result=n.release()
            self.assertEqual(result['status'],'rolledback' if fail else 'deployed')
            self.assertEqual(n.inspect(n.name)['Id'],'old' if fail else 'replacement')
            self.assertTrue(n.inspect(n.name)['State']['Running'])
            self.assertFalse(any('pg-unchanged' in str(x) for x in n.events))
            if not fail: self.assertIn(result['backup'],n.containers)

    def test_replacement_preserves_restart_policy_and_secret_stdin(self):
        from unittest.mock import patch
        p = load('node_production')
        n = object.__new__(p.Node)
        n.cfg = {'memory':1024, 'nano_cpus':1000000000, 'mounts':[]}
        old = {'HostConfig':{'RestartPolicy':{'Name':'unless-stopped'}},
               'Config':{'Env':['PGOPTIONS=-c statement_timeout=30000'], 'Labels':{}}}
        with patch.object(p, 'port_free'), patch.object(p, 'run', return_value='id') as run:
            n.create(old, 'replacement', 'sha256:'+'a'*64, 25131)
        argv = run.call_args.args[0]
        self.assertIn('--restart=unless-stopped', argv)
        self.assertNotIn('PGOPTIONS=-c statement_timeout=30000', argv)
        self.assertIn('PGOPTIONS=-c statement_timeout=30000', run.call_args.args[1])

    def test_environment_rejects_shadow_readonly_and_signing_override(self):
        p = load('node_production')
        good = {'PGOPTIONS':'-c statement_timeout=30000'}
        p.validate_environment(good)
        for env in ({}, {'PGOPTIONS':'-c default_transaction_read_only=on'},
                    dict(good, STELLA_SECRET_KEY='unapproved'), dict(good, PGHOST='remote')):
            with self.assertRaises(ValueError): p.validate_environment(env)

    def test_local_image_id_is_checked_against_same_daemon_inspect(self):
        import json
        from unittest.mock import patch
        p = load('node_production')
        n = object.__new__(p.Node)
        info = {'Id':'sha256:'+'a'*64, 'RootFS':{}, 'Config':{}, 'Architecture':'amd64', 'Os':'linux'}
        with patch.object(p, 'run', return_value=json.dumps([dict(info, Id='sha256:'+'b'*64)])):
            self.assertFalse(n.image_matches('container-image', info))

    def test_production_ci_is_manual_serial_protected(self):
        import yaml
        ci=yaml.safe_load((ROOT.parents[1]/'.gitlab-ci.yml').read_text())
        job=ci['local-ha-production-app']
        self.assertEqual(job['resource_group'],ci['deploy-k3s']['resource_group'])
        self.assertEqual(job['rules'][0]['when'],'on_success')
        self.assertIn('$STELLA_AUTO_DEPLOY == "true"',job['rules'][0]['if'])
        self.assertEqual(job['rules'][1]['when'],'manual')
        self.assertIn('$CI_COMMIT_REF_PROTECTED == "true"',job['rules'][0]['if'])
        self.assertIn('$STELLA_DEPLOY_TARGET == "local-ha"',job['rules'][0]['if'])
        self.assertEqual(ci['build-images']['artifacts']['reports']['dotenv'],'production-image.env')

if __name__ == '__main__':
    unittest.main()
