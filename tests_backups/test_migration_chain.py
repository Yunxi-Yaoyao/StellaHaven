"""Run the actual Alembic env/chain on one extra owned PG18 database."""
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import psycopg2
from psycopg2 import sql


def test_full_pg18_alembic_chain_roundtrip_and_detached_downgrade_refusal(owned, tmp_path):
    # No existing database argument is accepted. CREATE/DROP are restricted to
    # a generated sibling inside the already verified network-none server.
    database = 'backup_migration_' + uuid4().hex
    root = Path(__file__).resolve().parents[1]
    c = psycopg2.connect(host='127.0.0.1', port=5432, dbname=owned['database'],
                         user=owned['user'], password=owned['password'], connect_timeout=3)
    c.autocommit = True
    with c.cursor() as q:
        q.execute('SELECT current_database(), current_user, host(inet_server_addr()), inet_server_port()')
        assert q.fetchone() == (owned['database'], owned['user'], '127.0.0.1', 5432)
        q.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    out = root.parent / 'docs/Stella-界面改版执行-20261017/backup-migration-chain'
    out.mkdir(exist_ok=True)
    env = dict(os.environ, POSTGRES_DB=database, PYTHONPATH=str(root))
    code = '''
from pathlib import Path
import hashlib,json,os
from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text,inspect
from app.database import engine
from sqlalchemy.orm import Session
from app.models import User,Workspace,Document,Attachment
from app.services import blob_store
import io
root=Path(os.environ['PYTHONPATH'])
assert not Path('.env').exists()
with engine.connect() as c:
    assert c.execute(text('SELECT current_database(), current_user, host(inet_server_addr()), inet_server_port()')).one() == (os.environ['POSTGRES_DB'],os.environ['POSTGRES_USER'],'127.0.0.1',5432)
cfg=Config()
cfg.set_main_option('script_location',str(root/'alembic'))
assert ScriptDirectory.from_config(cfg).get_heads()==['62a4d9c0e871']
command.upgrade(cfg,'head')
with Session(engine) as db:
    u=User(username='migration-fixture',display_name='Fixture',password_hash='not-a-live-password');db.add(u);db.flush()
    w=Workspace(name='fixture',user_id=u.id);db.add(w);db.flush()
    d=Document(workspace_id=w.id,title='Migration sentinel',file_path='/migration-fixture',content='preserve-original-text',content_hash=hashlib.sha256(b'preserve-original-text').hexdigest());db.add(d);db.flush()
    a=Attachment(doc_id=d.id,filename='fixture.bin',mime='application/octet-stream',size=len(b'preserve-blobdata'));db.add(a);db.flush()
    blob_store.put(db,'attachments/'+str(a.id),io.BytesIO(b'preserve-blobdata'),a.mime,1024)
    aid,did,uid=a.id,d.id,u.id
    db.commit()
command.downgrade(cfg,'47c1d9e2ab60')
with engine.connect() as c:
    columns={col['name']:col for col in inspect(c).get_columns('attachments')}
    assert 'owner_id' not in columns and not columns['doc_id']['nullable']
    assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='47c1d9e2ab60'
command.upgrade(cfg,'head')
with Session(engine) as db:
    assert db.get(Document,did).content=='preserve-original-text'
    meta=blob_store.metadata(db,'attachments/'+str(aid))
    assert b''.join(blob_store.read_range(db,meta['key'],0,meta['size']))==b'preserve-blobdata'
    a=db.get(Attachment,aid);a.owner_id=uid;a.doc_id=None;db.commit()
try:
    command.downgrade(cfg,'47c1d9e2ab60')
except RuntimeError as e:
    assert 'detached project attachments' in str(e)
else:
    raise AssertionError('incompatible downgrade accepted detached data')
with engine.connect() as c:
    assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='62a4d9c0e871'
    assert c.execute(text('SELECT doc_id FROM attachments WHERE id=:id'),{'id':aid}).scalar_one() is None
    assert inspect(c).has_table('blob_chunks')
engine.dispose()
print(json.dumps({'actual_env_chain':True,'head':'62a4d9c0e871','upgrade_downgrade_reupgrade':True,'original_content_and_blob_preserved':True,'detached_downgrade_rejected':True,'production_mutated':False}))
'''
    try:
        result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=env,
                                capture_output=True, text=True, timeout=100)
        (out / 'actual-chain.log').write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        receipt = json.loads(result.stdout.splitlines()[-1])
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    finally:
        with c.cursor() as q:
            q.execute('SELECT current_database(), current_user')
            assert q.fetchone() == (owned['database'], owned['user'])
            q.execute('SELECT count(*) FROM pg_stat_activity WHERE datname=%s', (database,))
            assert q.fetchone()[0] == 0, 'migration child still owns database sessions'
            q.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
            q.execute('SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=%s)', (database,))
            assert q.fetchone()[0] is False
        c.close()
