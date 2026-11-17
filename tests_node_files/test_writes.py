import hashlib
import pytest
from agent import node_files as nf


def context(tmp_path, write=True):
    return nf.Sandbox({'fixture': {'path': str(tmp_path), 'write': write}})


def request(op, path='', **extra):
    return {'op': op, 'root': 'fixture', 'path': path, **extra}


def test_create_mkdir_rename_copy_move_no_clobber(tmp_path):
    s = context(tmp_path)
    s.execute(request('mkdir', 'folder'))
    s.execute(request('create', 'a.txt'))
    assert (tmp_path / 'a.txt').read_bytes() == b''
    (tmp_path / 'a.txt').write_text('alpha')
    s.execute(request('copy', 'a.txt', destination='folder/copy.txt'))
    s.execute(request('rename', 'a.txt', destination='renamed.txt'))
    s.execute(request('move', 'renamed.txt', destination='folder/moved.txt'))
    assert (tmp_path / 'folder/moved.txt').read_text() == 'alpha'
    assert (tmp_path / 'folder/copy.txt').read_text() == 'alpha'
    with pytest.raises(nf.FileError, match='destination_exists'):
        s.execute(request('copy', 'folder/copy.txt', destination='folder/moved.txt'))
    assert (tmp_path / 'folder/moved.txt').read_text() == 'alpha'
    with pytest.raises(nf.FileError):
        context(tmp_path, False).execute(request('create', 'denied'))
    assert not (tmp_path / 'denied').exists()


def test_raw_upload_and_cas_edit_conflict(tmp_path):
    s = context(tmp_path)
    content = b'first\n'
    req = request('upload', 'upload.txt', size=len(content), sha256=hashlib.sha256(content).hexdigest())
    s.write_stream(req, iter([content]), lambda: True)
    before = s.execute(request('preview', 'upload.txt'))
    edit = b'second\n'
    edit_req = request('edit', 'upload.txt', size=len(edit), sha256=hashlib.sha256(edit).hexdigest(), etag=before['etag'])
    (tmp_path / 'upload.txt').write_bytes(b'external change')
    with pytest.raises(nf.FileError, match='cas_conflict'):
        s.write_stream(edit_req, iter([edit]), lambda: True)
    assert (tmp_path / 'upload.txt').read_bytes() == b'external change'
    edit_req['etag'] = s.execute(request('preview', 'upload.txt'))['etag']
    s.write_stream(edit_req, iter([edit]), lambda: True)
    assert (tmp_path / 'upload.txt').read_bytes() == edit
    assert not list(tmp_path.glob('.stella-file-*'))


def test_cancel_hash_collision_and_symlink_leave_no_partial(tmp_path):
    s = context(tmp_path)
    data = b'bytes'
    req = request('upload', 'target', size=len(data), sha256=hashlib.sha256(data).hexdigest())
    with pytest.raises(nf.FileError):
        s.write_stream(req, iter([b'wrong']), lambda: True)
    assert not (tmp_path / 'target').exists()
    calls = []
    def cancelled():
        calls.append(True)
        return len(calls) < 2
    with pytest.raises(nf.FileError, match='inactive_request'):
        s.write_stream(req, iter([data]), cancelled)
    assert not (tmp_path / 'target').exists()
    (tmp_path / 'link').symlink_to('other')
    with pytest.raises(nf.FileError):
        s.execute(request('move', 'link', destination='renamed'))
    (tmp_path / 'target').write_text('original')
    with pytest.raises(nf.FileError, match='destination_exists'):
        s.write_stream(req, iter([data]), lambda: True)
    assert (tmp_path / 'target').read_text() == 'original'
    assert not list(tmp_path.glob('.stella-file-*'))


def test_copy_hash_pass_is_bounded_when_source_grows(tmp_path, monkeypatch):
    limit = 4 * nf.CHUNK_SIZE
    monkeypatch.setattr(nf, 'TRANSFER_LIMIT', limit)
    source = tmp_path / 'growing'
    source.write_bytes(b'x')
    inode = source.stat().st_ino
    original_read = nf.os.read
    observed = []
    def growing_read(fd, count):
        chunk = original_read(fd, count)
        if nf.os.fstat(fd).st_ino == inode:
            observed.append(len(chunk))
            if source.stat().st_size < limit + 2 * nf.CHUNK_SIZE:
                with source.open('ab') as target:
                    target.write(b'y' * nf.CHUNK_SIZE)
        return chunk
    with monkeypatch.context() as scope:
        scope.setattr(nf.os, 'read', growing_read)
        with pytest.raises(nf.FileError, match='transfer_limit'):
            context(tmp_path).execute(request('copy', 'growing', destination='copy'))
    assert sum(observed) <= limit + nf.CHUNK_SIZE
    assert not (tmp_path / 'copy').exists()


@pytest.mark.parametrize('op',['delete','chmod','chown','archive'])
def test_destructive_operations_absent(tmp_path, op):
    with pytest.raises(nf.FileError, match='unsupported_operation'):
        context(tmp_path).execute(request(op, 'file'))
