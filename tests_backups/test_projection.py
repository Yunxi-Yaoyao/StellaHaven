import io
import json
import uuid
import zipfile
from sqlalchemy import text
from sqlalchemy.orm import Session


def test_settings_projection_roundtrip_preserves_content_and_identity(engine, tmp_path):
    from app.services.backup_projection import export_settings, restore_settings
    from app.services.backup_archive import create_archive
    from app.models.user import User
    from app.models.config import AppConfig
    from app.models.workspace import Workspace
    from app.models.document import Document
    from app.services import blob_store
    owner = uuid.uuid4()
    workspace = uuid.uuid4()
    document = uuid.uuid4()
    with Session(engine) as db:
        db.add(User(id=owner, username='fixture', display_name='Original', password_hash='must-not-export',
                    avatar_url='/assets/avatars/a.png', home_bg='/assets/homebg/b.png'))
        db.flush()
        db.add(Workspace(id=workspace, user_id=owner, name='workspace-sentinel'))
        db.flush()
        db.add(Document(id=document, workspace_id=workspace, title='note-title', file_path='/note.md', content='NOTE-BODY-PRIVATE', content_hash='synthetic-note-hash'))
        db.add_all([AppConfig(key='public_host', value='https://original.example'),
                    AppConfig(key='notes-preferences:' + str(owner), value='{"font_size":19}'),
                    AppConfig(key='web-project:' + str(document), value='WEB-SOURCE-PRIVATE'),
                    AppConfig(key='unknown-private', value='UNKNOWN-CONTENT-PRIVATE')])
        blob_store.put(db, 'homebg/b.png', io.BytesIO(b'BACKGROUND-REAL'), 'image/png', 1000)
        blob_store.put(db, 'avatars/a.png', io.BytesIO(b'AVATAR-REAL'), 'image/png', 1000)
        blob_store.put(db, 'attachments/private', io.BytesIO(b'ATTACHMENT-PRIVATE'), 'application/octet-stream', 1000)
        db.commit()
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with export_settings(conn, tmp_path) as payload:
            create_archive(tmp_path / 'settings.zip', scope='settings', entries=payload.entries, warnings=payload.warnings)
    with zipfile.ZipFile(tmp_path / 'settings.zip') as z:
        raw = b''.join(z.read(n) for n in z.namelist())
        assert z.read('resources/homebg/b.png') == b'BACKGROUND-REAL'
        assert z.read('resources/avatars/a.png') == b'AVATAR-REAL'
        for secret in (b'NOTE-BODY-PRIVATE', b'ATTACHMENT-PRIVATE', b'WEB-SOURCE-PRIVATE', b'UNKNOWN-CONTENT-PRIVATE', b'must-not-export'):
            assert secret not in raw
        assert json.loads(z.read('manifest.json'))['warnings']
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET display_name='Changed', password_hash='keep-new-password', home_bg=''"))
        conn.execute(text("UPDATE app_config SET value='https://changed.example' WHERE key='public_host'"))
    restore_settings(engine, tmp_path / 'settings.zip')
    with Session(engine) as db:
        u = db.get(User, owner)
        assert (u.display_name, u.home_bg, u.password_hash) == ('Original', '/assets/homebg/b.png', 'keep-new-password')
        assert db.get(AppConfig, 'public_host').value == 'https://original.example'
        assert db.get(Document, document).content == 'NOTE-BODY-PRIVATE'
        assert b''.join(blob_store.read_range(db, 'attachments/private', 0, 18)) == b'ATTACHMENT-PRIVATE'
        assert b''.join(blob_store.read_range(db, 'homebg/b.png', 0, 15)) == b'BACKGROUND-REAL'
        assert blob_store.metadata(db, 'homebg/b.png')['mime'] == 'image/png'
        import hashlib,os
        from pathlib import Path
        note=db.get(Document,document).content.encode()
        att=b''.join(blob_store.read_range(db,'attachments/private',0,18))
        evidence={'document_id':str(document),'owner_id':str(owner),'note_sha256':hashlib.sha256(note).hexdigest(),
                  'expected_note_sha256':hashlib.sha256(b'NOTE-BODY-PRIVATE').hexdigest(),
                  'attachment_sha256':hashlib.sha256(att).hexdigest(),'expected_attachment_sha256':hashlib.sha256(b'ATTACHMENT-PRIVATE').hexdigest(),
                  'restored_profile':{'display_name':u.display_name,'home_bg':u.home_bg},'authentication_unchanged':u.password_hash=='keep-new-password',
                  'restored_resource_mime':blob_store.metadata(db,'homebg/b.png')['mime']}
        (Path(os.environ['TMPDIR'])/'settings-roundtrip.json').write_text(json.dumps(evidence,indent=2))


