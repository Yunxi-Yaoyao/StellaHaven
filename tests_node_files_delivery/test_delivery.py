"""File-release contract, using actual checked-in artifact bytes."""
import hashlib
import importlib.util
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fresh_delivery():
    spec = importlib.util.spec_from_file_location('owned_delivery_cache', ROOT / 'agent/node_files_delivery.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repeated_release_build_and_body_verification_compile_each_exact_source_once(monkeypatch):
    import builtins
    d = fresh_delivery()
    parsed, compiled = [], []
    real_parse = d.ast.parse

    def parse(body, *args, **kwargs):
        parsed.append(body)
        return real_parse(body, *args, **kwargs)

    def compile_tree(tree, *args, **kwargs):
        compiled.append(tree)
        return builtins.compile(tree, *args, **kwargs)

    monkeypatch.setattr(d.ast, 'parse', parse)
    monkeypatch.setattr(d, 'compile', compile_tree, raising=False)
    manifest, bodies = d.build_release(ROOT / 'agent')
    assert d.build_release(ROOT / 'agent') == (manifest, bodies)
    for name, body in bodies.items():
        d.verify_body(name, manifest['files'][name], body)
    assert len(parsed) == 2
    assert len(compiled) == 2


def test_same_version_same_size_same_mtime_change_reparses_and_rehashes(tmp_path, monkeypatch):
    import os
    d = fresh_delivery()
    for name in d.FILES:
        (tmp_path / name).write_bytes((ROOT / 'agent' / name).read_bytes())
    manifest, bodies = d.build_release(tmp_path)
    target = tmp_path / 'node_files.py'
    stat = target.stat()
    body = bodies['node_files.py']
    # Change a byte unrelated to any version declaration.
    changed = body.replace(b'import os', b'import re', 1)
    assert changed != body and len(changed) == len(body)
    parsed = []
    real_parse = d.ast.parse
    def parse(source, *args, **kwargs):
        parsed.append(source)
        return real_parse(source, *args, **kwargs)
    monkeypatch.setattr(d.ast, 'parse', parse)
    target.write_bytes(changed)
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    fresh, new_bodies = d.build_release(tmp_path)
    assert parsed == [changed]
    assert target.stat().st_mtime_ns == stat.st_mtime_ns
    assert fresh['version'] == manifest['version']
    assert new_bodies['node_files.py'] == changed
    assert fresh['files']['node_files.py']['sha256'] == hashlib.sha256(changed).hexdigest()
    assert d.release_id(fresh) != d.release_id(manifest)
    with pytest.raises(d.ReleaseError, match='size_hash_mismatch'):
        d.verify_body('node_files.py', manifest['files']['node_files.py'], changed)
    # Neither mutable result dictionaries nor manifest platform lists are cached.
    fresh['files']['node_files.py']['platforms'].append('windows')
    new_bodies['node_files.py'] = b'poison'
    manifest['files']['node_files.py']['sha256'] = '0' * 64
    clean, clean_bodies = d.build_release(tmp_path)
    assert clean['files']['node_files.py']['platforms'] == ['linux']
    assert clean['files']['node_files.py']['sha256'] == hashlib.sha256(changed).hexdigest()
    assert clean_bodies['node_files.py'] == changed
    assert parsed == [changed]


@pytest.mark.parametrize('replacement', [
    b"FILE_MODULE_VERSION = '1.0.0'\nFILE_PROTOCOL = 2\n",
    b"FILE_MODULE_VERSION = '1.0.0'\nFILE_PROTOCOL = True\n",
    b"FILE_MODULE_VERSION = '1.0.0'\nFILE_PROTOCOX = 1\n",
    b"FILE_MODULE_VERSION = '1.0.0'\nFILE_PROTOCOL = 1\nFILE_PROTOCOL = 1\n",
    b"FILE_MODULE_VERSION = '1.0.0'\nFILE_PROTOCOL = 1\nnot python!\n",
    b"FILE_MODULE_VERSION = '1.0.0'\nFILE_PROTOCOL = 1\nreturn\n",
    b"FILE_MODULE_VERSION = '01.0.0'\nFILE_PROTOCOL = 1\n",
])
def test_same_size_timestamp_mutations_fail_closed_concurrently(tmp_path, replacement):
    import os
    from concurrent.futures import ThreadPoolExecutor
    d = fresh_delivery()
    (tmp_path / 'stella_agent.py').write_bytes(b"AGENT_VERSION = '1.0.0'\n")
    target = tmp_path / 'node_files.py'
    original = b"FILE_MODULE_VERSION = '1.0.0'\nFILE_PROTOCOL = 1\n"
    original = original + b'#' + b' ' * (255 - len(original))
    target.write_bytes(original)
    manifest, _ = d.build_release(tmp_path)
    stat = target.stat()
    changed = replacement + b'#' + b' ' * (255 - len(replacement))
    assert len(changed) == len(original)
    target.write_bytes(changed)
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    def refused(_):
        with pytest.raises((d.ReleaseError, SyntaxError)):
            d.build_release(tmp_path)
        with pytest.raises(d.ReleaseError, match='size_hash_mismatch'):
            d.verify_body('node_files.py', manifest['files']['node_files.py'], target.read_bytes())
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(refused, range(8)))
    target.write_bytes(original)
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert d.build_release(tmp_path)[0] == manifest


