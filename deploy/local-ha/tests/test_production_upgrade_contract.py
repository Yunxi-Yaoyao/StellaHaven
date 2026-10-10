"""Offline production configuration upgrade contracts: never contact a host."""
import copy
import unittest
from unittest.mock import patch
from test_production_release import load


def overrides():
    return {
        'STELLA_TRUSTED_ORIGINS': 'https://stella.xiya.live,https://stella.yunxi.life,http://127.0.0.1:25131,http://127.0.0.1:25132',
        'STELLA_MAIN_ORIGIN': 'https://stella.xiya.live',
        'STELLA_OWNER_ID': '11111111-1111-4111-8111-111111111111',
        'STELLA_COOKIE_SECURE': 'true',
        'STELLA_AGENT_ROLLOUT_VERSION': '0.6.9',
        'STELLA_BACKUP_RECEIPT_DIR': '/app/data/backup-receipts',
    }


def inventory() -> dict:
    p = load('production_release')
    mounts = [{'Source': p.BASE + str(i), 'Destination': d, 'RW': d == '/tmp'}
              for i, d in enumerate(['/app/data', '/tmp', '/data/secret_key',
                                    '/run/secrets/app-password', '/run/secrets/oidc-private.json', '/shadow-start.py'])]
    return dict(scope='stella-production-app-v1', forward_compatible=True,
                schema_revision='new_revision', manifest_sha256='a' * 64, signing_sha256='b' * 64,
                nodes={n: dict(host=ip, alias='stella-prod-' + n, command=['/shadow-start.py'],
                              mounts=copy.deepcopy(mounts), startup_sha256='c' * 64,
                              memory=1024, nano_cpus=1000, application_env_overrides=overrides())
                       for n, ip in p.NODES.items()})

