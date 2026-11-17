import io
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile
import psycopg2
from sqlalchemy import text
from sqlalchemy.orm import Session


def test_pg18_all_snapshot_and_real_offline_empty_target_restore(engine, owned, tmp_path):
    from app.services.backup_postgres import export_all
    from app.services.backup_archive import create_archive
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.document import Document
    from app.models.config import AppConfig
    from app.models.attachment import Attachment
    from app.models.node import Node,NodeMetric
    from datetime import datetime,timezone
    from app.services import blob_store
    owner, ws, doc = (uuid.uuid4() for _ in range(3))
    with Session(engine) as db:
        db.add(User(id=owner, username='roundtrip', display_name='Roundtrip', password_hash='synthetic'))
        db.flush()
        db.add(Workspace(id=ws, user_id=owner, name='Real workspace'))
        db.flush()
        db.add(Document(id=doc, workspace_id=ws, title='real article', file_path='/real.md', content='FULL-CONTENT', content_hash='fixture'))
        db.add(AppConfig(key='web-project:' + str(doc), value='WEB-FULL-SOURCE'))
        db.flush()
        att=uuid.uuid4()
        db.add(Attachment(id=att,doc_id=doc,filename='real.bin',mime='application/octet-stream',size=len(b'\x00\xffREAL-BYTEA' * 100000)))
        node=Node(name='history-node',platform='linux',host='history.invalid')
        db.add(node);db.flush()
        db.add(NodeMetric(node_id=node.id,iface='snapshot-history',ts=datetime(2026,1,1,tzinfo=timezone.utc),rx_delta=123,tx_delta=456))
        blob_store.put(db, 'attachments/'+str(att), io.BytesIO(b'\x00\xffREAL-BYTEA' * 100000), 'application/octet-stream', 2000000)
        db.commit()
    data_root = tmp_path / 'data'
    (data_root / 'assets').mkdir(parents=True)
    (data_root / 'assets' / 'config.png').write_bytes(b'FILE-CONFIG-RESOURCE')
    (data_root / 'backups').mkdir()
    (data_root / 'backups' / 'recursive.zip').write_bytes(b'NEVER-COPY-RECURSIVE')
    archive = tmp_path / 'all.zip'
    with engine.connect().execution_options(isolation_level='REPEATABLE READ', postgresql_readonly=True) as conn:
        assert conn.execute(text('SELECT content FROM documents WHERE id=:id'),{'id':doc}).scalar_one()=='FULL-CONTENT'
        with engine.begin() as changed:
            changed.execute(text("UPDATE documents SET content='CONCURRENT-NEW-CONTENT' WHERE id=:id"),{'id':doc})
        with export_all(conn, tmp_path, data_root) as payload:
            create_archive(archive, scope='all', entries=payload.entries, warnings=payload.warnings)
    with zipfile.ZipFile(archive) as z:
        assert z.read('files/assets/config.png') == b'FILE-CONFIG-RESOURCE'
        assert not any('recursive.zip' in n for n in z.namelist())
    admin = psycopg2.connect(host='127.0.0.1', dbname='postgres', user=owned['user'], password=owned['password'])
    admin.autocommit = True
    from psycopg2 import sql
    with admin.cursor() as cur:
        cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(owned['restore_db'])))
    try:
        password_file = tmp_path / 'password'
        password_file.write_text(owned['password'])
        password_file.chmod(0o600)
        output = tmp_path / 'restored-data'
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'tools' / 'backup_restore.py'),
                   '--archive', str(archive), '--host', '127.0.0.1', '--port', '5432', '--user', owned['user'],
                   '--database', owned['restore_db'], '--password-file', str(password_file), '--data-directory', str(output),
                   '--maintenance', '--confirm-target', '127.0.0.1:5432/' + owned['restore_db'],
                   '--sha256', __import__('hashlib').file_digest(archive.open('rb'),'sha256').hexdigest()]
        refused = subprocess.run(command[:-1]+['0'*64],capture_output=True,text=True)
        assert refused.returncode!=0 and not output.exists()
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        target = psycopg2.connect(host='127.0.0.1', dbname=owned['restore_db'], user=owned['user'], password=owned['password'])
        with target, target.cursor() as cur:
            cur.execute('SELECT d.content, w.user_id FROM documents d JOIN workspaces w ON w.id=d.workspace_id WHERE d.id=%s', (str(doc),))
            restored_note,restored_owner=cur.fetchone()
            assert (restored_note,restored_owner) == ('FULL-CONTENT', str(owner))
            cur.execute("SELECT value FROM app_config WHERE key=%s", ('web-project:' + str(doc),))
            assert cur.fetchone()[0] == 'WEB-FULL-SOURCE'
            cur.execute('SELECT data FROM blob_chunks b JOIN attachments a ON b.key=\'attachments/\'||a.id::text JOIN documents d ON d.id=a.doc_id WHERE d.id=%s ORDER BY b.number', (str(doc),))
            restored_blob=b''.join(bytes(r[0]) for r in cur.fetchall())
            assert restored_blob == b'\x00\xffREAL-BYTEA' * 100000
            cur.execute("SELECT rx_delta,tx_delta FROM node_metrics m JOIN nodes n ON n.id=m.node_id WHERE n.name='history-node'")
            restored_history=cur.fetchone()
            assert restored_history==(123,456)
            cur.execute("SELECT conname FROM pg_constraint WHERE conrelid='attachments'::regclass")
            constraints=sorted(row[0] for row in cur.fetchall())
            assert 'attachment_has_custodian' in constraints
        target.close()
        assert (output / 'assets/config.png').read_bytes() == b'FILE-CONFIG-RESOURCE'
        checkpoints=list(tmp_path.glob('.stella-restore-*.json'))
        assert checkpoints and json.loads(checkpoints[0].read_text())['state']=='succeeded'
        # A second run must refuse the nonempty DB before attempting pg_restore.
        again = subprocess.run(command, capture_output=True, text=True)
        assert again.returncode != 0
        assert owned['password'] not in result.stdout + result.stderr + again.stdout + again.stderr
        import hashlib
        with zipfile.ZipFile(archive) as z:
            manifest=json.loads(z.read('manifest.json'))
        with engine.connect() as source:
            current_source_note=source.execute(text('SELECT content FROM documents WHERE id=:id'),{'id':doc}).scalar_one()
        evidence={'cli_result':json.loads(result.stdout),'wrong_checksum_rejected':refused.returncode!=0,
                  'nonempty_target_rejected':again.returncode!=0,'workspace_id':str(ws),'owner_id':str(owner),'document_id':str(doc),
                  'attachment_id':str(att),'source_blob_sha256':hashlib.sha256(b'\x00\xffREAL-BYTEA'*100000).hexdigest(),
                  'restored_blob_sha256':hashlib.sha256(restored_blob).hexdigest(),'schema_attachment_constraints':constraints,
                  'manifest':manifest,'archive_sha256':hashlib.file_digest(archive.open('rb'),'sha256').hexdigest(),
                  'restored_resource_sha256':hashlib.sha256((output/'assets/config.png').read_bytes()).hexdigest(),
                  'expected_resource_sha256':hashlib.sha256(b'FILE-CONFIG-RESOURCE').hexdigest(),
                  'restored_note_snapshot':restored_note,'concurrent_source_note':current_source_note,
                  'history_probe':dict(zip(('rx_delta','tx_delta'),restored_history))}
        (Path(os.environ['TMPDIR'])/'pg-roundtrip.json').write_text(json.dumps(evidence,indent=2))
    finally:
        with admin.cursor() as cur:
            cur.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(owned['restore_db'])))
        admin.close()


def test_all_excludes_selected_backup_directory_even_inside_persistent_assets(engine,tmp_path):
    from app.services.backup_postgres import export_all
    from app.services.backup_archive import create_archive
    data=tmp_path/'data';selected=data/'assets'/'nested-backups';selected.mkdir(parents=True)
    (selected/'stella-settings-old.zip').write_bytes(b'NEVER-RECURSIVE')
    with engine.connect().execution_options(isolation_level='REPEATABLE READ',postgresql_readonly=True) as conn:
        with export_all(conn,tmp_path,data,backup_directory=selected) as payload:
            assert all(not name.startswith('files/assets/nested-backups/') for name in payload.entries)
