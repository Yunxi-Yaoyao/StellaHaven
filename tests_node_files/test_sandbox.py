"""Only task-owned tmp_path files; no resident node execution."""
import os
import pytest
from agent import node_files as nf


def sandbox(tmp_path, write=False):
    return nf.Sandbox({'fixture': {'path': str(tmp_path), 'write': write}})


def test_default_empty_and_explicit_root(tmp_path):
    assert nf.Sandbox().roots() == []
    with pytest.raises(nf.FileError):
        nf.Sandbox().execute({'op': 'list', 'root': 'fixture', 'path': ''})
    (tmp_path / 'hello.txt').write_text('你好\n')
    (tmp_path / '.hidden').write_text('x')
    (tmp_path / 'dir').mkdir()
    result = sandbox(tmp_path).execute({'op': 'list', 'root': 'fixture', 'path': ''})
    assert [x['name'] for x in result['entries']] == ['dir', 'hello.txt']
    assert all({'mode', 'uid', 'gid', 'size', 'kind'} <= x.keys() for x in result['entries'])
    assert len(sandbox(tmp_path).execute({'op': 'list', 'root': 'fixture', 'path': '', 'hidden': True})['entries']) == 3
    preview = sandbox(tmp_path).execute({'op': 'preview', 'root': 'fixture', 'path': 'hello.txt'})
    assert preview['text'] == '你好\n' and len(preview['etag']) == 64


@pytest.mark.parametrize('path', ['../escape', '/etc/passwd', 'a/../b', 'a//b', 'a/./b', 'a\\b', 'a\x00b'])
def test_bad_path(tmp_path, path):
    with pytest.raises(nf.FileError):
        sandbox(tmp_path).execute({'op': 'preview', 'root': 'fixture', 'path': path})


def test_symlinks_special_files_and_preview_budget(tmp_path):
    (tmp_path / 'real').write_text('content')
    (tmp_path / 'link').symlink_to('real')
    (tmp_path / 'dir').mkdir()
    (tmp_path / 'linked').symlink_to('dir', target_is_directory=True)
    os.mkfifo(tmp_path / 'pipe')
    for path in ['link', 'linked/anything', 'pipe']:
        with pytest.raises(nf.FileError):
            sandbox(tmp_path).execute({'op': 'preview', 'root': 'fixture', 'path': path})
    (tmp_path / 'large').write_bytes(b'x' * (nf.PREVIEW_LIMIT + 1))
    with pytest.raises(nf.FileError, match='preview_limit'):
        sandbox(tmp_path).execute({'op': 'preview', 'root': 'fixture', 'path': 'large'})
    (tmp_path / 'binary').write_bytes(b'\x00\xff')
    with pytest.raises(nf.FileError, match='binary'):
        sandbox(tmp_path).execute({'op': 'preview', 'root': 'fixture', 'path': 'binary'})


def test_download_actual_chunks_and_no_links(tmp_path):
    data = bytes(range(256)) * 1200
    (tmp_path / 'bytes.bin').write_bytes(data)
    chunks = list(sandbox(tmp_path).stream('fixture', 'bytes.bin'))
    assert len(chunks) > 1 and max(map(len, chunks)) <= nf.CHUNK_SIZE
    assert b''.join(chunks) == data


def test_directory_budget_and_sort(tmp_path):
    for name in ['z', 'a', 'm']:
        (tmp_path / name).write_text(name)
    result = sandbox(tmp_path).execute({'op': 'list', 'root': 'fixture', 'path': '', 'sort': 'name', 'descending': True})
    assert [x['name'] for x in result['entries']] == ['z', 'm', 'a']
    with pytest.raises(nf.FileError, match='directory_limit'):
        sandbox(tmp_path).execute({'op': 'list', 'root': 'fixture', 'path': '', 'limit': 2})