def test_bounded_cache_eviction_and_uncached_failures(monkeypatch):
    d = fresh_delivery()
    parsed = []
    real_parse = d.ast.parse
    def parse(body, *args, **kwargs):
        parsed.append(body)
        return real_parse(body, *args, **kwargs)
    monkeypatch.setattr(d.ast, 'parse', parse)
    first = b'VALUE = 0\n'
    for n in range(5):
        assert d.declaration(('VALUE = %s\n' % n).encode(), 'VALUE') == n
    assert d._source_declarations.cache_info().maxsize == 4
    assert d._source_declarations.cache_info().currsize == 4
    assert d.declaration(first, 'VALUE') == 0
    assert parsed.count(first) == 2
    for _ in range(2):
        with pytest.raises(SyntaxError):
            d.declaration(b'VALUE = 1\nreturn\n', 'VALUE')
    assert parsed.count(b'VALUE = 1\nreturn\n') == 2
    assert d._source_declarations.cache_info().currsize == 4


def test_declarations_keep_per_name_counts_and_original_input_compatibility():
    import ast
    d = fresh_delivery()
    body = b'VALUE = 1\nOTHER = 2\nOTHER = 3\n'
    assert d.declaration(body, 'VALUE') == 1
    for name in ('OTHER', 'MISSING'):
        with pytest.raises(d.ReleaseError, match='invalid_version_declaration'):
            d.declaration(body, name)
    before = d._source_declarations.cache_info()
    for source in ('VALUE = 1\n', bytearray(b'VALUE = 1\n'), ast.parse('VALUE = 1\n')):
        assert d.declaration(source, 'VALUE') == 1
    mutable = bytearray(b'VALUE = 1\n')
    assert d.declaration(mutable, 'VALUE') == 1
    mutable[-2] = ord('2')
    assert d.declaration(mutable, 'VALUE') == 2
    oversized = b'VALUE = 1\n#' + b' ' * d.LIMIT
    assert d.declaration(oversized, 'VALUE') == 1
    assert d._source_declarations.cache_info() == before
    facts = d._source_declarations(body)
    assert isinstance(facts, tuple) and all(isinstance(pair, tuple) for pair in facts)
    with pytest.raises(TypeError):
        facts[0] = ('VALUE', 999)
    assert d.declaration(body, 'VALUE') == 1


def test_oversize_real_release_still_refused(tmp_path):
    d = fresh_delivery()
    (tmp_path / 'stella_agent.py').write_bytes(b"AGENT_VERSION = '1.0.0'\n")
    (tmp_path / 'node_files.py').write_bytes(b"FILE_MODULE_VERSION = '1.0.0'\nFILE_PROTOCOL = 1\n#" + b' ' * d.LIMIT)
    with pytest.raises(d.ReleaseError, match='invalid_file_digest'):
        d.build_release(tmp_path)
    assert d._source_declarations.cache_info().currsize == 1


def test_complete_manifest_pins_main_and_file_module():
    assert importlib.util.find_spec('agent.node_files_delivery') is not None, 'missing complete file-module delivery contract'
    from agent.node_files_delivery import build_release
    manifest, bodies = build_release(ROOT / 'agent')
    assert set(bodies) == {'stella_agent.py', 'node_files.py'}
    assert manifest['format'] == 1
    assert manifest['files']['stella_agent.py']['version'] == manifest['version']
    assert manifest['files']['node_files.py']['protocol'] == 1
    assert manifest['files']['node_files.py']['platforms'] == ['linux']
    for name, body in bodies.items():
        assert body == (ROOT / 'agent' / name).read_bytes()
        assert manifest['files'][name]['size'] == len(body)
        assert manifest['files'][name]['sha256'] == hashlib.sha256(body).hexdigest()
    assert 'path' not in str(manifest) and 'roots' not in str(manifest)


