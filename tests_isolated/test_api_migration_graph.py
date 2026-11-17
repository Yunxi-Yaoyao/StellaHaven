"""Static migration graph gates; never imports app, config, database or Alembic env."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def revision_path(revision, directory=None):
    matches = []
    for path in (directory or ROOT / 'alembic/versions').glob('*.py'):
        for node in ast.parse(path.read_text()).body:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            if any(isinstance(t, ast.Name) and t.id == 'revision' for t in targets):
                if ast.literal_eval(node.value) == revision:
                    matches.append(path)
    assert len(matches) == 1, 'revision must identify exactly one migration'
    return matches[0]


def test_revision_selection_ignores_parent_and_docstring_mentions(tmp_path):
    wrong = tmp_path / 'first.py'
    wrong.write_text('"""e2a3b4c5d6f7"""\nrevision = "child"\ndown_revision = "e2a3b4c5d6f7"\n')
    right = tmp_path / 'merge.py'
    right.write_text('revision: str = "e2a3b4c5d6f7"\n')
    assert revision_path('e2a3b4c5d6f7', tmp_path) == right
    right.unlink()
    import pytest
    with pytest.raises(AssertionError):
        revision_path('e2a3b4c5d6f7', tmp_path)


def revisions():
    result = {}
    for path in (ROOT / 'alembic/versions').glob('*.py'):
        values = {}
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name) and node.target.id in ('revision', 'down_revision'):
                values[node.target.id] = ast.literal_eval(node.value)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ('revision', 'down_revision'):
                        values[target.id] = ast.literal_eval(node.value)
        if values.get('revision'):
            assert values['revision'] not in result, 'duplicate migration revision'
            parents = values.get('down_revision')
            result[values['revision']] = set(parents if isinstance(parents, tuple) else [parents]) - {None}
    return result


def test_single_head_contains_browser_and_alert_branches():
    graph = revisions()
    referenced = set().union(*graph.values())
    assert referenced <= graph.keys(), 'missing parent migration'
    heads = graph.keys() - referenced
    assert len(heads) == 1, f'parallel migration heads need explicit reconciliation: {sorted(heads)}'
    seen = set()
    pending = list(heads)
    while pending:
        revision = pending.pop()
        if revision in seen:
            continue
        seen.add(revision)
        pending.extend(graph[revision])
    assert {'c1d2e3f4a5b6', 'd1a2b3c4d5e6'} <= seen


def test_merge_revision_has_no_data_mutation():
    graph = revisions()
    matches = [rev for rev, parents in graph.items() if parents == {'c1d2e3f4a5b6', 'd1a2b3c4d5e6'}]
    assert len(matches) == 1, 'explicit merge must preserve both independently authored histories'
    assert matches == ['e2a3b4c5d6f7']
    path = revision_path(matches[0])
    tree = ast.parse(path.read_text())
    for function in (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('upgrade', 'downgrade')):
        assert all(isinstance(n, (ast.Pass, ast.Expr)) and (isinstance(n, ast.Pass) or isinstance(n.value, ast.Constant)) for n in function.body)
