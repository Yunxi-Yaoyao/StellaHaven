"""Exact entry/backup environment approval; fixtures only, never live state."""
import copy
import json
import unittest
from unittest.mock import patch
from test_production_release import ROOT, load
from test_production_upgrade_contract import container, inventory, overrides, release_simulation


PRIVATE = 'https://stella.p.xiya.live'
BACKUP = '/var/cache/stella/backups'


def registry(main='https://stella.xiya.live') -> list[dict[str, object]]:
    return [
        {'service_id': 'stella', 'public': main, 'private': PRIVATE},
        {'service_id': 'web-project-runtime', 'public': 'https://pages.xiya.live', 'private': 'https://pages.p.xiya.live'},
        {'service_id': 'gallery', 'public': 'https://immich.xiya.live', 'private': 'https://immich.p.xiya.live'},
    ]


def overlay(rows=None, main='https://stella.xiya.live'):
    return dict(overrides(), STELLA_MAIN_ORIGIN=main,
                STELLA_TRUSTED_ORIGINS=overrides()['STELLA_TRUSTED_ORIGINS'] + ',' + PRIVATE,
                STELLA_ENTRY_REGISTRY=json.dumps(registry(main) if rows is None else rows, separators=(',', ':')),
                STELLA_BACKUP_DIRECTORY=BACKUP)


def extended_inventory(env=None):
    inv = inventory()
    for cfg in inv['nodes'].values():
        cfg['application_env_overrides'] = copy.deepcopy(overlay() if env is None else env)
        cfg['mounts'].append({'Source': load('node_production').BASE + 'cache',
                              'Destination': '/var/cache/stella', 'RW': True})
    return inv