def test_settings_monitor_alert_shared_config_excludes_runtime(engine, tmp_path):
    from app.services.backup_projection import export_settings, restore_settings
    from app.services.backup_archive import create_archive
    from app.models.node import Node, NodeMetric
    from app.models.monitor import Monitor
    from app.models.alert import AlertRule
    from app.services.ha_state import state_table
    from datetime import datetime, timezone
    with Session(engine) as db:
        node = Node(name='original-node', platform='linux', host='fixture.invalid', token='agent-config-secret', status='online', sys_info={'private_runtime':'RUNTIME-NOT-CONFIG'})
        db.add(node)
        db.flush()
        monitor = Monitor(name='original-monitor', node_id=node.id, type='tcp', target='fixture.invalid:22')
        db.add(monitor)
        db.flush()
        rule = AlertRule(kind='monitor_down', target=str(monitor.id), label='original-rule')
        db.add(rule)
        db.add(NodeMetric(node_id=node.id, iface='HISTORY-NOT-CONFIG', ts=datetime.now(timezone.utc), rx_delta=12, tx_delta=13))
        db.execute(state_table.insert(), [dict(key='smtp.config', payload={'host':'smtp.invalid','password':'smtp-config-secret'}),
                                        dict(key='oidc.clients', payload={'fixture':{'client_secret':'oidc-config-secret'}}),
                                        dict(key='oidc.runtime', payload={'tokens':{'RUNTIME-TOKEN-NOT-CONFIG':{}}})])
        db.commit()
        nid, mid, rid = node.id, monitor.id, rule.id
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with export_settings(conn, tmp_path) as payload:
            create_archive(tmp_path / 'settings.zip', scope='settings', entries=payload.entries, warnings=payload.warnings)
    with zipfile.ZipFile(tmp_path / 'settings.zip') as z:
        raw = z.read('settings.json')
        assert b'original-node' in raw and b'original-monitor' in raw and b'original-rule' in raw
        assert b'smtp-config-secret' in raw and b'oidc-config-secret' in raw
        assert b'RUNTIME-NOT-CONFIG' not in raw and b'RUNTIME-TOKEN-NOT-CONFIG' not in raw and b'HISTORY-NOT-CONFIG' not in raw
    with engine.begin() as conn:
        conn.execute(text("UPDATE nodes SET name='changed-node'"))
        conn.execute(text("UPDATE monitors SET name='changed-monitor'"))
        conn.execute(text("UPDATE alert_rules SET label='changed-rule'"))
    restore_settings(engine, tmp_path / 'settings.zip')
    with Session(engine) as db:
        assert db.get(Node, nid).name == 'original-node'
        assert db.get(Node, nid).status == 'online'
        assert db.get(Monitor, mid).name == 'original-monitor'
        assert db.get(AlertRule, rid).label == 'original-rule'
        assert db.query(NodeMetric).one().iface == 'HISTORY-NOT-CONFIG'