def test_complete_generation_activation_rolls_back_on_failed_handoff(tmp_path):
    from agent import node_files_delivery as delivery
    assert hasattr(delivery, 'ReleaseStore'), 'missing atomic complete-generation installer'
    manifest, bodies = delivery.build_release(ROOT / 'agent')
    store = delivery.ReleaseStore(tmp_path / 'owned-store')
    first = store.install(manifest, lambda name, info: bodies[name])
    original_pointer = (store.root / 'current.json').read_bytes()
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    for name, body in bodies.items():
        (candidate / name).write_bytes(body.replace(b"FILE_MODULE_VERSION = '1.0.0'", b"FILE_MODULE_VERSION = '1.0.1'"))
    second_manifest, second_bodies = delivery.build_release(candidate)
    import pytest
    with pytest.raises(RuntimeError, match='owned handoff failure'):
        with store.transaction(second_manifest, lambda name, info: second_bodies[name]) as active:
            assert active != first and store.current() == active
            assert (active / 'stella_agent.py').read_bytes() == second_bodies['stella_agent.py']
            assert (active / 'node_files.py').read_bytes() == second_bodies['node_files.py']
            raise RuntimeError('owned handoff failure')
    assert store.current() == first
    assert (store.root / 'current.json').read_bytes() == original_pointer
    for name in bodies:
        assert (store.current() / name).read_bytes() == bodies[name]


def test_local_policy_is_closed_and_windows_does_not_advertise_roots(monkeypatch):
    import pytest
    from agent import node_files
    monkeypatch.delenv('STELLA_FILE_ROOTS', raising=False)
    assert node_files.Sandbox.from_env().roots() == []
    for value in ([], {'r': {'path': ''}}, {'r': {'path': 'relative'}}, {'r': {'path': '/approved', 'write': 'true'}}, {'r': {'path': '/approved', 'sudo': True}}):
        with pytest.raises(node_files.FileError, match='invalid_local_policy'):
            node_files.Sandbox(value)
    monkeypatch.setattr(node_files.sys, 'platform', 'win32')
    assert node_files.Sandbox({'r': {'path': '/approved', 'write': True}}).roots() == []


def test_loading_installed_module_does_not_mutate_immutable_generation(tmp_path, monkeypatch):
    from agent import node_files_delivery as delivery
    import sys
    manifest, bodies = delivery.build_release(ROOT / 'agent')
    store = delivery.ReleaseStore(tmp_path / 'immutable')
    active = store.install(manifest, lambda name, info: bodies[name])
    monkeypatch.setattr(sys, 'dont_write_bytecode', False)
    module, result = delivery.installed_module(store)
    assert module.FILE_MODULE_VERSION == result['files']['node_files.py']['version']
    assert {p.name for p in active.iterdir()} == {'manifest.json', 'node_files.py', 'stella_agent.py'}
    assert store.current() == active


@pytest.mark.parametrize('fault', ['missing-module', 'extra-file', 'extra-path', 'bad-hash', 'bool-size', 'wrong-version', 'wrong-protocol', 'windows-advertised', 'oversize', 'bool-format'])
def test_invalid_complete_manifest_is_refused_before_fetch(tmp_path, fault):
    from agent import node_files_delivery as d
    manifest, _ = d.build_release(ROOT / 'agent')
    module = manifest['files']['node_files.py']
    if fault == 'missing-module':
        del manifest['files']['node_files.py']
    elif fault == 'extra-file':
        manifest['files']['../escape.py'] = dict(module)
    elif fault == 'extra-path':
        module['path'] = '/etc'
    elif fault == 'bad-hash':
        module['sha256'] = 'G' * 64
    elif fault == 'bool-size':
        module['size'] = True
    elif fault == 'wrong-version':
        manifest['files']['stella_agent.py']['version'] = '999.0.0'
    elif fault == 'wrong-protocol':
        module['protocol'] = 2
    elif fault == 'windows-advertised':
        module['platforms'] = ['linux', 'windows']
    elif fault == 'oversize':
        module['size'] = d.LIMIT + 1
    else:
        manifest['format'] = True
    fetched = []
    store = d.ReleaseStore(tmp_path / 'refused')
    with pytest.raises(d.ReleaseError):
        store.install(manifest, lambda *args: fetched.append(args))
    assert fetched == [] and store.current() is None