def container(p, node='nas'):
    inv = inventory()
    cfg = inv['nodes'][node]
    return {
        'Id': 'old', 'Name': '/stella-app-shadow-' + node, 'Image': 'same-image',
        'State': {'Running': True},
        'Config': {'Entrypoint': ['/app/.venv/bin/python'], 'WorkingDir': '/app',
                   'Cmd': ['/shadow-start.py'], 'Labels': {},
                   'Env': ['PGOPTIONS=-c statement_timeout=30000', 'POSTGRES_HOST=127.0.0.1',
                           'POSTGRES_PORT=24532', 'POSTGRES_DB=stella', 'STELLA_HA_MODE=primary-only',
                           'STELLA_BLOB_STORAGE=postgres', 'STELLA_SHARED_STATE=postgres',
                           'STELLA_PATRONI_URL=http://' + p.NODES[node] + ':24808']},
        'HostConfig': {'NetworkMode': 'host', 'ReadonlyRootfs': True, 'Memory': 1024,
                       'NanoCpus': 1000, 'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                       'RestartPolicy': {'Name': 'unless-stopped'}},
        'Mounts': [dict(m, Type='bind', Propagation='rprivate') for m in cfg['mounts']],
    }

def release_simulation(p, fail_stable=False, old_current=False, target_agent_version=None):
    import json
    class Simulation(p.Node):
        def __init__(self):
            inv = inventory()
            if target_agent_version is not None:
                for cfg in inv['nodes'].values():
                    cfg['application_env_overrides']['STELLA_AGENT_ROLLOUT_VERSION'] = target_agent_version
            super().__init__(dict(node='nas', inventory=inv, image=p.REGISTRY + '@sha256:' + 'd' * 64,
                                  registry_user='test', registry_password='test',
                                  expected_roles={'nyarch': True, 'nas': False}))
            c = container(p)
            if old_current:
                c['Config']['Cmd'] = ['-c', p.START, '25131']
                c['Config']['Env'] += [k + '=' + v for k, v in overrides().items()]
            self.containers = {self.name: c}
            self.events = []
        def inspect(self, name):
            return next(c for k, c in self.containers.items() if k == name or c['Id'] == name)
        def pg_guard(self):
            return 'pg-unchanged'
        def probe(self, name=None, port=25131, expected=True):
            if fail_stable and port and (name or self.name) == self.name and self.inspect(self.name)['Id'] != 'old':
                raise ValueError('stable unhealthy')
            return dict(roles={'nyarch': True, 'nas': False}, manifest='a' * 64,
                        http={'live': 200, 'ready_primary': 503})
        def health(self, name, port, expected=True):
            return self.probe(name, port, expected)
        def image_matches(self, actual, info):
            return True
        def command(self, args, data=None, **kw):
            self.events.append(tuple(args[1:]))
            if args[1:3] == ['image', 'inspect']:
                return json.dumps([{'Id': 'sha256:' + 'd' * 64, 'RepoDigests': [self.r['image']]}])
            if args[1] in ('login', 'pull'):
                return ''
            if args[1] == 'create':
                name = args[args.index('--name') + 1]
                c = copy.deepcopy(container(p))
                c.update(Id='created-' + str(len(self.events)), Name='/' + name)
                c['State']['Running'] = False
                c['Config']['Cmd'] = args[-3:]
                c['Config']['Env'] = data.splitlines()
                self.containers[name] = c
                return c['Id']
            c = self.inspect(args[-2] if args[1] == 'rename' else args[-1])
            if args[1] == 'rename':
                del self.containers[c['Name'][1:]]
                c['Name'] = '/' + args[-1]
                self.containers[args[-1]] = c
            elif args[1] == 'rm':
                del self.containers[c['Name'][1:]]
            else:
                c['State']['Running'] = args[1] == 'start'
            return ''
    return Simulation()


class UpgradeContractTests(unittest.TestCase):
    def test_inventory_accepts_explicit_read_only_hardware_agent_0611(self):
        p = load('production_release')
        inv = inventory()
        for cfg in inv['nodes'].values():
            cfg['application_env_overrides']['STELLA_AGENT_ROLLOUT_VERSION'] = '0.6.11'
        self.assertEqual(p.validate_inventory(inv), inv)
        load('node_production').Node(dict(node='nas', inventory=inv, op='release'))

    def test_hardware_rollout_requires_exact_explicit_0611_two_node_approval(self):
        p = load('production_release')
        inv = inventory()
        for cfg in inv['nodes'].values():
            cfg['application_env_overrides']['STELLA_AGENT_ROLLOUT_VERSION'] = '0.6.11'
        self.assertEqual(p.validate_release_approval(inv, '0.6.11'), inv)
        for version in (None, '0.6.9', '0.6.10', '0.6.12', '0.6.11 ', '0.6.011', 'latest'):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'agent rollout'):
                if version is None:
                    p.validate_release_approval(inv)
                else:
                    p.validate_release_approval(inv, version)
        inv['nodes']['nas']['application_env_overrides']['STELLA_AGENT_ROLLOUT_VERSION'] = '0.6.10'
        with self.assertRaisesRegex(ValueError, 'agent rollout'):
            p.validate_release_approval(inv, '0.6.11')

    def test_hardware_upgrade_0610_to_0611_same_image_redeploys_or_restores_exact_old(self):
        p = load('node_production')
        for fail in (False, True):
            with self.subTest(fail=fail):
                n = release_simulation(p, fail_stable=fail, old_current=True, target_agent_version='0.6.11')
                old = n.inspect(n.name)
                old['Config']['Env'] = ['STELLA_AGENT_ROLLOUT_VERSION=0.6.10' if row.startswith('STELLA_AGENT_ROLLOUT_VERSION=')
                                        else row for row in old['Config']['Env']]
                original = copy.deepcopy(old)
                with patch.object(p, 'port_free'), patch.object(p, 'validate_receipt_bundle'), patch.object(p, 'run', side_effect=n.command), \
                        patch.object(p.Path, 'read_bytes', return_value=b'fixture'), patch.object(p.hashlib, 'sha256') as sha:
                    sha.return_value.hexdigest.return_value = 'c' * 64
                    result = n.release()
                    self.assertEqual(result['status'], 'rolledback' if fail else 'deployed')
                    restored = n.inspect(n.name)
                    if fail:
                        self.assertEqual(restored, original)
                    else:
                        target_env = dict(row.split('=', 1) for row in restored['Config']['Env'])
                        old_env = dict(row.split('=', 1) for row in original['Config']['Env'])
                        self.assertEqual(target_env['STELLA_AGENT_ROLLOUT_VERSION'], '0.6.11')
                        old_env['STELLA_AGENT_ROLLOUT_VERSION'] = '0.6.11'
                        self.assertEqual(target_env, old_env)
                        self.assertEqual(n.release()['status'], 'unchanged')

    def test_inventory_rejects_arbitrary_environment_additions(self):
        p = load('production_release')
        p.validate_inventory(inventory())
        for key in ('POSTGRES_HOST', 'PGOPTIONS', 'STELLA_SECRET_KEY', 'PYTHONPATH', 'ARBITRARY'):
            with self.subTest(key=key):
                inv = inventory()
                inv['nodes']['nas']['application_env_overrides'][key] = 'bad'
                with self.assertRaisesRegex(ValueError, 'application'):
                    p.validate_inventory(inv)

    def test_inventory_rejects_unsafe_application_values(self):
        p = load('production_release')
        invalid = {
            'STELLA_TRUSTED_ORIGINS': ['https://evil.example,http://127.0.0.1:25131,http://127.0.0.1:25132',
                                      'https://stella.xiya.live',
                                      overrides()['STELLA_TRUSTED_ORIGINS'] + ',https://*.xiya.live',
                                      overrides()['STELLA_TRUSTED_ORIGINS'] + ',https://stella.xiya.live/',
                                      overrides()['STELLA_TRUSTED_ORIGINS'] + ',http://10.66.0.2:25131'],
            'STELLA_MAIN_ORIGIN': ['https://evil.example', 'https://stella.xiya.live/', 'http://stella.xiya.live'],
            'STELLA_OWNER_ID': ['not-a-uuid', '00000000-0000-0000-0000-000000000000', ' 11111111-1111-4111-8111-111111111111'],
            'STELLA_COOKIE_SECURE': ['false', 'True', True],
            'STELLA_AGENT_ROLLOUT_VERSION': ['0.6.8', '0.6.12', '0.6.11 ', '0.6.011', 'latest'],
            'STELLA_BACKUP_RECEIPT_DIR': ['/root/.credentials/stella-upgrade', '/data/backup-receipts', '/app/data/../secrets'],
        }
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    inv = inventory()
                    inv['nodes']['nas']['application_env_overrides'][key] = value
                    with self.assertRaises(ValueError):
                        p.validate_inventory(inv)
        inv = inventory()
        inv['nodes']['nas']['application_env_overrides']['STELLA_AGENT_ROLLOUT_VERSION'] = '0.6.10'
        p.validate_inventory(inv)

    def test_candidate_and_stable_merge_only_approved_fields(self):
        p = load('node_production')
        n = object.__new__(p.Node)
        n.cfg = inventory()['nodes']['nas']
        old = {'Config': {'Env': ['PGOPTIONS=-c statement_timeout=30000', 'PATH=/usr/bin',
                                 'STELLA_AGENT_ROLLOUT_VERSION=0.6.8'], 'Labels': {}},
               'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped'}}}
        for port in (25131, 25132):
            with patch.object(p, 'port_free'), patch.object(p, 'validate_receipt_bundle'), patch.object(p, 'run', return_value='id') as run:
                n.create(old, 'test', 'sha256:' + 'a' * 64, port)
            env = dict(row.split('=', 1) for row in run.call_args.args[1].splitlines())
            self.assertEqual({k: env.get(k) for k in overrides()}, overrides())
            self.assertEqual(env['PATH'], '/usr/bin')
            self.assertEqual(env['PGOPTIONS'], '-c statement_timeout=30000')
            self.assertEqual(len(run.call_args.args[1].splitlines()), len(env))
            self.assertNotIn('STELLA_OWNER_ID=' + overrides()['STELLA_OWNER_ID'], run.call_args.args[0])
        self.assertIn('STELLA_AGENT_ROLLOUT_VERSION=0.6.8', old['Config']['Env'])
        inv = inventory()
        inv['nodes']['nas']['application_env_overrides']['POSTGRES_HOST'] = 'bad'
        with self.assertRaisesRegex(ValueError, 'application'):
            p.Node(dict(node='nas', inventory=inv))

    def test_old_validation_keeps_mount_pins_but_candidate_requires_approved_env(self):
        p = load('node_production')
        n = p.Node(dict(node='nas', inventory=inventory()))
        c = container(p)
        with patch.object(p, 'validate_receipt_bundle'), patch.object(p.Path, 'read_bytes', return_value=b'fixture'), patch.object(p.hashlib, 'sha256') as sha:
            sha.return_value.hexdigest.return_value = 'c' * 64
            n.validate(c)  # missing new fields in an old container is intentional
            bad = copy.deepcopy(c)
            bad['Mounts'][0]['Source'] = p.BASE + 'unapproved'
            with self.assertRaisesRegex(ValueError, 'exact mount'):
                n.validate(bad)
            candidate = copy.deepcopy(c)
            candidate['Name'] = '/candidate'
            candidate['Config']['Cmd'] = ['-c', p.START, '25132']
            with self.assertRaisesRegex(ValueError, 'approved application'):
                n.validate(candidate, 'candidate', 25132, True)
            candidate['Config']['Env'] += [k + '=' + v for k, v in overrides().items()]
            n.validate(candidate, 'candidate', 25132, True)
            candidate['Config']['Env'][-1] = 'STELLA_BACKUP_RECEIPT_DIR=/data'
            with self.assertRaisesRegex(ValueError, 'approved application'):
                n.validate(candidate, 'candidate', 25132, True)

    def test_same_image_changed_environment_redeploys_then_is_idempotent(self):
        p = load('node_production')
        for fail in (False, True):
            n = release_simulation(p, fail_stable=fail)
            original = copy.deepcopy(n.inspect(n.name))
            with patch.object(p, 'port_free'), patch.object(p, 'validate_receipt_bundle'), patch.object(p, 'run', side_effect=n.command), \
                    patch.object(p.Path, 'read_bytes', return_value=b'fixture'), patch.object(p.hashlib, 'sha256') as sha:
                sha.return_value.hexdigest.return_value = 'c' * 64
                result = n.release()
                self.assertEqual(result['status'], 'rolledback' if fail else 'deployed')
                restored = n.inspect(n.name)
                if fail:
                    self.assertEqual(restored, original)
                else:
                    self.assertTrue(n.application_environment_matches(restored))
                    result = n.release()
                    self.assertEqual(result['status'], 'unchanged')
                    n.cfg['application_env_overrides']['STELLA_OWNER_ID'] = '22222222-2222-4222-8222-222222222222'
                    self.assertEqual(n.release()['status'], 'deployed')
            self.assertTrue(n.inspect(n.name)['State']['Running'])

    def test_receipt_bundle_requires_root_owned_nonsymlink_readonly_chain(self):
        import tempfile
        from pathlib import Path
        p = load('node_production')
        # The production contract rejects world-writable ancestors. CI's
        # default /tmp is therefore an invalid positive fixture, not a reason
        # to weaken the guard. Prefer the runtime scratch root; CI falls back
        # to its private home and removes the entire owned temporary tree.
        import os
        candidate = Path(os.environ.get('TMPDIR') or Path.home()).resolve()
        if any(part.stat().st_mode & 0o022 for part in [candidate, *candidate.parents]):
            candidate = Path.home().resolve()
        with tempfile.TemporaryDirectory(dir=candidate) as tmp, patch.object(p, 'BASE', tmp + '/'):
            root = Path(tmp) / 'modelpack'
            (root / 'backup-receipts').mkdir(parents=True)
            mount = {'Source': str(root), 'Destination': '/app/data', 'RW': False}
            validate = getattr(p, 'validate_receipt_bundle', lambda mounts: None)
            validate([mount])
            for bad in (dict(mount, RW=True), dict(mount, Source=tmp + '/../outside')):
                with self.assertRaises(ValueError):
                    validate([bad])
            (root / 'backup-receipts').rmdir()
            with self.assertRaises(ValueError):
                validate([mount])
            (root / 'backup-receipts').mkdir()
            root.chmod(0o777)
            with self.assertRaises(ValueError):
                validate([mount])
            root.chmod(0o755)
            link = Path(tmp) / 'linked'
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                validate([dict(mount, Source=str(link))])
        inv = inventory()
        inv['nodes']['nas']['target_mounts'] = []
        with self.assertRaisesRegex(ValueError, 'target mounts'):
            load('production_release').validate_inventory(inv)
        with self.assertRaisesRegex(ValueError, 'target mounts'):
            p.Node(dict(node='nas', inventory=inv))

    def test_target_probe_rejects_previous_schema_before_network(self):
        import io
        import sys
        import types
        p = load('node_production')
        config = types.ModuleType('alembic.config')
        config.Config = lambda path: object()
        scripts = types.ModuleType('alembic.script')
        scripts.ScriptDirectory = types.SimpleNamespace(from_config=lambda cfg: types.SimpleNamespace(get_heads=lambda: ['old_revision']))
        with patch.dict(sys.modules, {'psycopg2': types.ModuleType('psycopg2'), 'alembic.config': config, 'alembic.script': scripts}), \
                patch('sys.stdin', io.StringIO('{"revision":"new_revision","previous":"old_revision","target":true}')), \
                patch('urllib.request.build_opener', side_effect=AssertionError('network before target schema check')):
            with self.assertRaisesRegex(ValueError, 'schema'):
                exec(compile(p.PROBE, 'probe', 'exec'), {})

    def test_probe_targets_are_strict_and_rollback_old_bundle_remains_allowed(self):
        import json
        p = load('node_production')
        inv = inventory()
        inv.update(previous_schema_revision='old_revision', previous_manifest_sha256='e' * 64)
        n = p.Node(dict(node='nas', inventory=inv))
        n.target_names = {'candidate'}
        with patch.object(p, 'run', return_value='{}') as run:
            n.probe()
            old = json.loads(run.call_args.args[1])
            n.probe('candidate', 25132)
            target = json.loads(run.call_args.args[1])
        self.assertFalse(old.get('target', False))
        self.assertEqual(old.get('previous_manifest'), 'e' * 64)
        self.assertTrue(target.get('target'))
        self.assertEqual(target.get('receipt_dir'), '/app/data/backup-receipts')
        self.assertEqual(target['port'], 25132)

    def test_orchestration_accepts_old_bundle_only_until_each_node_is_upgraded(self):
        p = load('production_release')
        inv = inventory()
        inv['previous_manifest_sha256'] = 'e' * 64
        class Transport:
            def __init__(self, lie=False): self.upgraded = set(); self.lie = lie
            def call(self, node, op, **kw):
                if op == 'release':
                    self.upgraded.add(node)
                    return {'status': 'deployed'}
                current = node in self.upgraded and not self.lie
                return dict(status='healthy', node=node, primary=node == 'nyarch',
                            roles={'nyarch': True, 'nas': False}, revision='new_revision', signing='b' * 64,
                            manifest=('a' if current else 'e') * 64, application_environment_matches=current)
        t = Transport()
        result = p.orchestrate(t, inv)
        self.assertEqual(result['status'], 'deployed')
        self.assertEqual(t.upgraded, {'nas', 'nyarch'})
        t = Transport(lie=True)
        self.assertEqual(p.orchestrate(t, inv)['status'], 'blocked')
        self.assertEqual(t.upgraded, {'nas'})
        inv['previous_manifest_sha256'] = '/unapproved'
        with self.assertRaisesRegex(ValueError, 'previous manifest'):
            p.validate_inventory(inv)

    def test_release_requires_complete_upgrade_pack_and_default_agent_pause(self):
        p = load('production_release')
        approve = getattr(p, 'validate_release_approval', lambda inv, version='0.6.9': None)
        inv = inventory()
        approve(inv)
        for n in inv['nodes']:
            inv['nodes'][n]['application_env_overrides']['STELLA_AGENT_ROLLOUT_VERSION'] = '0.6.10'
        with self.assertRaisesRegex(ValueError, 'agent rollout'):
            approve(inv)
        approve(inv, '0.6.10')  # explicit operator gate, after whole fleet helper readback
        inv['nodes']['nas']['application_env_overrides']['STELLA_AGENT_ROLLOUT_VERSION'] = '0.6.9'
        with self.assertRaises(ValueError):
            approve(inv, '0.6.10')
        del inv['nodes']['nas']['application_env_overrides']
        with self.assertRaisesRegex(ValueError, 'application'):
            approve(inv)
        with self.assertRaisesRegex(ValueError, 'application'):
            load('node_production').Node(dict(node='nas', inventory=inv, op='release'))

    def test_post_release_readback_requests_strict_target_probe(self):
        p = load('production_release')
        inv = inventory()
        class Transport:
            def __init__(self): self.upgraded = set(); self.target_probes = []
            def call(self, node, op, **kw):
                if op == 'release':
                    self.upgraded.add(node)
                    return {'status': 'deployed'}
                if node in self.upgraded:
                    self.target_probes.append(kw.get('target', False))
                return dict(status='healthy', node=node, primary=node == 'nyarch',
                            roles={'nyarch': True, 'nas': False}, revision='new_revision', signing='b' * 64,
                            manifest='a' * 64, application_environment_matches=node in self.upgraded)
        t = Transport()
        self.assertEqual(p.orchestrate(t, inv)['status'], 'deployed')
        self.assertTrue(t.target_probes)
        self.assertTrue(all(t.target_probes))
        node = load('node_production')
        n = node.Node(dict(node='nas', inventory=inv, op='probe', target=True))
        c = container(node)
        with patch.object(n, 'inspect', return_value=c), patch.object(n, 'pg_guard'), patch.object(n, 'probe', return_value={'roles': {'nyarch': True, 'nas': False}}), \
                patch.object(node.Path, 'read_bytes', return_value=b'fixture'), patch.object(node.hashlib, 'sha256') as sha:
            sha.return_value.hexdigest.return_value = 'c' * 64
            with self.assertRaisesRegex(ValueError, 'approved application'):
                n.execute()

    def test_rollback_receipt_refuses_changed_old_environment(self):
        p = load('node_production')
        n = release_simulation(p, fail_stable=True)
        original_command = n.command
        def command(args, *a, **kw):
            result = original_command(args, *a, **kw)
            if args[1:] == ['start', 'old']:
                n.inspect('old')['Config']['Env'].append('STELLA_COOKIE_SECURE=false')
            return result
        with patch.object(p, 'port_free'), patch.object(p, 'validate_receipt_bundle'), patch.object(p, 'run', side_effect=command), \
                patch.object(p.Path, 'read_bytes', return_value=b'fixture'), patch.object(p.hashlib, 'sha256') as sha:
            sha.return_value.hexdigest.return_value = 'c' * 64
            result = n.release()
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('rollback incomplete', result['reason'])

    def test_release_rejects_conflicting_ha_owner_or_origin_approvals(self):
        p = load('production_release')
        for key, value in [('STELLA_OWNER_ID', '22222222-2222-4222-8222-222222222222'),
                           ('STELLA_MAIN_ORIGIN', 'https://stella.yunxi.life')]:
            inv = inventory()
            inv['nodes']['nas']['application_env_overrides'][key] = value
            p.validate_inventory(inv)
            with self.assertRaisesRegex(ValueError, 'two-node application'):
                p.validate_release_approval(inv)

    def test_strict_validation_checks_approved_receipt_directory_chain(self):
        p = load('node_production')
        n = p.Node(dict(node='nas', inventory=inventory()))
        c = container(p)
        c['Config']['Env'] += [k + '=' + v for k, v in overrides().items()]
        with patch.object(p.Path, 'read_bytes', return_value=b'fixture'), patch.object(p.hashlib, 'sha256') as sha, \
                patch.object(p, 'validate_receipt_bundle', side_effect=ValueError('receipt chain changed')):
            sha.return_value.hexdigest.return_value = 'c' * 64
            n.validate(c)  # initial/rollback validation intentionally remains legacy
            with self.assertRaisesRegex(ValueError, 'receipt chain'):
                n.validate(c, approved_environment=True)


if __name__ == '__main__':
    unittest.main()
