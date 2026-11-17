"""No-DB unified runner: fail closed on admission and incomplete results."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


class UnifiedCI(unittest.TestCase):
    def load(self):
        path = ROOT/'deploy/ci/unified_ci.py'
        self.assertTrue(path.is_file(), 'missing actual unified CI runner')
        spec = importlib.util.spec_from_file_location('unified_ci_contract', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_collector_manifest_covers_all_four_files_and_sixty_one_cases(self):
        import json
        from collections import Counter
        ids = json.loads((ROOT/'deploy/ci/unified-nodeids.json').read_text())
        self.assertEqual(len(ids), 61)
        self.assertEqual(len(set(ids)), 61)
        counts = Counter(node.split('::')[0] for node in ids)
        self.assertEqual(set(counts), {str(p.relative_to(ROOT)) for p in (ROOT/'tests_agent_unified').glob('test_*.py')})
        self.assertEqual(counts['tests_agent_unified/test_refresh_timeout.py'], 30)

    def test_full_main_without_admission_fails_not_skips(self):
        import ast
        source = ROOT/'tests_agent_refresh_timeout/test_full_main.py'
        tree = ast.parse(source.read_text())
        test = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith('test_'))
        # Exercise only the admission preamble, not app/database imports.
        prefix = []
        for statement in test.body:
            if isinstance(statement, ast.FunctionDef) and statement.name == 'guard':
                break
            prefix.append(statement)
        fragment = ast.Module(body=prefix, type_ignores=[])
        from types import SimpleNamespace
        def forbidden_skip(*args):
            raise RuntimeError('missing admission must fail, never skip')
        pytest = SimpleNamespace(skip=forbidden_skip)
        import types
        admission_tree = ast.parse((ROOT/'tests_agent_unified/conftest.py').read_text())
        admission = next(n for n in admission_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'require_os_fixture')
        module = types.ModuleType('tests_agent_unified.conftest')
        namespace = dict(os=os, Path=Path)
        exec(compile(ast.Module(body=[admission], type_ignores=[]), '<real admission>', 'exec'), namespace)
        module.require_os_fixture = namespace['require_os_fixture']
        for env in ({}, {'DATABASE_URL':'postgresql://foreign'},
                    {'NODE_FILES_AUTO_NONCE':'a'*32, 'NODE_FILES_AUTO_RECEIPT':'/no-proof'},
                    {'STELLA_CI_UNIFIED':'1'}, {'UNIFIED_ROOTFS':'1'}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, {'tests_agent_unified.conftest':module}):
                try:
                    exec(compile(ast.fix_missing_locations(fragment), str(source), 'exec'),
                         dict(os=os, Path=Path, pytest=pytest, json=__import__('json'), socket=__import__('socket')))
                except (AssertionError, KeyError, ValueError, FileNotFoundError):
                    pass
                else:
                    self.fail('missing fixture admission was accepted')

    def test_full_main_inventory_is_both_real_collected_parameters(self):
        from deploy.ci.owned_inventory import FULL_MAIN_NODEIDS
        self.assertEqual(FULL_MAIN_NODEIDS, (
            'tests_agent_refresh_timeout/test_full_main.py::test_active_upload_survives_periodic_network_timeout[/agent/files/config]',
            'tests_agent_refresh_timeout/test_full_main.py::test_active_upload_survives_periodic_network_timeout[/agent/identity]',
        ))
        m = self.load()
        good = dict(collected=list(FULL_MAIN_NODEIDS), manual_deselected=[], exit_code=0,
                    results={node:dict(setup='passed', call='passed', teardown='passed') for node in FULL_MAIN_NODEIDS})
        m.check_complete(good, FULL_MAIN_NODEIDS)
        for ids in ([], list(FULL_MAIN_NODEIDS[:1]), list(FULL_MAIN_NODEIDS)*2):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                m.check_complete({**good, 'collected': ids}, FULL_MAIN_NODEIDS)
        for phase in ('setup', 'call', 'teardown'):
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                results = {node:dict(row) for node, row in good['results'].items()}
                results[FULL_MAIN_NODEIDS[0]][phase] = 'skipped'
                m.check_complete({**good, 'results':results}, FULL_MAIN_NODEIDS)

    def test_private_overlay_rejects_host_root_and_nested_mounts(self):
        import runpy
        from types import SimpleNamespace
        with patch.dict(sys.modules):
            sys.path.insert(0, str(ROOT/'deploy/ci'))
            try:
                boundary = runpy.run_path(str(ROOT/'deploy/ci/run-owned-suite.py'))['private_job_root']
            finally:
                sys.path.pop(0)
        status = 'CapEff:\t0000000000000000\nCapBnd:\t0000000000000000\nSeccomp:\t2\n'
        good_mount = '1 0 0:1 / / rw - overlay overlay rw\n'
        def check(mounts=good_mount, dockerenv=True, docker_socket=False, uid=0, caps=status):
            def text(path, *args, **kwargs):
                return caps if str(path) == '/proc/self/status' else mounts
            def exists(path):
                return dockerenv if str(path) == '/.dockerenv' else docker_socket
            with patch('os.geteuid', return_value=uid), patch.object(Path, 'read_text', text), patch.object(Path, 'exists', exists), patch.object(Path, 'lstat', return_value=SimpleNamespace(st_uid=0, st_mode=0o755)), patch.object(Path, 'is_symlink', return_value=False):
                return boundary()
        check()
        for kwargs in ({'dockerenv':False}, {'docker_socket':True}, {'uid':1000},
                       {'caps':status.replace('0000000000000000','0000000000200000')},
                       {'mounts':'1 0 0:1 / / rw - ext4 /dev/root rw\n'},
                       {'mounts':good_mount + '2 1 0:2 / /mnt/host rw - ext4 /dev/root rw\n'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                check(**kwargs)

    def test_child_fence_denies_external_network_and_nonprivate_writes(self):
        import socket
        m = self.load()
        roots = (Path('/mnt/owned'), Path('/evidence/owned'))
        m.audit_boundary('socket.connect', (type('S', (), {'family':socket.AF_INET})(), ('127.0.0.1', 30000)), roots)
        m.audit_boundary('open', ('/mnt/owned/file', 'w', os.O_WRONLY), roots)
        for event, args in (
            ('socket.connect', (type('S', (), {'family':socket.AF_INET})(), ('8.8.8.8',443))),
            ('socket.connect', (type('S', (), {'family':socket.AF_INET})(), ('postgres',5432))),
            ('open', ('/etc/stella-agents/live', 'w', os.O_WRONLY)),
            ('os.rename', ('/mnt/owned/file', '/host/live', -1, -1)),
        ):
            with self.subTest(event=event), self.assertRaises(ValueError):
                m.audit_boundary(event, args, roots)

    def test_devnull_is_not_a_resident_write_and_symlink_escape_stays_closed(self):
        import tempfile
        m = self.load()
        m.audit_boundary('open', ('/dev/null', None, os.O_RDWR), (Path('/mnt/owned'),))
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            (root/'escape').symlink_to('/etc')
            m.audit_boundary('os.remove', (str(root/'escape'), -1), (root,))
            with self.assertRaises(ValueError):
                m.audit_boundary('open', (str(root/'escape/live'), 'w', os.O_WRONLY), (root,))
            fd = os.open('/etc', os.O_RDONLY)
            try:
                with self.assertRaises(ValueError):
                    m.audit_boundary('os.remove', ('live', fd), (root, Path.cwd()))
            finally:
                os.close(fd)

    def test_exact_inventory_rejects_fake_zero_partial_skip_and_fail(self):
        m = self.load()
        ids = ['tests_agent_unified/test_example.py::test_a']
        good = {'collected': ids, 'manual_deselected': [], 'exit_code': 0,
                'results': {ids[0]: {'setup': 'passed', 'call': 'passed', 'teardown': 'passed'}}}
        m.check_complete(good, ids)
        for bad in (
            {**good, 'collected': []}, {**good, 'collected': ids*2},
            {**good, 'results': {}}, {**good, 'exit_code': 1},
            {**good, 'results': {ids[0]: {'setup':'passed','call':'skipped','teardown':'passed'}}},
            {**good, 'results': {ids[0]: {'setup':'passed','call':'failed','teardown':'passed'}}},
            {**good, 'manual_deselected': ids},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m.check_complete(bad, ids)
        with self.assertRaises(ValueError):
            m.check_complete(good, ids + ['missing::test_b'])


if __name__ == '__main__':
    unittest.main()