class EntryOverlayTests(unittest.TestCase):
    def assert_rejected(self, env):
        node = load('node_production')
        release = load('production_release')
        with patch.object(node, 'run', side_effect=AssertionError('unexpected external command')):
            with self.assertRaises(ValueError):
                node.validate_application_env_overrides(env)
            with self.assertRaises(ValueError):
                node.Node(dict(node='nas', inventory=extended_inventory(env), op='release'))
        with self.assertRaises(ValueError):
            release.validate_inventory(extended_inventory(env))

    def test_legacy_six_fields_keep_exact_contract_without_cache_mount(self):
        node = load('node_production')
        self.assertEqual(node.APPLICATION_ENV_KEYS, frozenset(overrides()))
        self.assertIs(node.validate_application_env_overrides(overrides()).__class__, dict)
        for main in ('https://stella.xiya.live', 'https://stella.yunxi.life'):
            inv = inventory()
            for cfg in inv['nodes'].values():
                cfg['application_env_overrides']['STELLA_MAIN_ORIGIN'] = main
            self.assertEqual(load('production_release').validate_inventory(inv), inv)
            node.Node(dict(node='nas', inventory=inv, op='release'))
        old_private = dict(overrides(), STELLA_TRUSTED_ORIGINS=overlay()['STELLA_TRUSTED_ORIGINS'])
        self.assert_rejected(old_private)

    def test_complete_eight_field_overlay_passes_both_boundaries_unchanged(self):
        node = load('node_production')
        release = load('production_release')
        for main in ('https://stella.xiya.live', 'https://stella.yunxi.life'):
            with self.subTest(main=main):
                env = overlay(main=main)
                original = copy.deepcopy(env)
                self.assertIs(node.validate_application_env_overrides(env), env)
                self.assertEqual(env, original)
                inv = extended_inventory(env)
                self.assertEqual(release.validate_inventory(inv), inv)
                self.assertEqual(release.validate_release_approval(inv), inv)
                with patch.object(node, 'run', side_effect=AssertionError('external command')), \
                        patch.object(node.Path, 'mkdir', side_effect=AssertionError('must not create backup directory')):
                    node.Node(dict(node='nas', inventory=inv, op='release'))
                self.assertNotIn('https://pages.p.xiya.live', env['STELLA_TRUSTED_ORIGINS'])
                self.assertNotIn('https://immich.p.xiya.live', env['STELLA_TRUSTED_ORIGINS'])

    def test_owned_module_records_use_exact_stable_id_and_optional_private(self):
        node = load('node_production')
        rows = registry()
        for sid in ('module-1', 'a' * 32, 'x' * 59):
            rows.append(dict(service_id=sid, public='https://app-' + sid + '.xiya.live',
                             private='https://app-' + sid + '.p.xiya.live'))
        rows.append(dict(service_id='public-only', public='https://app-public-only.xiya.live'))
        env = overlay(rows)
        self.assertEqual(node.validate_application_env_overrides(env), env)
        # A registry need not pretend a missing module has a private counterpart.
        self.assertEqual(node.validate_application_env_overrides(overlay(registry()[:1])), overlay(registry()[:1]))

    def test_partial_or_unknown_environment_sets_are_not_an_extension(self):
        for key in ('STELLA_ENTRY_REGISTRY', 'STELLA_BACKUP_DIRECTORY'):
            env = overlay()
            del env[key]
            with self.subTest(missing=key):
                self.assert_rejected(env)
        for key in ('POSTGRES_HOST', 'POSTGRES_PASSWORD', 'PGOPTIONS', 'DATABASE_URL', 'STELLA_SECRET_KEY',
                    'STELLA_OIDC_PRIVATE_KEY', 'PYTHONPATH', 'LD_PRELOAD', 'ARBITRARY'):
            with self.subTest(extra=key):
                self.assert_rejected(dict(overlay(), **{key: 'synthetic-private-marker'}))

    def test_private_trust_requires_registered_main_pair_and_public_main(self):
        for origins in (overrides()['STELLA_TRUSTED_ORIGINS'],
                        overlay()['STELLA_TRUSTED_ORIGINS'] + ',' + PRIVATE,
                        overlay()['STELLA_TRUSTED_ORIGINS'] + ',https://other.p.xiya.live',
                        overlay()['STELLA_TRUSTED_ORIGINS'] + ',https://pages.xiya.live',
                        overlay()['STELLA_TRUSTED_ORIGINS'] + ',https://immich.p.xiya.live',
                        overlay()['STELLA_TRUSTED_ORIGINS'].replace('http://127.0.0.1:25132,', ''),
                        overlay()['STELLA_TRUSTED_ORIGINS'] + ',https://external-api.example',
                        overlay()['STELLA_TRUSTED_ORIGINS'] + ',http://10.66.0.2:25131'):
            with self.subTest(origins=origins):
                self.assert_rejected(dict(overlay(), STELLA_TRUSTED_ORIGINS=origins))
        self.assert_rejected(dict(overlay(), STELLA_MAIN_ORIGIN=PRIVATE))
        self.assert_rejected(overlay(registry('https://stella.yunxi.life')))
        self.assert_rejected(overlay(registry()[1:]))
        rows = registry()
        del rows[0]['private']
        self.assert_rejected(overlay(rows))

    def test_registry_is_a_strict_array_of_exact_records_with_unique_json_members(self):
        for raw in ('{}', 'null', 'false', '[]', '[1]', '[null]', '["stella"]', '{',
                    '[{"service_id":"other","service_id":"stella","public":"https://stella.xiya.live","private":"https://stella.p.xiya.live"}]'):
            with self.subTest(raw=raw):
                self.assert_rejected(dict(overlay(), STELLA_ENTRY_REGISTRY=raw))
        for row in ({}, {'service_id': 'x'}, {'public': 'https://pages.xiya.live'},
                    dict(registry()[1], extra='not-approved'), dict(registry()[1], private=None)):
            with self.subTest(row=row):
                self.assert_rejected(overlay([registry()[0], row]))
        for sid in ('', 'a' * 65, 'space id', 'a/b', 1, None, 'bad_id', 'BadID', 'a' * 60, 'trailing-'):
            rows = registry()
            rows.append(dict(service_id=sid, public='https://app-' + str(sid) + '.xiya.live'))
            with self.subTest(sid=sid):
                self.assert_rejected(overlay(rows))

    def test_duplicate_ids_or_origins_and_lane_confusion_fail_closed(self):
        cases = [registry() + [registry()[0]],
                 registry() + [dict(service_id='different', public=registry()[1]['public'])]]
        for index in range(3):
            rows = registry()
            rows[index]['private'] = rows[index]['public']
            cases.append(rows)
            rows = registry()
            rows[index]['public'], rows[index]['private'] = rows[index]['private'], rows[index]['public']
            cases.append(rows)
        rows = registry()
        rows[1]['private'] = rows[2]['private']
        cases.append(rows)
        for rows in cases:
            with self.subTest(rows=rows):
                self.assert_rejected(overlay(rows))

    def test_registry_origins_are_canonical_exact_owned_https_pairs(self):
        bad_origins = ('http://pages.xiya.live', 'https://pages.xiya.live/', 'https://pages.xiya.live/path',
                       'https://pages.xiya.live?x=1', 'https://pages.xiya.live#fragment',
                       'https://user:pass@pages.xiya.live', 'https://pages.xiya.live:443',
                       'https://pages.xiya.live:444', 'https://PAGES.xiya.live', 'https://pages.xiya.live.',
                       'https://*.xiya.live', 'https://pages.xiya.live.evil.example',
                       'https://external-api.example', 'https://127.0.0.1', ' https://pages.xiya.live',
                       'https://pages.xiya.live\nINJECTED=value')
        for bad in bad_origins:
            rows = registry()
            rows[1]['public'] = bad
            with self.subTest(origin=bad):
                self.assert_rejected(overlay(rows))
        for index in (1, 2):
            rows = registry()
            del rows[index]['private']
            with self.subTest(missing_private=index):
                self.assert_rejected(overlay(rows))
        for row in (dict(service_id='module-1', public='https://app-module-2.xiya.live'),
                    dict(service_id='module-1', public='https://app-module-1.xiya.live', private='https://app-module-2.p.xiya.live'),
                    dict(service_id='module-1', public='https://module-1.xiya.live', private='https://module-1.p.xiya.live')):
            self.assert_rejected(overlay(registry() + [row]))

    def test_backup_environment_accepts_only_the_fixed_persistent_default(self):
        for value in ('/tmp/backups', '/scratch/backups', '/var/cache/stella/blobs', '/app/data/backups',
                      '/data/backups', '/root/.credentials/backups', '/var/lib/postgresql/data',
                      '/var/cache/stella/backups/', '/var/cache/stella/../backups', '', None,
                      '/var/cache/stella/backups\nPGOPTIONS=unsafe'):
            with self.subTest(value=value):
                self.assert_rejected(dict(overlay(), STELLA_BACKUP_DIRECTORY=value))

    def test_extended_environment_retains_owner_cookie_receipt_agent_guards(self):
        for key, bad in (('STELLA_OWNER_ID', '00000000-0000-0000-0000-000000000000'),
                         ('STELLA_COOKIE_SECURE', 'false'), ('STELLA_BACKUP_RECEIPT_DIR', BACKUP),
                         ('STELLA_AGENT_ROLLOUT_VERSION', '0.6.16')):
            with self.subTest(key=key):
                self.assert_rejected(dict(overlay(), **{key: bad}))