def test_nested_private_extensions_are_omitted_and_website_templates_kept(engine, tmp_path):
    from app.services.backup_projection import export_settings
    from app.models.config import AppConfig
    owner = str(uuid.uuid4())
    tid = 'user_' + uuid.uuid4().hex
    registry = dict(modules={}, targets={}, navigation=[], website_templates={tid:{'id':tid,'name':'portable-template','owner_id':owner,'draft':{'name':'portable','custom':{'enabled':False,'css':'','js':'','timing':'dom_ready'}}}},
                    grants={'private':'GRANT-PRIVATE'}, website_save_keys={'x':'RECEIPT-PRIVATE'}, unknown='UNKNOWN-PRIVATE')
    with Session(engine) as db:
        db.add(AppConfig(key='integrations_v1', value=json.dumps(registry)))
        db.add(AppConfig(key='notes-preferences:' + owner, value=json.dumps({'font_size':18, 'unknown_private':'NESTED-PRIVATE'})))
        db.commit()
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with export_settings(conn, tmp_path) as payload:
            raw = payload.entries['settings.json'].read()
            assert b'portable-template' in raw
            assert all(value not in raw for value in (b'GRANT-PRIVATE',b'RECEIPT-PRIVATE',b'UNKNOWN-PRIVATE',b'NESTED-PRIVATE'))


def test_backup_plan_is_projected_without_runtime_and_restored_without_replacing_job(engine, tmp_path):
    from app.services.backup_center import BackupCenter
    from app.services.backup_projection import export_settings, restore_settings
    from app.services.backup_archive import create_archive
    center = BackupCenter(engine, tmp_path, key=b'key')
    center.patch({'scope':'all','time':'06:45','expected_revision':0})
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with export_settings(conn,tmp_path) as payload:
            data=json.loads(payload.entries['settings.json'].getvalue())
            plan=next(row for row in data['config'] if row['key']=='backup_center_v1')
            assert set(json.loads(plan['value'])) == {'config'}
            create_archive(tmp_path/'settings.zip',scope='settings',entries=payload.entries,warnings=payload.warnings)
    center.patch({'time':'09:00','expected_revision':1})
    restore_settings(engine,tmp_path/'settings.zip')
    assert center.status()['config']['time']=='06:45'
    assert center.status()['config']['revision'] > 2


def test_missing_catalog_resource_and_write_fault_refuse_without_partial_settings(engine, tmp_path, monkeypatch):
    import pytest
    from app.services.backup_projection import export_settings, restore_settings
    from app.services.backup_archive import create_archive, InvalidArchive
    from app.models.user import User
    from app.services import blob_store
    owner=uuid.uuid4()
    with Session(engine) as db:
        db.add(User(id=owner,username='fault',display_name='original',password_hash='identity'))
        db.flush()
        blob_store.put(db,'avatars/fault.png',io.BytesIO(b'fault-asset'),'image/png',1000)
        db.commit()
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with export_settings(conn,tmp_path) as payload:
            create_archive(tmp_path/'good.zip',scope='settings',entries=payload.entries)
            payload.entries['settings.json'].seek(0)
            create_archive(tmp_path/'missing.zip',scope='settings',entries={'settings.json':payload.entries['settings.json']})
    with engine.begin() as conn:
        conn.execute(text("UPDATE users SET display_name='keep-after-failure'"))
    with pytest.raises(InvalidArchive): restore_settings(engine,tmp_path/'missing.zip')
    def broken(*a,**k): raise OSError(28,'injected no space')
    monkeypatch.setattr(blob_store,'put',broken)
    with pytest.raises(OSError): restore_settings(engine,tmp_path/'good.zip')
    with Session(engine) as db:
        assert db.get(User,owner).display_name=='keep-after-failure'
        assert db.get(User,owner).password_hash=='identity'


def test_restore_checks_ownership_before_commit_and_rolls_back_on_loss(engine,tmp_path):
    import pytest
    from app.services.backup_projection import export_settings,restore_settings
    from app.services.backup_archive import create_archive
    from app.models.user import User
    uid=uuid.uuid4()
    with Session(engine) as db:
        db.add(User(id=uid,username='fenced',display_name='backup-value',password_hash='identity'));db.commit()
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with export_settings(conn,tmp_path) as payload: create_archive(tmp_path/'settings.zip',scope='settings',entries=payload.entries)
    with engine.begin() as conn: conn.execute(text("UPDATE users SET display_name='current-value'"))
    def lost(): raise RuntimeError('primary authority lost')
    with pytest.raises(RuntimeError): restore_settings(engine,tmp_path/'settings.zip',fence=lost)
    with Session(engine) as db: assert db.get(User,uid).display_name=='current-value'