@pytest.mark.parametrize('fault', ['hash', 'size', 'version', 'protocol', 'syntax', 'import'])
def test_bad_module_preserves_previous_complete_generation(tmp_path, fault):
    from agent import node_files_delivery as d
    manifest, bodies = d.build_release(ROOT / 'agent')
    store = d.ReleaseStore(tmp_path / 'rollback')
    active = store.install(manifest, lambda name, info: bodies[name])
    pointer = (store.root / 'current.json').read_bytes()
    changed = dict(bodies)
    body = bodies['node_files.py'] + b'\n# owned candidate\n'
    if fault == 'version':
        body = body.replace(b"FILE_MODULE_VERSION = '1.0.0'", b"FILE_MODULE_VERSION = '9.0.0'")
    elif fault == 'protocol':
        body = body.replace(b'FILE_PROTOCOL = 1', b'FILE_PROTOCOL = 2')
    elif fault == 'syntax':
        body += b'not python syntax!\n'
    elif fault == 'import':
        body += b"raise RuntimeError('owned load failure')\n"
    changed['node_files.py'] = body
    info = manifest['files']['node_files.py']
    info['sha256'] = hashlib.sha256(body).hexdigest() if fault != 'hash' else '0' * 64
    info['size'] = len(body) if fault != 'size' else len(body) + 1
    with pytest.raises((d.ReleaseError, SyntaxError)):
        store.install(manifest, lambda name, info: changed[name])
    assert store.current() == active
    assert (store.root / 'current.json').read_bytes() == pointer
    assert not list(store.root.glob('.stage-*')) and not (store.root / '.install-lock').exists()


def test_install_lock_and_first_install_rollback_are_fail_closed(tmp_path):
    from agent import node_files_delivery as d
    manifest, bodies = d.build_release(ROOT / 'agent')
    store = d.ReleaseStore(tmp_path / 'lock')
    with pytest.raises(RuntimeError):
        with store.transaction(manifest, lambda name, info: bodies[name]):
            with pytest.raises(d.ReleaseError, match='busy'):
                store.install(manifest, lambda name, info: bodies[name])
            raise RuntimeError('owned first-install handoff')
    assert store.current() is None
    (store.root / '.install-lock').mkdir()
    with pytest.raises(d.ReleaseError, match='busy'):
        store.install(manifest, lambda name, info: bodies[name])
    assert (store.root / '.install-lock').is_dir()


@pytest.mark.parametrize('fault', ['missing', 'symlink', 'hardlink', 'hash', 'world-write', 'pointer'])
def test_installed_boot_never_falls_back_on_invalid_module(tmp_path, fault):
    from agent import node_files_delivery as d
    manifest, bodies = d.build_release(ROOT / 'agent')
    store = d.ReleaseStore(tmp_path / 'boot')
    active = store.install(manifest, lambda name, info: bodies[name])
    target = active / 'node_files.py'
    if fault in ('missing', 'symlink', 'hardlink'):
        target.unlink()
        if fault == 'symlink':
            target.symlink_to(ROOT / 'agent' / 'node_files.py')
        elif fault == 'hardlink':
            (tmp_path / 'linked').write_bytes(bodies['node_files.py'])
            import os
            os.link(tmp_path / 'linked', target)
    elif fault == 'hash':
        target.write_bytes(bodies['node_files.py'] + b'\n')
    elif fault == 'world-write':
        target.chmod(0o666)
    else:
        (store.root / 'current.json').write_text('{"release":"../agent"}')
    with pytest.raises((d.ReleaseError, OSError)):
        d.installed_module(store)


@pytest.mark.parametrize('origin', ['http://example.test', 'http://127.0.0.1', 'https://u:p@example.test', 'https://example.test/path', 'https://example.test/?q=1', 'file:///etc'])
def test_transport_origin_refuses_unsafe_defaults(origin):
    from agent.node_files_delivery import checked_origin, ReleaseError
    with pytest.raises(ReleaseError):
        checked_origin(origin)


def test_required_worker_httpx_dependency_is_probed_before_activation(tmp_path, monkeypatch):
    from agent import node_files_delivery as d
    import subprocess
    manifest, bodies = d.build_release(ROOT / 'agent')
    store = d.ReleaseStore(tmp_path / 'no-site-packages')
    real_run = subprocess.run
    def without_site(argv, **kwargs):
        # Actual resident interpreter, but hide site-packages to prove the
        # dependency boundary; no invented import/probe responses.
        return real_run([argv[0], '-S', *argv[1:]], **kwargs)
    monkeypatch.setattr(d.subprocess, 'run', without_site)
    with pytest.raises(d.ReleaseError, match='load_validation'):
        store.install(manifest, lambda name, info: bodies[name])
    assert store.current() is None
