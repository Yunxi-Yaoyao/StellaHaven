"""NF-SEC-01: real ACL/UID oracle, owned roots only; no ACL-edit product API."""
import errno
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
import subprocess

import pytest
from agent import node_files as nf
from test_pipeline import complete, submit

BODY = b'edited-owned-data'


def set_acl(path, value, default=False):
    subprocess.run([(shutil.which('setfacl') or '/usr/sbin/setfacl'), *(['-d'] if default else []), '-m', value, str(path)], check=True)


def snapshot(path):
    info = path.stat()
    return {'body': path.read_bytes().hex(), 'inode': info.st_ino, 'dev': info.st_dev,
            'uid': info.st_uid, 'gid': info.st_gid, 'mode': info.st_mode,
            'acl': subprocess.check_output([(shutil.which('getfacl') or '/usr/sbin/getfacl'), '-cpn', str(path)], text=True)}


def dropped_read(root):
    # Enter the owned directory before dropping UID: no global ancestor chmod.
    result = subprocess.run([(shutil.which('setpriv') or '/usr/sbin/setpriv'), '--reuid=65534', '--regid=65534', '--clear-groups',
                             sys.executable, '-I', '-c', 'from pathlib import Path; print(Path("private.txt").read_text())'],
                            cwd=root, env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True)
    return {'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}


def record(name, data):
    Path(os.environ['NODE_FILES_EVIDENCE'], name + '.json').write_text(json.dumps(data, indent=2))


def setup_file(root, access=True):
    root.chmod(0o755)
    path = root / 'private.txt'
    path.write_bytes(b'original-owned-data')
    path.chmod(0o644)
    if access:
        set_acl(path, 'u:65534:---')
    return path


def request(path):
    return {'op': 'edit', 'root': 'owned', 'path': path.name, 'size': len(BODY),
            'sha256': hashlib.sha256(BODY).hexdigest(), 'etag': hashlib.sha256(path.read_bytes()).hexdigest()}


def sandbox(root):
    return nf.Sandbox({'owned': {'path': str(root), 'write': True}})


def scoped(system, key):
    root = system['root'] / key
    root.mkdir()
    policy = json.loads(system['policy'].read_text())
    policy['930001'][key] = {'owners': [str(system['uid'])], 'write': True}
    system['policy'].write_text(json.dumps(policy))
    system['worker'].sandbox.allowed[key] = {'path': str(root), 'write': True}
    system['worker'].tick()
    return root


def test_access_acl_sandbox_denial_oracle(tmp_path):
    path = setup_file(tmp_path)
    before, read_before = snapshot(path), dropped_read(tmp_path)
    assert read_before['returncode'] != 0 and 'PermissionError' in read_before['stderr']
    consumed, error, result = [], None, None
    def chunks():
        consumed.append(True)
        yield BODY
    try:
        result = sandbox(tmp_path).write_stream(request(path), chunks())
    except nf.FileError as exc:
        error = str(exc)
    after, read_after = snapshot(path), dropped_read(tmp_path)
    record('access-sandbox', {'source': nf.__file__, 'before': before, 'after': after,
                             'read_before': read_before, 'read_after': read_after,
                             'error': error, 'result': result, 'body_consumed': bool(consumed)})
    assert read_after['returncode'] != 0, 'NF-SEC-01: edit granted previously denied UID65534 read access'
    assert error == 'metadata_preservation_denied'
    assert before == after and not consumed
    assert not list(tmp_path.glob('.stella-file-*'))


def test_access_acl_http_pg_worker_denial_oracle(system):
    root = scoped(system, 'aclaccess')
    path = setup_file(root)
    before, read_before = snapshot(path), dropped_read(root)
    assert read_before['returncode'] != 0 and 'PermissionError' in read_before['stderr']
    preview = complete(system, submit(system, 'preview', path.name, root='aclaccess'))
    assert preview['state'] == 'done'
    job = submit(system, 'edit', path.name, root='aclaccess', size=len(BODY),
                 sha256=hashlib.sha256(BODY).hexdigest(), etag=preview['result']['etag'])
    assert system['client'].put('/node-files/requests/' + job['id'] + '/upload?offset=0', content=BODY).status_code == 200
    assert system['client'].post('/node-files/requests/' + job['id'] + '/seal').status_code == 200
    result = complete(system, job)
    after, read_after = snapshot(path), dropped_read(root)
    # Read the exact durable result back, not only the worker's successful POST.
    assert system['client'].get('/node-files/requests/' + job['id']).json() == result
    record('access-http-pg-worker', {'source': nf.__file__, 'before': before, 'after': after,
                                    'read_before': read_before, 'read_after': read_after, 'receipt': result})
    assert read_after['returncode'] != 0, 'NF-SEC-01: HTTP edit granted previously denied UID65534 read access'
    assert result['state'] == 'failed' and result['error'] == 'metadata_preservation_denied'
    assert before == after
    assert not list(root.glob('.stella-file-*'))


@pytest.mark.parametrize('when', ['initial', 'commit'])
def test_parent_default_acl_is_not_permission_equivalence(tmp_path, when):
    path = setup_file(tmp_path, access=False)
    path.chmod(0o640)  # UID65534 cannot read, but inherited named-user:r can grant it.
    before, read_before = snapshot(path), dropped_read(tmp_path)
    assert read_before['returncode'] != 0 and 'PermissionError' in read_before['stderr']
    def set_default():
        set_acl(tmp_path, 'u:65534:r--', default=True)
        return True
    if when == 'initial':
        set_default()
    consumed, error = [], None
    def chunks():
        consumed.append(True)
        yield BODY
    try:
        sandbox(tmp_path).write_stream(request(path), chunks(), commit=set_default if when == 'commit' else None)
    except nf.FileError as exc:
        error = str(exc)
    after, read_after = snapshot(path), dropped_read(tmp_path)
    record('default-' + when, {'before': before, 'after': after, 'read_before': read_before,
                              'read_after': read_after, 'error': error, 'body_consumed': bool(consumed),
                              'parent_acl': subprocess.check_output([(shutil.which('getfacl') or '/usr/sbin/getfacl'), '-cpn', str(tmp_path)], text=True)})
    assert error == 'metadata_preservation_denied', 'parent default ACL not rechecked at commit'
    assert before == after and read_after['returncode'] != 0
    assert when != 'initial' or not consumed
    assert not list(tmp_path.glob('.stella-file-*'))


@pytest.mark.parametrize('when', ['before_body', 'commit'])
def test_replacement_acl_not_just_mode_is_checked(tmp_path, monkeypatch, when):
    path = setup_file(tmp_path, access=False)
    before = snapshot(path)
    consumed = []
    real_open = os.open
    def open_with_inherited_acl(name, flags, *args, **kwargs):
        if isinstance(name, str) and name.startswith('.stella-file-'):
            # Default added after the initial parent check, inherited by the
            # replacement, then removed. Only the replacement ACL exposes it.
            set_acl(tmp_path, 'u:65534:---', default=True)
            try:
                return real_open(name, flags, *args, **kwargs)
            finally:
                subprocess.run([(shutil.which('setfacl') or '/usr/sbin/setfacl'), '-k', str(tmp_path)], check=True)
        return real_open(name, flags, *args, **kwargs)
    def mutate_replacement():
        temporary, = tmp_path.glob('.stella-file-*')
        set_acl(temporary, 'u:65534:---')
        assert temporary.stat().st_mode == path.stat().st_mode
        return True
    def chunks():
        consumed.append(True)
        yield BODY
    if when == 'before_body':
        monkeypatch.setattr(nf.os, 'open', open_with_inherited_acl)
    with pytest.raises(nf.FileError, match='metadata_preservation_denied'):
        sandbox(tmp_path).write_stream(request(path), chunks(), commit=mutate_replacement if when == 'commit' else None)
    assert snapshot(path) == before
    assert bool(consumed) == (when == 'commit')
    assert not list(tmp_path.glob('.stella-file-*'))


@pytest.mark.parametrize('phase,error', [
    ('source', errno.EIO), ('source', errno.EPERM), ('source', errno.EOPNOTSUPP),
    ('source', errno.ENOSYS), ('source', None), ('parent', errno.EIO),
    ('replacement', errno.EIO), ('commit-source', errno.EIO),
    ('commit-parent', errno.EOPNOTSUPP), ('commit-replacement', errno.EIO),
])
def test_acl_read_unknown_is_fail_closed(tmp_path, monkeypatch, phase, error):
    path = setup_file(tmp_path, access=False)
    before = snapshot(path)
    original_ino, parent_ino = path.stat().st_ino, tmp_path.stat().st_ino
    real_getxattr, armed, consumed = os.getxattr, False, []
    def uncertain(fd, name, *args, **kwargs):
        inode = os.fstat(fd).st_ino
        target = phase.removeprefix('commit-')
        matches = inode == original_ino if target == 'source' else inode == parent_ino if target == 'parent' else inode not in (original_ino, parent_ino)
        if matches and (not phase.startswith('commit-') or armed):
            raise OSError(error, 'owned injected ACL read failure')
        return real_getxattr(fd, name, *args, **kwargs)
    if error is None:
        monkeypatch.delattr(nf.os, 'getxattr')
    else:
        monkeypatch.setattr(nf.os, 'getxattr', uncertain)
    def commit():
        nonlocal armed
        armed = True
        return True
    def chunks():
        consumed.append(True)
        yield BODY
    with pytest.raises(nf.FileError, match='metadata_preservation_denied'):
        sandbox(tmp_path).write_stream(request(path), chunks(), commit=commit)
    assert snapshot(path) == before
    assert bool(consumed) == phase.startswith('commit-')
    assert not list(tmp_path.glob('.stella-file-*'))


def test_acl_change_during_cas_keeps_external_inode_and_acl(tmp_path):
    path = setup_file(tmp_path, access=False)
    current = None
    def external_acl_change():
        nonlocal current
        set_acl(path, 'u:65534:---')
        current = snapshot(path)
        return True
    with pytest.raises(nf.FileError, match='cas_conflict'):
        sandbox(tmp_path).write_stream(request(path), [BODY], commit=external_acl_change)
    assert snapshot(path) == current
    assert dropped_read(tmp_path)['returncode'] != 0
    assert not list(tmp_path.glob('.stella-file-*'))


@pytest.mark.parametrize('change', ['mode', 'uid', 'gid', 'hardlink'])
def test_replacement_metadata_rechecked_at_commit(tmp_path, change):
    path = setup_file(tmp_path, access=False)
    before = snapshot(path)
    def mutate():
        temporary, = tmp_path.glob('.stella-file-*')
        if change == 'mode': temporary.chmod(0o666)
        elif change == 'uid': os.chown(temporary, 65534, -1)
        elif change == 'gid': os.chown(temporary, -1, 65534)
        else: os.link(temporary, tmp_path / 'owned-extra-link')
        return True
    with pytest.raises(nf.FileError, match='metadata_preservation_denied'):
        sandbox(tmp_path).write_stream(request(path), [BODY], commit=mutate)
    assert snapshot(path) == before
    assert not list(tmp_path.glob('.stella-file-*'))


def test_plain_no_acl_edit_preserves_supported_metadata(tmp_path):
    path = setup_file(tmp_path, access=False)
    before = snapshot(path)
    result = sandbox(tmp_path).write_stream(request(path), [BODY])
    after = snapshot(path)
    assert result['sha256'] == hashlib.sha256(BODY).hexdigest()
    assert path.read_bytes() == BODY
    assert all(before[key] == after[key] for key in ('uid', 'gid', 'mode', 'acl'))
    assert not list(tmp_path.glob('.stella-file-*'))
