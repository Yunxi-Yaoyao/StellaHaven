"""ZIP compensation source review: metadata only, no application bootstrap."""
import ast
from collections import Counter
from copy import deepcopy
import hashlib

import pytest

from test_api_openapi_contract import ROOT, static_inventory
from test_api_response_contract import response_module


ZIP_SUPPORT = {
    'app.services.notes_zip._reconcile_failed_files',
    'app.services.attachment_lifecycle.drain_file_gc',
    'app.services.attachment_lifecycle.referenced_candidates',
    'app.services.attachment_lifecycle.references',
    'app.services.notes_lifecycle.lock_graph',
    'app.services.notes_lifecycle.lock_workspace',
    'app.services.notes_tools.lock_key',
    'app.models.document.Document',
    'app.models.document_version.DocumentVersion',
    'app.models.attachment.Attachment',
    'app.models.config.AppConfig',
}
ZIP_FILES = {'app/services/notes_zip.py', 'app/services/attachment_lifecycle.py'}


def assert_exact_operations(m, records):
    # Base 233 + approved Notes 6 / web projects 16 / backups 10. Compare
    # identities, not a refreshed magic count that can hide replaced operations.
    actual = Counter((method, path, endpoint) for method, path, endpoint, _ in records)
    reviewed = Counter((row['method'], row['path'], row['endpoint']) for row in m.INVENTORY)
    assert actual == reviewed
    assert all(count == 1 for count in actual.values()), 'duplicate operation'
    assert Counter((method, path) for method, path, _ in actual) == Counter(m.DECLARATIONS.keys())
    assert m.validate_response_sources(ROOT, records) == []


def source_range(text, file, symbol):
    symbol = symbol.split('@', 1)[0]
    if symbol == file:
        return 1, len(text.splitlines())
    module = file.removesuffix('.py').replace('/', '.')
    for whole_file in (file + ':', module + ':'):
        if symbol.startswith(whole_file):
            assert symbol.removeprefix(whole_file), 'missing whole-file review identity'
            return 1, len(text.splitlines())
    prefix = module + '.'
    assert symbol.startswith(prefix), ('source symbol outside module', symbol, file)
    scope = ast.parse(text).body
    node = None
    for name in symbol.removeprefix(prefix).split('.'):
        matches = []
        for candidate in scope:
            if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if candidate.name == name:
                    matches.append(candidate)
            elif isinstance(candidate, (ast.Assign, ast.AnnAssign)):
                targets = candidate.targets if isinstance(candidate, ast.Assign) else [candidate.target]
                if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                    matches.append(candidate)
        assert len(matches) == 1, ('missing or ambiguous reviewed symbol', symbol, name)
        node = matches[0]
        scope = getattr(node, 'body', [])
    assert node is not None
    return node.lineno, node.end_lineno


def assert_source_range(source, root=ROOT):
    path = root / source['file']
    assert source['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (source['line'], source['end_line']) == source_range(path.read_text(), source['file'], source['symbol'])


def test_zip_compensation_has_complete_supporting_source_chain():
    m = response_module()
    records = static_inventory()[0]
    assert_exact_operations(m, records)
    declaration = m.DECLARATIONS[('POST', '/documents/import/zip')]
    assert declaration['endpoint'] == 'app.routers.document.import_zip'
    assert ZIP_SUPPORT <= set(declaration['sources'])
    for symbol in declaration['sources']:
        assert symbol in m.SOURCE_EVIDENCE
        assert m.SOURCE_EVIDENCE[symbol]['symbol'].split('@', 1)[0] == symbol.split('@', 1)[0]
        assert_source_range(m.SOURCE_EVIDENCE[symbol])


def test_zip_review_source_ranges_match_exact_candidate_ast():
    m = response_module()
    selected = [source for source in m.SOURCE_EVIDENCE.values() if source['file'] in ZIP_FILES]
    assert {source['file'] for source in selected} == ZIP_FILES
    for source in selected:
        assert_source_range(source)


@pytest.mark.parametrize('mutation', ['unknown', 'missing', 'wrong-method', 'duplicate'])
def test_exact_inventory_rejects_operation_mutations(mutation):
    m = response_module()
    records = list(static_inventory()[0])
    if mutation == 'unknown':
        records.append(('GET', '/unreviewed-endpoint', 'app.routers.document.future', []))
    elif mutation == 'missing':
        records.pop()
    elif mutation == 'wrong-method':
        method, path, endpoint, metadata = records[0]
        records[0] = ('UNREVIEWED', path, endpoint, metadata)
    else:
        records.append(records[0])
    with pytest.raises(AssertionError):
        assert_exact_operations(m, records)
    # Production fail-closed validator also rejects unknown/missing/changed
    # identities; duplicate detection is an additional test-level guarantee.
    if mutation != 'duplicate':
        assert m.validate_response_sources(ROOT, records)


@pytest.mark.parametrize('field,value', [('line', 0), ('end_line', 99999), ('sha256', '0' * 64), ('symbol', 'app.services.notes_zip.missing')])
def test_zip_source_review_rejects_range_hash_and_symbol_mutations(field, value):
    source = deepcopy(response_module().SOURCE_EVIDENCE['app.services.notes_zip._reconcile_failed_files'])
    source[field] = value
    with pytest.raises(AssertionError):
        assert_source_range(source)


@pytest.mark.parametrize('symbol,expected', [
    ('fixture.LIMIT', (1, 1)), ('fixture.Policy', (2, 5)),
    ('fixture.Policy.LIMIT', (3, 3)), ('fixture.Policy.check', (4, 5)),
    ('fixture.async_check', (6, 7)), ('fixture.py:whole-review', (1, 7)),
])
def test_source_ranges_support_constants_classes_and_qualified_symbols(symbol, expected):
    text = 'LIMIT = 1\nclass Policy:\n    LIMIT: int = 2\n    def check(self):\n        return self.LIMIT\nasync def async_check():\n    return LIMIT\n'
    assert source_range(text, 'fixture.py', symbol) == expected
