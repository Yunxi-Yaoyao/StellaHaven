"""Pinned 46e6229 control-flow boundaries for the narrow env-only extension."""
import ast
import contextlib
import copy
import hashlib
import io
import json
import sys
import unittest
from unittest.mock import patch
from test_production_release import ROOT, load


BASELINE = '46e62291906611ecd0732ea274b9854214cbb92a'


def canonical_ast_dump(value):
    """Freeze field serialization, not ast.dump's changing display defaults.

    Keep every field (including empty lists and None), except empty PEP 695
    type_params on definitions: Python 3.11 has no such field. Nonempty type
    parameters and any other/new fields remain pinned; locations stay excluded.
    """
    if isinstance(value, ast.AST):
        fields = []
        for name, item in ast.iter_fields(value):
            if (isinstance(value, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and name == 'type_params' and item == []):
                continue
            fields.append(name + '=' + canonical_ast_dump(item))
        return type(value).__name__ + '(' + ', '.join(fields) + ')'
    if isinstance(value, list):
        return '[' + ', '.join(canonical_ast_dump(item) for item in value) + ']'
    return repr(value)


def ast_hash(tree):
    return hashlib.sha256(canonical_ast_dump(tree).encode()).hexdigest()


class CanonicalASTTests(unittest.TestCase):
    def test_pin_format_keeps_empty_and_none_fields_except_empty_type_params(self):
        # Fixed wire format: independent of ast.dump's version-specific defaults.
        tree = ast.parse('def f():\n    return 1\n').body[0]
        expected = (
            "FunctionDef(name='f', args=arguments(posonlyargs=[], args=[], "
            "vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]), "
            "body=[Return(value=Constant(value=1, kind=None))], "
            "decorator_list=[], returns=None, type_comment=None)"
        )
        self.assertEqual(ast_hash(tree), hashlib.sha256(expected.encode()).hexdigest())

    def test_only_empty_definition_type_params_are_a_cross_version_no_op(self):
        for source in ('def f(): pass', 'async def f(): pass', 'class C: pass'):
            with self.subTest(source=source):
                legacy = ast.parse(source).body[0]
                setattr(legacy, '_fields', tuple(f for f in legacy._fields if f != 'type_params'))
                modern = copy.deepcopy(legacy)
                setattr(modern, '_fields', (*modern._fields, 'type_params'))
                setattr(modern, 'type_params', [])
                self.assertEqual(ast_hash(legacy), ast_hash(modern))
                setattr(modern, 'type_params', [ast.Name(id='T', ctx=ast.Load())])
                self.assertNotEqual(ast_hash(legacy), ast_hash(modern))

    def test_other_empty_none_and_unknown_fields_remain_pinned(self):
        tree = ast.parse('def f(): pass').body[0]
        for field in ('decorator_list', 'returns'):
            with self.subTest(field=field):
                missing = copy.deepcopy(tree)
                setattr(missing, '_fields', tuple(f for f in missing._fields if f != field))
                self.assertNotEqual(ast_hash(tree), ast_hash(missing))
        for value in ([], None, ['T']):
            with self.subTest(unknown_field=value):
                extended = copy.deepcopy(tree)
                setattr(extended, '_fields', (*extended._fields, 'future_semantics'))
                setattr(extended, 'future_semantics', value)
                self.assertNotEqual(ast_hash(tree), ast_hash(extended))

    def test_locations_are_excluded_and_hashing_does_not_mutate_the_tree(self):
        tree = ast.parse('def f(): return 1')
        before = ast.dump(tree, include_attributes=True)
        digest = ast_hash(tree)
        self.assertEqual(ast.dump(tree, include_attributes=True), before)
        self.assertEqual(digest, ast_hash(ast.parse('\n\n# location only\ndef f(): return 1')))
        self.assertNotEqual(digest, ast_hash(ast.parse('def f(): return 2')))


class ReleasePreservationTests(unittest.TestCase):
    def test_whole_node_ast_changes_only_two_mount_context_arguments(self):
        tree = ast.parse((ROOT / 'node_production.py').read_text())
        node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == 'Node')
        changed = []
        expected = ast.parse("self.cfg.get('mounts', [])", mode='eval').body
        for method in node.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            for call in ast.walk(method):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == 'validate_application_env_overrides':
                    self.assertEqual(len(call.keywords), 1)
                    self.assertEqual(call.keywords[0].arg, 'mounts')
                    self.assertEqual(ast.dump(call.keywords[0].value), ast.dump(expected))
                    call.keywords = []  # only these exact two additions are permitted
                    changed.append(method.name)
        self.assertEqual(changed, ['__init__', 'create'])
        # git show BASELINE:deploy/local-ha/node_production.py, whole Node.
        # Legacy 3.13 ast.dump pin: 3a98fc3248212816da285fe96809c80693526eaa1d225a4085b019b1d8d07d64
        self.assertEqual(ast_hash(node), '17c6834e44d40623fd3732a580be2a79ee84f1e4e1ecc37fd3e4ea6ef69d0035')

    def test_whole_release_ast_changes_only_inventory_mount_context_and_docstring(self):
        tree = ast.parse((ROOT / 'production_release.py').read_text())
        tree.body = tree.body[1:]  # module documentation is not control flow
        calls = [call for call in ast.walk(tree) if isinstance(call, ast.Call) and
                 isinstance(call.func, ast.Attribute) and call.func.attr == 'validate_application_env_overrides']
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(len(call.keywords), 1)
        self.assertEqual(call.keywords[0].arg, 'mounts')
        self.assertEqual(ast.dump(call.keywords[0].value), ast.dump(ast.parse("item.get('mounts', [])", mode='eval').body))
        call.keywords = []
        # git show BASELINE:deploy/local-ha/production_release.py, no module docstring.
        # Legacy 3.13 ast.dump pin: 4fc0545e2d4a1595fc0f69a5d3005528c99cb4db1d8ab7a289ee696825800117
        self.assertEqual(ast_hash(tree), '3ee32edeac8210fb055d02545f9193ba25e9f6ce54b72508233bb13094f349c2')

    def test_probe_start_database_guard_and_normalizer_sources_remain_pinned(self):
        node = load('node_production')
        for value, expected in ((node.PROBE, '924bfec7f1b676a1e788ac402c80569e652904b6bb6187871a8686f49d815ee3'),
                                (node.START, '0880ddee84793cf7acf9162498d211e94ab2db4a56cc0f62a5a96f6958cd7043')):
            self.assertEqual(hashlib.sha256(value.encode()).hexdigest(), expected)
        tree = ast.parse((ROOT / 'node_production.py').read_text())
        guard = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == 'validate_environment')
        # git show BASELINE:deploy/local-ha/node_production.py, unchanged guard.
        # Legacy 3.13 ast.dump pin: 12b8cd4ed5b3857e9eafa19ae076d038d53f79720352b814b2c4b20a298607de
        self.assertEqual(ast_hash(guard), 'a4d15e1a0fae055fc51e659e6279b95d7e2a6ca9bb914bcbc4239d01dbec1462')
        for name, expected in (
                ('normalize_manual_runtime.py', 'd7816a943b5774e96dd120442adfe0050f341ab5d21469f3ae6227384252cc3d'),
                ('node.py', '88bff161a804ac030969fe2271836be711257394eed4889c630202eb057f44ca'),
                ('release.py', 'e720a0d4fb684794cd7afe37d042f88d30fb38afa4aa45ef381ac496dcd99d6f')):
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected)

    def test_pack_mode_never_reads_inventory_or_constructs_transport(self):
        release = load('production_release')
        output = io.StringIO()
        real_read = release.Path.read_text
        def source_only(path, *args, **kw):
            self.assertEqual(path.resolve(), ROOT / 'node_production.py')
            return real_read(path, *args, **kw)
        with patch.object(sys, 'argv', ['production_release.py', '--validate-pack', '--inventory', '/not-opened/private-inventory']), \
                patch.object(release.Path, 'read_text', source_only), \
                patch.object(release, 'SSHTransport', side_effect=AssertionError('no SSH')), \
                patch.object(release, 'validate_inventory', side_effect=AssertionError('no inventory access')), \
                patch.object(release.subprocess, 'run', side_effect=AssertionError('no external command')), \
                contextlib.redirect_stdout(output):
            self.assertEqual(release.main(), 0)
        self.assertEqual(json.loads(output.getvalue()), {'status': 'validated', 'production_executed': False})


if __name__ == '__main__':
    unittest.main()
