"""All normalization tests are offline; Docker and probes are simulated."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch
from test_production_release import load
from test_production_upgrade_contract import inventory, container, overrides


OLD_ID = '1' * 64
IMAGE_ID = 'sha256:' + '2' * 64
PG_ID = '3' * 64
ROLES = {'nyarch': True, 'nas': False}


def approval() -> tuple[dict, dict]:
    p = load('node_production')
    inv = inventory()
    for cfg in inv['nodes'].values():
        cfg.update(memory=1073741824, nano_cpus=2000000000,
                   startup_sha256=hashlib.sha256(b'fixture').hexdigest())
    old = container(p)
    old.update(Id=OLD_ID, Image=IMAGE_ID)
    old['Config'].update(Entrypoint=None, Cmd=['/app/.venv/bin/python', '/shadow-start.py'])
    old['Config']['Env'] += [k + '=' + v for k, v in overrides().items()]
    old['HostConfig'].update(Memory=0, NanoCpus=0, CapDrop=None, SecurityOpt=None,
                             ReadonlyRootfs=False, Init=False,
                             RestartPolicy={'Name': 'no', 'MaximumRetryCount': 0})
    image = dict(Id=IMAGE_ID, RootFS={'Type': 'layers', 'Layers': ['sha256:' + '4' * 64]},
                 Config={'WorkingDir': '/app'}, Architecture='amd64', Os='linux')
    return dict(scope='stella-manual-runtime-normalize-v1', node='nas', inventory=inv,
                approved_old={k: copy.deepcopy(old[k]) for k in ('Id', 'Image', 'Config', 'HostConfig', 'Mounts')},
                approved_image=image, approved_pg_id=PG_ID, expected_roles=copy.deepcopy(ROLES)), old


class Harness:
    def __init__(self, module, request=None):
        self.m = module
        self.request, old = approval()
        if request is not None:
            self.request = request
        self.n = module.Normalizer(self.request)
        self.containers = {old['Id']: old}
        self.events = []
        self.inputs = []
        self.n.pg_guard = lambda: PG_ID
        self.n.probe = self.probe
        self.n.health = lambda name, port, expected=True: self.probe(name, port, expected)

    def inspect(self, name):
        for c in self.containers.values():
            if c['Id'] == name or c['Name'] == '/' + name:
                return c
        raise ValueError('container missing')

    def probe(self, name=None, port=25131, expected=True) -> dict:
        name = name or self.n.name
        c = self.inspect(name)
        if not c['State']['Running']:
            raise ValueError('probe stopped container')
        self.events.append(('probe', c['Id'], port, expected))
        return dict(roles=copy.deepcopy(ROLES), manifest=self.request['inventory']['manifest_sha256'],
                    signing=self.request['inventory']['signing_sha256'], revision='new_revision',
                    http={'live': 200, 'ready_primary': 503})

    def command(self, args, data=None, **kw):
        self.events.append(tuple(args[1:]))
        if args[1] == 'inspect':
            return json.dumps([self.inspect(args[-1])])
        if args[1:3] == ['image', 'inspect']:
            return json.dumps([self.request['approved_image']])
        if args[1] == 'create':
            self.inputs.append((args, data))
            name = args[args.index('--name') + 1]
            if any(c['Name'] == '/' + name for c in self.containers.values()):
                raise ValueError('name in use')
            old = self.request['approved_old']
            c = copy.deepcopy(old)
            c.update(Id=str(len(self.containers) + 4) * 64, Name='/' + name, State={'Running': False})
            image_pos = args.index(IMAGE_ID)
            c['Config'].update(Entrypoint=['/app/.venv/bin/python'], WorkingDir='/app',
                               Cmd=args[image_pos + 1:], Env=data.splitlines())
            c['HostConfig'].update(ReadonlyRootfs=True, Init=True, Memory=1073741824,
                                  NanoCpus=2000000000, CapDrop=['ALL'],
                                  SecurityOpt=['no-new-privileges'],
                                  RestartPolicy={'Name': 'unless-stopped' if '--restart=unless-stopped' in args else 'no', 'MaximumRetryCount': 0})
            self.containers[c['Id']] = c
            return c['Id']
        if args[1] not in ('start', 'stop', 'rename'):
            raise AssertionError('unexpected or forbidden Docker operation')
        c = self.inspect(args[-2] if args[1] == 'rename' else args[-1])
        if args[1] == 'rename':
            if any(x['Name'] == '/' + args[-1] for x in self.containers.values()):
                raise ValueError('name in use')
            c['Name'] = '/' + args[-1]
        else:
            c['State']['Running'] = args[1] == 'start'
        return ''

    def run(self, apply=False):
        with patch.object(self.m.contract, 'run', side_effect=self.command), \
                patch.object(self.m.contract, 'port_free'), \
                patch.object(self.m.contract, 'validate_receipt_bundle'), \
                patch.object(self.m.contract.Path, 'read_bytes', return_value=b'fixture'):
            return self.n.normalize(apply=apply)

    def mutations(self):
        return [e for e in self.events if e[0] in ('create', 'start', 'stop', 'rename', 'rm')]


class NormalizeTests(unittest.TestCase):

    def test_docker_mount_order_drift_does_not_change_approved_mount_identity(self):
        m = load('normalize_manual_runtime')
        h = Harness(m)
        h.containers[OLD_ID]['Mounts'].reverse()
        self.assertEqual(h.run()['status'], 'validated')
        self.assertEqual(h.mutations(), [])

    def test_reordered_mount_with_changed_source_is_still_rejected(self):
        m = load('normalize_manual_runtime')
        h = Harness(m)
        h.containers[OLD_ID]['Mounts'].reverse()
        h.containers[OLD_ID]['Mounts'][0]['Source'] += '-changed'
        with self.assertRaisesRegex(ValueError, 'snapshot changed'):
            h.run()
        self.assertEqual(h.mutations(), [])


    def test_memory_bound_restores_default_oom_killer_without_allowing_disable(self):
        m = load('normalize_manual_runtime')
        h = Harness(m)
        old_command = h.command
        h.request['approved_old']['HostConfig']['OomKillDisable'] = None
        h.n.r['approved_old']['HostConfig']['OomKillDisable'] = None
        h.containers[OLD_ID]['HostConfig']['OomKillDisable'] = None
        def command(args, data=None, **kw):
            out = old_command(args, data, **kw)
            if args[1] == 'create':
                h.containers[out]['HostConfig']['OomKillDisable'] = False
            return out
        h.command = command
        self.assertEqual(h.run(apply=True)['status'], 'normalized')
        h = Harness(m)
        h.request['approved_old']['HostConfig']['OomKillDisable'] = None
        h.n.r['approved_old']['HostConfig']['OomKillDisable'] = None
        h.containers[OLD_ID]['HostConfig']['OomKillDisable'] = None
        old_command = h.command
        def forbidden(args, data=None, **kw):
            out = old_command(args, data, **kw)
            if args[1] == 'create':
                h.containers[out]['HostConfig']['OomKillDisable'] = True
            return out
        h.command = forbidden
        self.assertEqual(h.run(apply=True)['status'], 'blocked')
        self.assertFalse(any(e[0] == 'start' for e in h.mutations()))

    def test_default_is_read_only_and_existing_guard_still_rejects_manual(self):
        from pathlib import Path
        self.assertTrue((Path(__file__).resolve().parents[1] / 'normalize_manual_runtime.py').exists(),
                        'explicit opt-in normalization helper is missing')
        m = load('normalize_manual_runtime')
        h = Harness(m)
        result = h.run()
        self.assertEqual(result['status'], 'validated')
        self.assertTrue(result['read_only'])
        self.assertEqual(h.mutations(), [])
        with self.assertRaisesRegex(ValueError, 'entrypoint'):
            m.contract.Node(h.request).validate(h.inspect(OLD_ID))


    def test_apply_validates_candidate_before_swap_and_restores_golden_exact_env(self):
        m = load('normalize_manual_runtime')
        h = Harness(m)
        original = copy.deepcopy(h.inspect(OLD_ID))
        result = h.run(apply=True)
        self.assertEqual(result['status'], 'normalized')
        stable = h.inspect(h.n.name)
        self.assertNotEqual(stable['Id'], OLD_ID)
        self.assertEqual(stable['Image'], IMAGE_ID)
        self.assertEqual(stable['Config']['Env'], original['Config']['Env'])
        self.assertEqual(stable['Config']['Labels'], original['Config']['Labels'])
        self.assertEqual(stable['Mounts'], original['Mounts'])
        self.assertEqual(stable['Config']['Entrypoint'], ['/app/.venv/bin/python'])
        self.assertEqual(stable['Config']['Cmd'], ['/shadow-start.py'])
        self.assertTrue(stable['HostConfig']['Init'])
        self.assertTrue(stable['HostConfig']['ReadonlyRootfs'])
        self.assertEqual(stable['HostConfig']['Memory'], 1073741824)
        self.assertEqual(stable['HostConfig']['NanoCpus'], 2000000000)
        self.assertEqual(stable['HostConfig']['RestartPolicy']['Name'], 'unless-stopped')
        self.assertEqual(h.inspect(OLD_ID)['Name'], '/' + result['backup'])
        self.assertFalse(h.inspect(OLD_ID)['State']['Running'])
        candidate_health = next(i for i, e in enumerate(h.events) if e[0] == 'probe' and e[2] == 25132)
        old_stop = h.events.index(('stop', '--time', '30', OLD_ID))
        self.assertLess(candidate_health, old_stop)
        self.assertFalse(any(e[0] in ('pull', 'login', 'rm') for e in h.events))
        self.assertEqual(len(h.inputs), 2)
        for argv, stdin in h.inputs:
            self.assertIn('--pull=never', argv)
            self.assertIn('--env-file', argv)
            self.assertEqual(stdin.splitlines(), original['Config']['Env'])
            self.assertFalse(any('STELLA_OWNER_ID=' in arg for arg in argv))
        with patch.object(m.contract, 'validate_receipt_bundle'), patch.object(m.contract.Path, 'read_bytes', return_value=b'fixture'):
            m.contract.Node(h.request).validate(stable, approved_environment=True)

    def test_failed_stable_health_restores_exact_old_and_retains_failed_containers(self):
        m = load('normalize_manual_runtime')
        h = Harness(m)
        original = copy.deepcopy(h.inspect(OLD_ID))
        def health(name, port, expected=True):
            if name == h.n.name and h.inspect(name)['Id'] != OLD_ID:
                raise ValueError('stable unhealthy secret-must-not-leak')
            return h.probe(name, port, expected)
        h.n.health = health
        result = h.run(apply=True)
        self.assertEqual(result['status'], 'rolledback')
        self.assertEqual(h.inspect(h.n.name), original)
        self.assertFalse(h.inspect(result['candidate_id'])['State']['Running'])
        self.assertFalse(h.inspect(result['failed_id'])['State']['Running'])
        self.assertIn('-normalize-failed-', h.inspect(result['failed_id'])['Name'])
        self.assertNotIn('secret-must-not-leak', json.dumps(result))
        self.assertFalse(any(e[0] == 'rm' for e in h.events))
        self.assertEqual(result['http'], {'live': 200, 'ready_primary': 503})

    def test_cli_requires_explicit_apply_and_suppresses_secret_errors(self):
        import io
        from unittest.mock import mock_open
        m = load('normalize_manual_runtime')
        self.assertTrue(callable(getattr(m, 'main', None)), 'safe stdin CLI required')
        request, _ = approval()
        for argv, expected_apply in (([], False), (['--dry-run'], False), (['--apply'], True)):
            with self.subTest(argv=argv), patch('sys.stdin', io.StringIO(json.dumps(request))), \
                    patch('sys.stdout', new_callable=io.StringIO) as out, \
                    patch.object(m.Normalizer, 'normalize', return_value={'status': 'normalized' if expected_apply else 'validated'}) as normalize, \
                    patch('builtins.open', mock_open()) as opened, patch.object(m.contract.fcntl, 'flock') as flock:
                self.assertEqual(m.main(argv), 0)
                self.assertEqual(normalize.call_args.kwargs['apply'], expected_apply)
                self.assertNotIn('STELLA_OWNER_ID', out.getvalue())
                self.assertEqual(opened.call_count, 1 if expected_apply else 0)
                self.assertEqual(flock.call_count, 1 if expected_apply else 0)
        with patch('sys.stdin', io.StringIO(json.dumps(request))), patch('sys.stdout', new_callable=io.StringIO) as out, \
                patch.object(m.Normalizer, 'normalize', side_effect=ValueError('password-secret-marker')):
            self.assertEqual(m.main([]), 1)
            self.assertEqual(json.loads(out.getvalue())['status'], 'blocked')
            self.assertNotIn('password-secret-marker', out.getvalue())

    def test_target_refuses_other_host_or_config_drift_instead_of_losing_settings(self):
        m = load('normalize_manual_runtime')
        for section, field, value in (('HostConfig', 'PidsLimit', 99), ('HostConfig', 'LogConfig', {'Type': 'none'}),
                                      ('Config', 'User', 'unapproved-user'), ('Config', 'Healthcheck', {'Test': ['NONE']})):
            with self.subTest(section=section, field=field):
                h = Harness(m)
                original_command = h.command
                def command(args, *a, **kw):
                    result = original_command(args, *a, **kw)
                    if args[1] == 'create':
                        h.inspect(result)[section][field] = value
                    return result
                h.command = command
                result = h.run(apply=True)
                self.assertEqual(result['status'], 'blocked')
                self.assertTrue(h.inspect(OLD_ID)['State']['Running'])
                self.assertFalse(any(e[0] == 'stop' and e[-1] == OLD_ID for e in h.events))

    def test_action_failures_before_and_after_side_effect_restore_exact_old(self):
        m = load('normalize_manual_runtime')
        for target in ('candidate-create', 'candidate-start', 'stop-old', 'rename-old', 'stable-create', 'stable-start', 'candidate-stop'):
            for after in (False, True):
                with self.subTest(target=target, after=after):
                    h = Harness(m)
                    original = copy.deepcopy(h.inspect(OLD_ID))
                    original_command = h.command
                    fired = False
                    def command(args, *a, **kw):
                        nonlocal fired
                        op = args[1]
                        name = args[args.index('--name') + 1] if op == 'create' else ''
                        matching = ((target == 'candidate-create' and op == 'create' and name != h.n.name)
                                    or (target == 'stable-create' and op == 'create' and name == h.n.name)
                                    or (target == 'stop-old' and op == 'stop' and args[-1] == OLD_ID)
                                    or (target == 'rename-old' and op == 'rename' and args[-2] == OLD_ID)
                                    or (target == 'candidate-start' and op == 'start' and args[-1] == '5' * 64)
                                    or (target == 'stable-start' and op == 'start' and args[-1] == '6' * 64)
                                    or (target == 'candidate-stop' and op == 'stop' and args[-1] == '5' * 64))
                        if matching and not fired:
                            fired = True
                            if after:
                                original_command(args, *a, **kw)
                            raise TimeoutError('uncertain Docker outcome with secret-marker')
                        return original_command(args, *a, **kw)
                    h.command = command
                    result = h.run(apply=True)
                    self.assertTrue(fired)
                    self.assertNotIn('secret-marker', json.dumps(result))
                    if target == 'stable-create' and after:
                        self.assertEqual(result['status'], 'blocked')
                        self.assertIn('manual recovery', result['reason'])
                        self.assertEqual(len(h.containers), 3)
                        self.assertFalse(h.inspect(OLD_ID)['State']['Running'])
                    else:
                        self.assertEqual(h.inspect(h.n.name), original)
                        self.assertIn(result['status'], ('blocked', 'rolledback'))
                    self.assertFalse(any(e[0] == 'rm' for e in h.events))
                    self.assertTrue(all(e[-1] != PG_ID for e in h.mutations()))


    def test_candidate_health_failure_never_stops_old_and_retains_candidate(self):
        m = load('normalize_manual_runtime')
        h = Harness(m)
        original = copy.deepcopy(h.inspect(OLD_ID))
        def health(name, port, expected=True):
            if port == 25132:
                raise ValueError('candidate unhealthy')
            return h.probe(name, port, expected)
        h.n.health = health
        result = h.run(apply=True)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(h.inspect(h.n.name), original)
        self.assertFalse(any(e[0] == 'stop' and e[-1] == OLD_ID for e in h.events))
        self.assertEqual(len(h.containers), 2)
        self.assertFalse(h.inspect(result['candidate_id'])['State']['Running'])


    def test_old_snapshot_drift_is_rejected_without_mutation(self):
        m = load('normalize_manual_runtime')
        changes = (('Id', None, '7' * 64), ('Image', None, 'sha256:' + '7' * 64),
                   ('Config', 'Env', ['PGOPTIONS=-c statement_timeout=30000']),
                   ('Config', 'WorkingDir', '/other'), ('HostConfig', 'NetworkMode', 'bridge'),
                   ('HostConfig', 'Memory', 1), ('Mounts', None, []))
        for section, field, value in changes:
            with self.subTest(section=section, field=field):
                h = Harness(m)
                old = h.inspect(OLD_ID)
                if field:
                    old[section][field] = value
                else:
                    old[section] = value
                with self.assertRaisesRegex(ValueError, 'snapshot'):
                    h.run(apply=True)
                self.assertEqual(h.mutations(), [])


    def test_independently_approved_unsafe_snapshot_is_still_rejected(self):
        m = load('normalize_manual_runtime')
        for section, field, value in (('HostConfig', 'Privileged', True), ('HostConfig', 'CapAdd', ['SYS_ADMIN']),
                                      ('HostConfig', 'Devices', [{'PathOnHost': '/dev/sda'}]),
                                      ('HostConfig', 'NetworkMode', 'bridge'), ('Config', 'WorkingDir', '/other')):
            with self.subTest(section=section, field=field):
                request, _ = approval()
                request['approved_old'][section][field] = value
                h = Harness(m, request)
                h.inspect(OLD_ID)[section][field] = value
                with self.assertRaises(ValueError):
                    h.run(apply=True)
                self.assertEqual(h.mutations(), [])


    def test_approval_rejects_short_ids_or_changed_owner_or_golden_resources(self):
        m = load('normalize_manual_runtime')
        requests = []
        for field, value in (('Id', OLD_ID[:12]), ('Image', IMAGE_ID[:16])):
            request, _ = approval()
            request['approved_old'][field] = value
            requests.append(request)
        request, _ = approval()
        request['approved_pg_id'] = PG_ID[:12]
        requests.append(request)
        request, _ = approval()
        for cfg in request['inventory']['nodes'].values():
            cfg['application_env_overrides']['STELLA_OWNER_ID'] = '22222222-2222-4222-8222-222222222222'
        requests.append(request)
        request, _ = approval()
        request['inventory']['nodes']['nas']['memory'] = 1
        requests.append(request)
        request, _ = approval()
        request['expected_roles']['nas'] = True
        requests.append(request)
        for request in requests:
            with self.subTest(request=request['approved_old']['Id']):
                with self.assertRaises(ValueError):
                    m.Normalizer(request)


    def test_same_daemon_image_content_drift_blocks_preflight(self):
        m = load('normalize_manual_runtime')
        for field, value in (('Id', 'sha256:' + '8' * 64), ('RootFS', {'Layers': ['different']}),
                              ('Config', {'WorkingDir': '/different'})):
            with self.subTest(field=field):
                h = Harness(m)
                original_command = h.command
                def command(args, *a, **kw):
                    if args[1:3] == ['image', 'inspect']:
                        info = copy.deepcopy(h.request['approved_image'])
                        info[field] = value
                        return json.dumps([info])
                    return original_command(args, *a, **kw)
                h.command = command
                with self.assertRaisesRegex(ValueError, 'image content'):
                    h.run(apply=True)
                self.assertEqual(h.mutations(), [])


    def test_role_drift_after_healthy_candidate_blocks_cutover(self):
        m = load('normalize_manual_runtime')
        h = Harness(m)
        original_probe = h.probe
        drift = False
        def probe(name=None, port=25131, expected=True):
            if drift and expected:
                raise ValueError('PROBE expected_roles mismatch')
            return original_probe(name, port, expected)
        def health(name, port, expected=True):
            nonlocal drift
            result = original_probe(name, port, expected)
            if port == 25132:
                drift = True
            return result
        h.n.probe, h.n.health = probe, health
        result = h.run(apply=True)
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(h.inspect(OLD_ID)['State']['Running'])
        self.assertFalse(any(e[0] == 'stop' and e[-1] == OLD_ID for e in h.events))


    def test_pg_identity_drift_blocks_cutover_without_pg_actions(self):
        m = load('normalize_manual_runtime')
        h = Harness(m)
        changed = False
        def health(name, port, expected=True):
            nonlocal changed
            result = h.probe(name, port, expected)
            if port == 25132:
                changed = True
            return result
        h.n.health = health
        h.n.pg_guard = lambda: '9' * 64 if changed else PG_ID
        result = h.run(apply=True)
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('manual recovery', result['reason'])
        self.assertTrue(h.inspect(OLD_ID)['State']['Running'])
        self.assertFalse(any(e[0] == 'stop' and e[-1] == OLD_ID for e in h.events))
        self.assertTrue(all(e[-1] != PG_ID for e in h.mutations()))


    def test_rollback_refuses_old_env_mutation_and_failed_recovery_commands(self):
        m = load('normalize_manual_runtime')
        for failure in ('old-env', 'old-start', 'stable-stop', 'old-health'):
            with self.subTest(failure=failure):
                h = Harness(m)
                original_command = h.command
                def health(name, port, expected=True):
                    if name == h.n.name and (h.inspect(name)['Id'] != OLD_ID or failure == 'old-health'):
                        raise ValueError('unhealthy')
                    return h.probe(name, port, expected)
                h.n.health = health
                def command(args, *a, **kw):
                    if failure == 'old-start' and args[1:] == ['start', OLD_ID]:
                        raise TimeoutError('restart failed')
                    if failure == 'stable-stop' and args[1] == 'stop' and args[-1] == '6' * 64:
                        raise TimeoutError('stop failed')
                    result = original_command(args, *a, **kw)
                    if failure == 'old-env' and args[1:] == ['start', OLD_ID]:
                        h.inspect(OLD_ID)['Config']['Env'].append('STELLA_COOKIE_SECURE=false')
                    return result
                h.command = command
                result = h.run(apply=True)
                self.assertEqual(result['status'], 'blocked')
                self.assertIn('manual recovery', result['reason'])
                self.assertEqual(len(h.containers), 3)
                self.assertFalse(any(e[0] == 'rm' for e in h.events))


    def test_candidate_and_stable_probes_use_existing_strict_read_only_probe(self):
        m = load('normalize_manual_runtime')
        request, _ = approval()
        n = m.Normalizer(request)
        n.target_names = {'candidate', n.name}
        with patch.object(m.contract, 'run', return_value='{}') as run:
            for name, port in (('candidate', 25132), (n.name, 25131)):
                n.probe(name, port)
                argv, stdin = run.call_args.args
                payload = json.loads(stdin)
                self.assertTrue(payload['target'])
                self.assertEqual(payload['expected_roles'], ROLES)
                self.assertEqual(payload['manifest'], request['inventory']['manifest_sha256'])
                self.assertEqual(payload['receipt_dir'], '/app/data/backup-receipts')
                self.assertEqual(argv[-1], m.contract.PROBE)
                self.assertIn('/primary', argv[-1])
                self.assertIn('pg_is_in_recovery', argv[-1])
                self.assertIn("cur.execute('SELECT version_num FROM alembic_version')", argv[-1])
                self.assertNotIn('ALTER ', argv[-1])

    def test_expected_docker_reference_and_swap_defaults_do_not_block_exact_image_repair(self):
        m = load('normalize_manual_runtime')
        request, _ = approval()
        request['approved_old']['Config']['Image'] = 'operator-approved-manual-tag'
        request['approved_old']['HostConfig']['MemorySwap'] = 0
        h = Harness(m, request)
        h.inspect(OLD_ID)['Config']['Image'] = 'operator-approved-manual-tag'
        h.inspect(OLD_ID)['HostConfig']['MemorySwap'] = 0
        original_command = h.command
        def command(args, *a, **kw):
            result = original_command(args, *a, **kw)
            if args[1] == 'create':
                h.inspect(result)['Config']['Image'] = IMAGE_ID
                h.inspect(result)['HostConfig']['MemorySwap'] = 2147483648
            return result
        h.command = command
        result = h.run(apply=True)
        self.assertEqual(result['status'], 'normalized')
        self.assertEqual(h.inspect(h.n.name)['Image'], IMAGE_ID)
        self.assertEqual(h.inspect(h.n.name)['HostConfig']['MemorySwap'], 2147483648)

    def test_untrusted_create_return_id_is_never_used_for_app_or_pg_mutations(self):
        m = load('normalize_manual_runtime')
        for returned in (OLD_ID, PG_ID, 'short-id'):
            with self.subTest(returned=returned):
                h = Harness(m)
                original_command = h.command
                def command(args, *a, **kw):
                    result = original_command(args, *a, **kw)
                    return returned if args[1] == 'create' else result
                h.command = command
                result = h.run(apply=True)
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(h.mutations(), [e for e in h.mutations() if e[0] == 'create'])
                self.assertIsNone(result['candidate_id'])

    def test_candidate_unapproved_env_is_rejected_before_start(self):
        m = load('normalize_manual_runtime')
        h = Harness(m)
        original_command = h.command
        def command(args, *a, **kw):
            result = original_command(args, *a, **kw)
            if args[1] == 'create':
                h.inspect(result)['Config']['Env'].append('PYTHONPATH=/unapproved')
            return result
        h.command = command
        result = h.run(apply=True)
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(any(e[0] == 'start' for e in h.mutations()))

    def test_lock_busy_blocks_apply_and_pack_validation_never_reads_stdin_or_docker(self):
        import io
        from unittest.mock import mock_open
        m = load('normalize_manual_runtime')
        request, _ = approval()
        with patch('sys.stdin', io.StringIO(json.dumps(request))), patch('sys.stdout', new_callable=io.StringIO) as out, \
                patch('builtins.open', mock_open()), patch.object(m.contract.fcntl, 'flock', side_effect=BlockingIOError()), \
                patch.object(m.Normalizer, 'normalize') as normalize:
            self.assertEqual(m.main(['--apply']), 1)
            normalize.assert_not_called()
            self.assertEqual(json.loads(out.getvalue())['status'], 'blocked')
        with patch('sys.stdin', new=object()), patch('sys.stdout', new_callable=io.StringIO) as out, \
                patch.object(m.contract, 'run', side_effect=AssertionError('no Docker allowed')):
            self.assertEqual(m.main(['--validate-pack']), 0)
            self.assertFalse(json.loads(out.getvalue())['production_executed'])


    def test_existing_candidate_name_collision_never_sweeps_unknown_container(self):
        from types import SimpleNamespace
        m = load('normalize_manual_runtime')
        h = Harness(m)
        stranger = copy.deepcopy(h.inspect(OLD_ID))
        stranger.update(Id='a' * 64, Name='/' + h.n.name + '-normalize-candidate-fixedsuffix')
        h.containers[stranger['Id']] = stranger
        with patch.object(m.contract.uuid, 'uuid4', return_value=SimpleNamespace(hex='fixedsuffix')):
            result = h.run(apply=True)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(h.inspect(stranger['Id']), stranger)
        self.assertEqual(h.mutations(), [e for e in h.mutations() if e[0] == 'create'])


    def test_role_drift_after_stop_restores_old_with_actual_role_readback(self):
        m = load('normalize_manual_runtime')
        h = Harness(m)
        original_command = h.command
        drift = False
        def command(args, *a, **kw):
            nonlocal drift
            result = original_command(args, *a, **kw)
            if args[1] == 'stop' and args[-1] == OLD_ID:
                drift = True
            return result
        def probe(name=None, port=25131, expected=True):
            if drift and expected:
                raise ValueError('expected roles changed')
            result = h.probe(name, port, expected)
            if drift:
                result['roles'] = {'nyarch': False, 'nas': True}
                result['http']['ready_primary'] = 200
            return result
        h.command = command
        h.n.probe = probe
        h.n.health = lambda name, port, expected=True: probe(name, port, expected)
        result = h.run(apply=True)
        self.assertEqual(result['status'], 'rolledback')
        self.assertEqual(result['rollback_roles'], {'nyarch': False, 'nas': True})
        self.assertEqual(h.inspect(h.n.name)['Id'], OLD_ID)
        self.assertTrue(h.inspect(OLD_ID)['State']['Running'])

    def test_unconfirmed_create_outcome_is_explicitly_blocked_even_if_old_is_healthy(self):
        m = load('normalize_manual_runtime')
        for stable in (False, True):
            with self.subTest(stable=stable):
                h = Harness(m)
                original_command = h.command
                def command(args, *a, **kw):
                    if args[1] == 'create':
                        name = args[args.index('--name') + 1]
                        if (name == h.n.name) == stable:
                            raise TimeoutError('create result unknown')
                    return original_command(args, *a, **kw)
                h.command = command
                result = h.run(apply=True)
                self.assertEqual(result['status'], 'blocked')
                self.assertTrue(result.get('outcome_unknown'), 'unknown create result must be reported')
                self.assertEqual(h.inspect(h.n.name)['Id'], OLD_ID)
                self.assertTrue(h.inspect(OLD_ID)['State']['Running'])


if __name__ == '__main__':
    unittest.main()
