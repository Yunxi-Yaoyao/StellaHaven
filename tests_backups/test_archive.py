import io
import zipfile
from pathlib import Path
import pytest


def test_real_zip_manifest_and_bytes(tmp_path):
    from app.services.backup_archive import create_archive, validate_archive
    target = tmp_path / 'settings.zip'
    manifest = create_archive(target, scope='settings', entries={'settings.json': io.BytesIO(b'{"real":true}'),
                                                                'resources/homebg/a.png': io.BytesIO(b'background-bytes')})
    assert manifest['scope'] == 'settings'
    assert validate_archive(target)['id'] == manifest['id']
    with zipfile.ZipFile(target) as z:
        assert z.read('resources/homebg/a.png') == b'background-bytes'
        assert set(z.namelist()) == {'manifest.json', 'settings.json', 'resources/homebg/a.png'}
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('damage', ['traversal', 'duplicate', 'version', 'hash', 'missing', 'symlink', 'bomb', 'duplicate-json'])
def test_damaged_untrusted_zips_are_rejected(tmp_path, damage):
    import json
    from app.services.backup_archive import create_archive, validate_archive, InvalidArchive
    original = tmp_path / 'original.zip'
    create_archive(original, scope='settings', entries={'settings.json': io.BytesIO(b'{}')})
    with zipfile.ZipFile(original) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    manifest = json.loads(entries['manifest.json'])
    if damage == 'version': manifest['version'] = 999
    if damage == 'hash': manifest['entries']['settings.json']['sha256'] = '0' * 64
    if damage == 'missing': entries.pop('settings.json')
    entries['manifest.json'] = json.dumps(manifest).encode()
    if damage == 'duplicate-json':
        entries['manifest.json'] = entries['manifest.json'].replace(b'"version": 1', b'"version": 999, "version": 1')
    bad = tmp_path / 'bad.zip'
    with zipfile.ZipFile(bad, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, raw in entries.items(): z.writestr(name, raw)
        if damage == 'traversal': z.writestr('../outside', b'bad')
        if damage == 'duplicate':
            with pytest.warns(UserWarning): z.writestr('settings.json', b'{}')
        if damage == 'symlink':
            info = zipfile.ZipInfo('symlink'); info.external_attr = 0o120777 << 16; z.writestr(info, b'/etc/hosts')
        if damage == 'bomb': z.writestr('bomb', b'0' * 2_000_000)
    with pytest.raises(InvalidArchive):
        validate_archive(bad)


def test_writer_enforces_total_budget_during_stream_not_after_finishing(tmp_path,monkeypatch):
    import app.services.backup_archive as module
    monkeypatch.setattr(module,'MAX_TOTAL',10)
    reads=[]
    class Bounded:
        def read(self,n):
            reads.append(n)
            if len(reads)>4: raise RuntimeError('writer overran total budget')
            return b'12345678901'
    with pytest.raises(module.InvalidArchive):
        module.create_archive(tmp_path/'failed.zip',scope='settings',entries={'settings.json':Bounded()})
    assert len(reads)==1 and not (tmp_path/'failed.zip').exists()


def test_streaming_zip_8mib_uses_bounded_python_memory(tmp_path):
    import json,random,tracemalloc
    from app.services.backup_archive import create_archive,validate_archive,CHUNK
    block=random.Random(310).randbytes(CHUNK)
    class Source:
        remaining=32
        def read(self,n):
            assert n<=CHUNK
            if not self.remaining:return b''
            self.remaining-=1
            return block
    tracemalloc.start()
    try:
        create_archive(tmp_path/'stream.zip',scope='all',entries={'database.dump':Source()})
        _,peak=tracemalloc.get_traced_memory()
    finally:tracemalloc.stop()
    assert peak<4*1024**2
    receipt={'source_bytes':len(block)*32,'peak_python_bytes':peak,'archive_bytes':(tmp_path/'stream.zip').stat().st_size}
    (Path(__import__('os').environ['TMPDIR'])/'streaming-budget.json').write_text(json.dumps(receipt))
