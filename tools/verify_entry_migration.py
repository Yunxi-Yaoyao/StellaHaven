"""Destructive migration rehearsal ONLY for our disposable PG container 25461."""
import os,sys,json,hashlib,subprocess,tempfile
from pathlib import Path
from sqlalchemy import create_engine,text,inspect
ROOT=Path(__file__).resolve().parents[1]
CONTAINER='stella-entry-monitoring-qa-20261020'
ROLE=DB='entry_monitoring'
assert tuple(os.environ.get(k) for k in ('POSTGRES_HOST','POSTGRES_PORT','POSTGRES_USER','POSTGRES_DB'))==('127.0.0.1','25461',ROLE,DB)
engine=create_engine('postgresql://entry_monitoring:owned-entry-fixture-only@127.0.0.1:25461/entry_monitoring')
output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)

def command(args,**kwargs):
    r=subprocess.run(args,check=True,capture_output=True,**kwargs)
    return r.stdout

def samples(engine):
    with engine.connect() as c:
        return [list(r) for r in c.execute(text('SELECT id,control_channel FROM nodes ORDER BY id'))]

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
original=samples(engine)
assert any(v is not None for _,v in original),'run real report acceptance before backup'
restore='entry_monitoring_restore'
receipt={'scope':'ONLY disposable container '+CONTAINER,'before_revision':'cc20261020','rows':len(original),'before_samples_sha256':digest(original)}
with tempfile.TemporaryDirectory(prefix='entry-migration-',dir=os.environ['TMPDIR']) as scratch:
    dump=Path(scratch)/'owned.dump'
    with dump.open('wb') as f:
        subprocess.run(['docker','exec',CONTAINER,'pg_dump','-U',ROLE,'-d',DB,'-Fc'],stdout=f,check=True)
    dump.chmod(0o600)
    receipt.update(backup_sha256=hashlib.sha256(dump.read_bytes()).hexdigest(),backup_bytes=dump.stat().st_size)
    for target,label in [('bf20261019','downgrade'),('head','upgrade')]:
        p=subprocess.run([sys.executable,'-m','alembic',label,target],cwd=ROOT,capture_output=True,text=True)
        (output/(label+'.log')).write_text(p.stdout+p.stderr)
        assert p.returncode==0,(label,p.stderr)
        columns={c['name']:c for c in inspect(engine).get_columns('nodes')}
        assert ('control_channel' in columns)==(label=='upgrade')
        with engine.connect() as c:revision=c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
        receipt[label]={'returncode':p.returncode,'revision':revision,'column_present':'control_channel' in columns}
    assert all(value is None for _,value in samples(engine)),'upgrade must not invent old-Agent samples'
    command(['docker','exec',CONTAINER,'createdb','-U',ROLE,restore])
    try:
        with dump.open('rb') as f:
            r=subprocess.run(['docker','exec','-i',CONTAINER,'pg_restore','-U',ROLE,'-d',restore,'--no-owner','--exit-on-error'],stdin=f,capture_output=True)
        assert r.returncode==0,r.stderr.decode()
        restored_engine=create_engine('postgresql://entry_monitoring:owned-entry-fixture-only@127.0.0.1:25461/'+restore)
        restored=samples(restored_engine)
        assert restored==original
        restored_engine.dispose()
        receipt.update(restore_returncode=r.returncode,restored_samples_sha256=digest(restored),restore_matches=True)
    finally:
        command(['docker','exec',CONTAINER,'dropdb','-U',ROLE,restore])
receipt['settings_backup_policy']='nodes.control_channel and entry_monitoring.v1 are telemetry/runtime identities, excluded from settings archive allowlist; full PG backup preserves raw JSONB and monitor checks.'
(output/'MIGRATION.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
engine.dispose()
print(json.dumps(receipt,ensure_ascii=False,indent=2))
