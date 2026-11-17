import io
import os
import zipfile
import pytest


def test_mixed_scopes_publish_then_retain_two_and_failed_does_not_evict(tmp_path):
    from app.services.backup_storage import BackupDirectory
    store = BackupDirectory(tmp_path, b'test-owned-key')
    unrelated = tmp_path / 'unrelated.zip'
    unrelated.write_bytes(b'not ours')
    records = []
    for scope in ('settings', 'all', 'settings'):
        records.append(store.create(scope, {'settings.json' if scope == 'settings' else 'database.dump': io.BytesIO(b'actual-data')}))
    assert [r['id'] for r in store.records()] == [records[2]['id'], records[1]['id']]
    assert not (tmp_path / records[0]['filename']).exists()
    assert unrelated.read_bytes() == b'not ours'
    class Broken:
        def read(self, n):
            raise OSError(28, 'injected disk full')
    with pytest.raises(OSError):
        store.create('settings', {'settings.json': Broken()})
    assert len(store.records()) == 2
    assert set(p.name for p in tmp_path.glob('*.zip')) == {unrelated.name, records[1]['filename'], records[2]['filename']}
    assert not list(tmp_path.glob('*.tmp'))


def test_symlink_directory_and_record_rejected_without_following(tmp_path):
    from app.services.backup_storage import BackupDirectory
    linked = tmp_path / 'linked'
    linked.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        BackupDirectory(linked, b'key').create('settings', {'settings.json': io.BytesIO(b'{}')})
    store = BackupDirectory(tmp_path, b'key')
    record = store.create('settings', {'settings.json': io.BytesIO(b'{}')})
    path = tmp_path / record['filename']
    path.unlink()
    external = tmp_path / 'external'
    external.write_bytes(b'keep me')
    path.symlink_to(external)
    with pytest.raises((OSError, ValueError)):
        store.delete(record['id'], record['filename'])
    assert external.read_bytes() == b'keep me'


def test_killed_writer_cleanup_is_bounded_and_does_not_evict(tmp_path):
    import subprocess
    import sys
    from app.services.backup_storage import BackupDirectory
    store = BackupDirectory(tmp_path, b'key')
    old = [store.create('settings', {'settings.json': io.BytesIO(b'{}')}) for _ in range(2)]
    code = '''
import os, sys
from app.services.backup_storage import BackupDirectory
class Killed:
    def read(self,n): os._exit(23)
BackupDirectory(sys.argv[1], b'key').create('settings', {'settings.json':Killed()})
'''
    killed = subprocess.run([sys.executable, '-c', code, str(tmp_path)])
    assert killed.returncode == 23
    assert {r['id'] for r in store.records()} == {r['id'] for r in old}
    store.create('settings', {'settings.json': io.BytesIO(b'{}')})
    assert not list(tmp_path.glob('.stella-backup-*.tmp'))


def test_same_timestamp_retention_uses_publication_order(tmp_path,monkeypatch):
    import app.services.backup_archive as module
    from app.services.backup_storage import BackupDirectory
    from datetime import datetime,timezone
    class Clock:
        @staticmethod
        def now(zone): return datetime(2026,1,1,tzinfo=timezone.utc)
        fromisoformat=staticmethod(datetime.fromisoformat)
    monkeypatch.setattr(module,'datetime',Clock)
    store=BackupDirectory(tmp_path,b'key')
    rows=[store.create(scope,{'settings.json' if scope=='settings' else 'database.dump':io.BytesIO(b'{}')}) for scope in ('all','settings','all')]
    assert [r['id'] for r in store.records()]==[rows[2]['id'],rows[1]['id']]


def test_failed_postpublication_index_recovery_keeps_new_and_two_good(tmp_path,monkeypatch):
    from app.services.backup_storage import BackupDirectory
    store=BackupDirectory(tmp_path,b'key')
    for _ in range(2): store.create('settings',{'settings.json':io.BytesIO(b'{}')})
    original=store._retain
    def crash(*args): raise OSError(5,'injected index I/O failure')
    monkeypatch.setattr(store,'_retain',crash)
    with pytest.raises(OSError): store.create('all',{'database.dump':io.BytesIO(b'pg-data')})
    assert len(list(tmp_path.glob('stella-*.zip')))==3
    assert len(store.records())==2
    monkeypatch.setattr(store,'_retain',original)
    store.create('settings',{'settings.json':io.BytesIO(b'{}')})
    assert len(list(tmp_path.glob('stella-*.zip')))==2
    assert len(store.records())==2


def test_crash_after_old_unlink_before_index_trim_recovers_without_four_records(tmp_path,monkeypatch):
    from app.services.backup_storage import BackupDirectory,INDEX
    store=BackupDirectory(tmp_path,b'key')
    for _ in range(2):store.create('settings',{'settings.json':io.BytesIO(b'{}')})
    original=store._write
    calls=[]
    def failure(fd,name,payload):
        if name==INDEX:
            calls.append(len(payload))
            if len(calls)==2:raise OSError(5,'injected trim failure')
        return original(fd,name,payload)
    monkeypatch.setattr(store,'_write',failure)
    with pytest.raises(OSError):store.create('all',{'database.dump':io.BytesIO(b'pgdump')})
    monkeypatch.setattr(store,'_write',original)
    store.create('settings',{'settings.json':io.BytesIO(b'{}')})
    assert len(store.records())==2 and len(list(tmp_path.glob('stella-*.zip')))==2


def test_crashed_metadata_staging_is_recovered_and_unowned_tmp_untouched(tmp_path):
    import subprocess,sys
    from app.services.backup_storage import BackupDirectory
    code='''
import io,os,sys
from app.services.backup_storage import BackupDirectory
original=os.replace
def crash(*args,**kwargs): os._exit(27)
os.replace=crash
BackupDirectory(sys.argv[1],b'key').create('settings',{'settings.json':io.BytesIO(b'{}')})
'''
    assert subprocess.run([sys.executable,'-c',code,str(tmp_path)]).returncode==27
    unrelated=tmp_path/'.stella-index-unrelated.tmp';unrelated.write_bytes(b'not signed')
    store=BackupDirectory(tmp_path,b'key')
    store.create('settings',{'settings.json':io.BytesIO(b'{}')})
    assert list(tmp_path.glob('.stella-index-*.tmp'))==[unrelated]
    assert unrelated.read_bytes()==b'not signed'


def test_recovery_cleans_signed_killed_zip_without_creating_new_backup(tmp_path):
    import subprocess,sys
    from app.services.backup_storage import BackupDirectory
    code='''
import os,sys
from app.services.backup_storage import BackupDirectory
class Killed:
    def read(self,n):os._exit(31)
BackupDirectory(sys.argv[1],b'key').create('settings',{'settings.json':Killed()})
'''
    assert subprocess.run([sys.executable,'-c',code,str(tmp_path)]).returncode==31
    assert list(tmp_path.glob('.stella-backup-*.tmp'))
    store=BackupDirectory(tmp_path,b'key')
    store.recover()
    assert not list(tmp_path.glob('.stella-backup-*.tmp')) and store.records()==[]
