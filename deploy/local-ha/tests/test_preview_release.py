"""Preview release safety: no daemon used by these tests."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load():
    path = ROOT / 'preview_release.py'
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location('preview_release', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class PreviewTests(unittest.TestCase):
    def test_safety_contract_rejects_production_before_any_mutation(self):
        p = load()
        self.assertIsNotNone(p, 'preview release safety implementation missing')
        c = fixture(p)
        p.validate_container(c)
        for mutate in [
            lambda c: c.update(Name='/stella-production'),
            lambda c: c['Config'].update(Labels={}),
            lambda c: c['Config']['Env'].append('DATABASE_URL=postgres://production/stella'),
            lambda c: c['Config']['Env'].append('POSTGRES_DB=stella'),
            lambda c: c['Config']['Env'].append('POSTGRES_USER=production_user'),
            lambda c: c['HostConfig'].update(Privileged=True),
            lambda c: c['Mounts'][0].update(Source='/opt/hermes-workstation/stella-ha-poc-evil/private/stage-app-password'),
            lambda c: c['Mounts'][0].update(Source='/var/run/docker.sock'),
            lambda c: c['Config']['Cmd'].__setitem__(-3, '0.0.0.0'),
        ]:
            bad = copy.deepcopy(c)
            mutate(bad)
            with self.assertRaises(p.Refused):
                p.validate_container(bad)


    def test_release_candidate_gate_swap_rollback_and_idempotence(self):
        p = load()
        self.assertTrue(hasattr(p, 'release'), 'release transaction missing')
        for failure, expected in [(None, 'deployed'), ('candidate', 'candidate_failed'), ('stable', 'rolled_back')]:
            d = FakeDocker(p, failure)
            result = p.release(d, 'a'*40, {'scope':'stella-ha-preview', 'username':'synthetic', 'password':'private', 'document_id':'00000000-0000-4000-8000-000000000001', 'document_contains':'marker'})
            self.assertEqual(result['status'], expected)
            self.assertNotIn('private', str(result))
            self.assertIn(p.NAME, d.containers)
            self.assertTrue(d.containers[p.NAME]['State']['Running'])
            self.assertEqual(len(d.containers), 1)
            if failure == 'candidate':
                self.assertNotIn('stop', d.events)
            if not failure:
                again = p.release(d, 'a'*40, {'scope':'stella-ha-preview', 'username':'synthetic', 'password':'private', 'document_id':'00000000-0000-4000-8000-000000000001', 'document_contains':'marker'})
                self.assertEqual(again['status'], 'unchanged')

    def test_failure_edges_and_recovery_receipts(self):
        from unittest.mock import patch
        p = load()
        f = {'scope':'stella-ha-preview', 'username':'synthetic', 'password':'private', 'document_id':'00000000-0000-4000-8000-000000000001', 'document_contains':'marker'}
        for stage in ('candidate-create', 'candidate-start', 'stable-create', 'stable-start', 'rollback-health'):
            d = FakeDocker(p, 'stable' if stage == 'rollback-health' else None)
            original_create, original_start, original_health = d.create, d.start, d.health
            def create(config, name, digest, port):
                original_create(config, name, digest, port)
                if stage == ('candidate-create' if port == 24232 else 'stable-create'):
                    raise RuntimeError('partial create')
            def start(name):
                if (stage == 'candidate-start' and '-candidate-' in name) or (stage == 'stable-start' and name == p.NAME and d.containers[name]['Image'] != 'sha256:'+'1'*64):
                    raise RuntimeError('start')
                original_start(name)
            def health(name, port, f):
                if stage == 'rollback-health' and port == 24231:
                    raise RuntimeError('health')
                original_health(name, port, f)
            d.create, d.start, d.health = create, start, health
            result = p.release(d, 'a'*40, f)
            expected = 'candidate_failed' if stage.startswith('candidate') else 'rolled_back'
            if stage == 'rollback-health':
                expected = 'rollback_failed'
            self.assertEqual(result['status'], expected, stage)
            self.assertEqual(d.containers[p.NAME]['Image'], 'sha256:'+'1'*64)
            self.assertEqual(len(d.containers), 1)

    def test_pg_identity_and_invalid_sha_refused_before_pull(self):
        p = load()
        f = {'scope':'stella-ha-preview', 'username':'synthetic', 'password':'private', 'document_id':'00000000-0000-4000-8000-000000000001', 'document_contains':'marker'}
        from unittest.mock import Mock
        for kind in ('label', 'address', 'sha', 'fixture'):
            d = FakeDocker(p, None)
            original = d.inspect
            def inspect(name):
                c = original(name)
                if name.endswith('pg-a'):
                    if kind == 'label':
                        c['Config']['Labels'] = {}
                    if kind == 'address':
                        c['NetworkSettings']['Networks']['stella-ha-poc-net']['IPAddress'] = '10.0.0.1'
                return c
            d.inspect = inspect
            d.resolve = Mock(side_effect=AssertionError('must not pull'))
            with self.assertRaises(p.Refused):
                p.release(d, 'latest' if kind == 'sha' else 'a'*40, {} if kind == 'fixture' else f)
            d.resolve.assert_not_called()

    def test_cli_digest_and_stdin_transport(self):
        from unittest.mock import patch
        import json
        import subprocess
        p = load()
        d = p.Docker()
        seen = []
        def run(argv, **kwargs):
            seen.append((argv, kwargs))
            if argv[1:3] == ['image', 'inspect']:
                data = [{'Id':'sha256:'+'2'*64, 'RepoDigests':[p.REGISTRY+'@sha256:'+'2'*64]}]
            elif argv[1:3] == ['container', 'inspect']:
                data = [fixture(p)]
            else:
                data = ''
            return subprocess.CompletedProcess(argv, 0, json.dumps(data), '')
        with patch.object(p.subprocess, 'run', side_effect=run):
            digest, image = d.resolve('a'*40)
            self.assertEqual(digest, p.REGISTRY+'@sha256:'+'2'*64)
            d.health(p.NAME, 24231, {'password':'never-log-this'})
        self.assertNotIn('never-log-this', str([a for a,k in seen]))
        self.assertIn('never-log-this', seen[2][1]['input'])
        self.assertEqual(seen[0][0], ['docker','pull',p.REGISTRY+':'+'a'*40])
        compile(p.HEALTH_CODE, '<health>', 'exec')

    def test_ci_preview_job_is_manual_serialized_nonproduction(self):
        import yaml
        ci = yaml.safe_load((ROOT.parents[1] / '.gitlab-ci.yml').read_text())
        job = ci['local-ha-preview']
        self.assertEqual(job['resource_group'], 'stella-ha-preview')
        self.assertEqual(job['rules'][0]['when'], 'manual')
        self.assertEqual(job['environment']['deployment_tier'], 'testing')
        self.assertEqual(job['artifacts']['when'], 'always')
        self.assertFalse(job['interruptible'])
        self.assertIn('feature/local-ha-20260915', job['rules'][0]['if'])
        self.assertNotIn('local-ha-apply', ci)


class FakeDocker:
    def __init__(self, p, failure):
        self.p, self.failure, self.events = p, failure, []
        self.containers = {p.NAME: fixture(p)}

    def inspect(self, name):
        if name == 'stella-ha-poc-pg-a':
            return {'Name':'/' + name, 'Config':{'Labels':{self.p.LABEL:self.p.SCOPE}},
                    'NetworkSettings':{'Networks':{'stella-ha-poc-net':{'IPAddress':'172.25.0.6'}}}, 'State':{'Running':True}}
        return copy.deepcopy(self.containers[name])

    def resolve(self, sha):
        return self.p.REGISTRY + '@sha256:' + '2'*64, 'sha256:' + '2'*64

    def create(self, config, name, digest, port):
        c = copy.deepcopy(config)
        c.update(Name='/' + name, Id=name, Image='sha256:' + '2'*64)
        c['Config']['Cmd'] = self.p.command(port)
        c['State']['Running'] = False
        self.containers[name] = c

    def health(self, name, port, fixture):
        self.events.append('health-' + str(port))
        if (self.failure == 'candidate' and port == 24232) or (self.failure == 'stable' and port == 24231 and self.containers[name]['Image'] == 'sha256:' + '2'*64):
            raise RuntimeError('unhealthy')

    def stop(self, name):
        self.events.append('stop')
        self.containers[name]['State']['Running'] = False

    def start(self, name):
        self.containers[name]['State']['Running'] = True

    def rename(self, old, new):
        c = self.containers.pop(old)
        c['Name'] = '/' + new
        self.containers[new] = c

    def remove(self, name):
        self.containers.pop(name, None)


def fixture(p):
    return {'Id': 'old-id', 'Name': '/' + p.NAME, 'Image': 'sha256:' + '1'*64,
            'Config': {'Labels': {p.LABEL: p.SCOPE}, 'Env': [f'{k}={v}' for k,v in p.REQUIRED_ENV.items()],
                       'Entrypoint': ['/app/.venv/bin/python'], 'Cmd': p.command(24231), 'WorkingDir': '/app'},
            'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': 'host', 'Privileged': False,
                           'Memory': 1073741824, 'NanoCpus': 2000000000, 'CapDrop': ['ALL'],
                           'SecurityOpt': ['no-new-privileges'], 'RestartPolicy': {'Name':'no'}},
            'Mounts': [{'Type':'bind', 'Source':s, 'Destination':d, 'RW':rw, 'Propagation':'rprivate'}
                       for s,(d,rw) in p.MOUNTS.items()], 'State': {'Running':True}}