class BackupMountTests(unittest.TestCase):
    def test_extended_backup_requires_existing_exact_rw_cache_mount(self):
        node = load('node_production')
        release = load('production_release')
        # Never auto-add a mount or accept scratch/PGDATA as the backup source.
        bad_caches = [None,
                      {'Source': node.BASE + 'cache', 'Destination': '/var/cache/stella', 'RW': False},
                      {'Source': node.BASE + 'cache', 'Destination': '/var/cache/stella', 'RW': 1},
                      {'Source': node.BASE + 'scratch', 'Destination': '/var/cache/stella', 'RW': True},
                      {'Source': node.BASE + 'cache/blobs', 'Destination': '/var/cache/stella', 'RW': True},
                      {'Source': node.BASE + 'cache/../scratch', 'Destination': '/var/cache/stella', 'RW': True},
                      {'Source': '/var/lib/stella-ha-runtime/nas/pgdata', 'Destination': '/var/cache/stella', 'RW': True}]
        for cache in bad_caches:
            inv = extended_inventory()
            cfg = inv['nodes']['nas']
            cfg['mounts'] = [m for m in cfg['mounts'] if m['Destination'] != '/var/cache/stella']
            if cache is not None:
                cfg['mounts'].append(cache)
            with self.subTest(cache=cache), patch.object(node, 'run', side_effect=AssertionError('external command')), \
                    patch.object(node.Path, 'mkdir', side_effect=AssertionError('no directory creation')):
                with self.assertRaisesRegex(ValueError, 'backup'):
                    node.Node(dict(node='nas', inventory=inv, op='release'))
                with self.assertRaisesRegex(ValueError, 'backup'):
                    release.validate_inventory(inv)
        inv = extended_inventory()
        inv['nodes']['nas']['mounts'].append(copy.deepcopy(inv['nodes']['nas']['mounts'][-1]))
        with self.assertRaisesRegex(ValueError, 'backup'):
            node.Node(dict(node='nas', inventory=inv, op='release'))

    def test_constructor_rechecks_backup_mount_before_docker_create(self):
        node = load('node_production')
        n = node.Node(dict(node='nas', inventory=extended_inventory(), op='release'))
        n.cfg['mounts'] = [m for m in n.cfg['mounts'] if m['Destination'] != '/var/cache/stella']
        old = {'Config': {'Env': ['PGOPTIONS=-c statement_timeout=30000']},
               'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped'}}}
        with patch.object(node, 'port_free'), patch.object(node, 'validate_receipt_bundle'), \
                patch.object(node, 'run', return_value='must-not-be-created') as run:
            with self.assertRaisesRegex(ValueError, 'backup'):
                n.create(old, 'fixture-candidate', 'sha256:' + 'd' * 64, 25132)
            run.assert_not_called()


class OverlayConstructionTests(unittest.TestCase):
    def test_candidate_and_stable_merge_exact_overlay_via_stdin_without_new_mounts(self):
        node = load('node_production')
        n = node.Node(dict(node='nas', inventory=extended_inventory(), op='release'))
        old = container(node)
        old['Mounts'].append(dict(n.cfg['mounts'][-1], Type='bind', Propagation='rprivate'))
        old['Config']['Env'] += [k + '=' + v for k, v in overrides().items()]
        original = copy.deepcopy(old)
        for port in (25131, 25132):
            with self.subTest(port=port), patch.object(node, 'port_free'), patch.object(node, 'validate_receipt_bundle') as receipts, \
                    patch.object(node.Path, 'mkdir', side_effect=AssertionError('backup default is read-only until manual operation')), \
                    patch.object(node, 'run', return_value='created-fixture-id') as run:
                n.create(old, 'fixture-name', 'sha256:' + 'd' * 64, port)
                args, data = run.call_args.args
                env = dict(row.split('=', 1) for row in data.splitlines())
                self.assertEqual(env, dict((row.split('=', 1) for row in original['Config']['Env']), **overlay()))
                self.assertEqual(env['PGOPTIONS'], '-c statement_timeout=30000')
                self.assertEqual(len(data.splitlines()), len(env))
                self.assertIn('--env-file', args)
                self.assertIn('/dev/stdin', args)
                self.assertNotIn(overlay()['STELLA_ENTRY_REGISTRY'], ' '.join(args))
                self.assertNotIn('STELLA_OWNER_ID=', ' '.join(args))
                mounts = [args[index + 1] for index, arg in enumerate(args) if arg == '--mount']
                expected = ['type=bind,src=' + m['Source'] + ',dst=' + m['Destination'] +
                            (',readonly' if not m['RW'] else '') for m in n.cfg['mounts']]
                self.assertEqual(mounts, expected)
                self.assertIn('--restart=' + ('unless-stopped' if port == 25131 else 'no'), args)
                self.assertEqual(args[-3:], ['-c', node.START, str(port)])
                receipts.assert_called_once_with(n.cfg['mounts'])
                self.assertEqual(old, original)

    def test_initial_legacy_env_allowed_but_targets_and_actual_mounts_remain_strict(self):
        node = load('node_production')
        n = node.Node(dict(node='nas', inventory=extended_inventory(), op='probe'))
        old = container(node)
        old['Mounts'].append(dict(n.cfg['mounts'][-1], Type='bind', Propagation='rprivate'))
        old['Config']['Env'] += [k + '=' + v for k, v in overrides().items()]
        with patch.object(node, 'validate_receipt_bundle'), patch.object(node.Path, 'read_bytes', return_value=b'fixture'), \
                patch.object(node.hashlib, 'sha256') as sha:
            sha.return_value.hexdigest.return_value = 'c' * 64
            n.validate(old)  # initial/rollback carriers need not have the new env
            with self.assertRaisesRegex(ValueError, 'approved application'):
                n.validate(old, approved_environment=True)
            for port in (25131, 25132):
                target = copy.deepcopy(old)
                target['Name'] = '/fixture-target'
                target['Config']['Cmd'] = ['-c', node.START, str(port)]
                base = {row.split('=', 1)[0]: row.split('=', 1)[1] for row in old['Config']['Env']}
                base.update(overlay())
                target['Config']['Env'] = [k + '=' + v for k, v in base.items()]
                n.validate(target, 'fixture-target', port, True, approved_environment=True)
                for key in ('STELLA_ENTRY_REGISTRY', 'STELLA_BACKUP_DIRECTORY'):
                    missing = copy.deepcopy(target)
                    missing['Config']['Env'] = [row for row in missing['Config']['Env'] if not row.startswith(key + '=')]
                    with self.subTest(port=port, missing=key), self.assertRaisesRegex(ValueError, 'approved application'):
                        n.validate(missing, 'fixture-target', port, True, approved_environment=True)
                for source, rw in ((n.cfg['mounts'][-1]['Source'], False), (node.BASE + 'scratch', True)):
                    unsafe = copy.deepcopy(target)
                    unsafe['Mounts'][-1].update(Source=source, RW=rw)
                    with self.subTest(port=port, source=source, rw=rw), self.assertRaisesRegex(ValueError, 'exact mount'):
                        n.validate(unsafe, 'fixture-target', port, True, approved_environment=True)
                for secret in ('STELLA_SECRET_KEY', 'PGHOST', 'DATABASE_URL'):
                    unsafe = copy.deepcopy(target)
                    unsafe['Config']['Env'].append(secret + '=synthetic-private-marker')
                    with self.subTest(secret=secret), self.assertRaises(ValueError):
                        n.validate(unsafe, 'fixture-target', port, True, approved_environment=True)

    def test_same_image_overlay_redeploy_and_exact_old_rollback_remain_ordinary(self):
        node = load('node_production')
        for fail in (False, True):
            with self.subTest(fail=fail):
                n = release_simulation(node, fail_stable=fail, old_current=True)
                for cfg in n.inv['nodes'].values():
                    cfg['application_env_overrides'] = overlay()
                    cfg['mounts'].append(dict(Source=node.BASE + 'cache', Destination='/var/cache/stella', RW=True))
                old = n.inspect(n.name)
                old['Mounts'].append(dict(n.cfg['mounts'][-1], Type='bind', Propagation='rprivate'))
                original = copy.deepcopy(old)
                command = n.command
                def fixture_command(args, *a, **kw):
                    result = command(args, *a, **kw)
                    if args[1] == 'create':
                        n.inspect(result)['Mounts'].append(dict(n.cfg['mounts'][-1], Type='bind', Propagation='rprivate'))
                    return result
                with patch.object(node, 'port_free'), patch.object(node, 'validate_receipt_bundle'), \
                        patch.object(node, 'run', side_effect=fixture_command), \
                        patch.object(node.Path, 'read_bytes', return_value=b'fixture'), patch.object(node.hashlib, 'sha256') as sha:
                    sha.return_value.hexdigest.return_value = 'c' * 64
                    result = n.release()  # all Docker/HTTP/PG access is mocked
                    self.assertEqual(result['status'], 'rolledback' if fail else 'deployed')
                    current = n.inspect(n.name)
                    if fail:
                        self.assertEqual(current, original)
                    else:
                        self.assertTrue(n.application_environment_matches(current))
                        self.assertEqual(n.release()['status'], 'unchanged')
                self.assertTrue(n.inspect(n.name)['State']['Running'])

    def test_unchanged_normalizer_accepts_exact_extended_env_in_both_old_shapes(self):
        from test_normalize_manual_runtime import approval
        normalize = load('normalize_manual_runtime')
        for secure_inline in (False, True):
            request, old = approval(secure_inline=secure_inline)
            for cfg in request['inventory']['nodes'].values():
                env = overlay()
                env['STELLA_AGENT_ROLLOUT_VERSION'] = cfg['application_env_overrides']['STELLA_AGENT_ROLLOUT_VERSION']
                cfg['application_env_overrides'] = env
                cfg['mounts'].append(dict(Source=normalize.contract.BASE + 'cache', Destination='/var/cache/stella', RW=True))
            cfg = request['inventory']['nodes']['nas']
            env = dict(row.split('=', 1) for row in old['Config']['Env'])
            env.update(cfg['application_env_overrides'])
            old['Config']['Env'] = [k + '=' + v for k, v in env.items()]
            old['Mounts'].append(dict(cfg['mounts'][-1], Type='bind', Propagation='rprivate'))
            request['approved_old'] = {k: copy.deepcopy(old[k]) for k in normalize.OLD_FIELDS}
            original = copy.deepcopy(old)
            with self.subTest(secure_inline=secure_inline), patch.object(normalize.contract, 'run', side_effect=AssertionError('no external command')), \
                    patch.object(normalize.contract, 'validate_receipt_bundle'), \
                    patch.object(normalize.contract.Path, 'read_bytes', return_value=b'fixture'):
                n = normalize.Normalizer(request)
                self.assertEqual(n.validate_manual(old), old)
                self.assertEqual(old, original)

    def test_noncompatible_schema_approval_is_not_repaired_or_bypassed(self):
        node = load('node_production')
        release = load('production_release')
        for value in (False, None, 'true', 1):
            inv = extended_inventory()
            inv['forward_compatible'] = value
            original = copy.deepcopy(inv)
            with self.subTest(value=value), patch.object(node, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'forward compatibility'):
                    release.validate_inventory(inv)
                with self.assertRaisesRegex(ValueError, 'inventory approval'):
                    node.Node(dict(node='nas', inventory=inv, op='release'))
                run.assert_not_called()
                self.assertEqual(inv, original)

    def test_exact_two_node_overlay_and_agent_rollout_approval_remain_required(self):
        release = load('production_release')
        inv = extended_inventory()
        for cfg in inv['nodes'].values():
            cfg['application_env_overrides']['STELLA_AGENT_ROLLOUT_VERSION'] = '0.6.15'
        release.validate_inventory(inv)
        with self.assertRaisesRegex(ValueError, 'agent rollout'):
            release.validate_release_approval(inv)
        release.validate_release_approval(inv, '0.6.15')
        rows = registry() + [dict(service_id='module-1', public='https://app-module-1.xiya.live')]
        inv['nodes']['nas']['application_env_overrides']['STELLA_ENTRY_REGISTRY'] = overlay(rows)['STELLA_ENTRY_REGISTRY']
        release.validate_inventory(inv)
        with self.assertRaisesRegex(ValueError, 'two-node application'):
            release.validate_release_approval(inv, '0.6.15')


if __name__ == '__main__':
    unittest.main()
