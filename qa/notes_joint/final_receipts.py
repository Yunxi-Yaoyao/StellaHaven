"""Exact owned-state readback and production asset equality before cleanup."""
import json,hashlib,subprocess
from pathlib import Path
import httpx
from psycopg2 import sql
from test_live_http import db,R,O,S,URL
m=json.loads(subprocess.run(['docker','inspect',S['id']],check=True,text=True,capture_output=True).stdout)[0]
assert m['Id']==S['id'] and m['Config']['Labels']['stella.audit']==S['label']
assert m['HostConfig']['NanoCpus']==1000000000 and m['HostConfig']['Memory']==805306368
with db() as c,c.cursor() as q:
    q.execute('select current_database(),current_user');identity=q.fetchone();assert identity==(S['db'],S['user'])
    q.execute('select tablename from pg_tables where schemaname=%s',(S['schema'],));tables=[x[0] for x in q.fetchall()];tasks={}
    for t in tables:
        if any(word in t for word in ['task','command','node']):
            q.execute(sql.SQL('select count(*) from {}').format(sql.Identifier(t)));tasks[t]=q.fetchone()[0]
    assert all(v==0 for v in tasks.values()),tasks
    q.execute("select count(*) from pg_tables where schemaname='public'");assert q.fetchone()[0]==0
assets=[];dist=R/'application/frontend/dist'
with httpx.Client(base_url=URL,trust_env=False,timeout=20) as c:
    for p in [dist/'index.html',*sorted((dist/'static').glob('index-*.js'))]:
        r=c.get('/'+str(p.relative_to(dist)));assert r.status_code==200 and r.content==p.read_bytes()
        assets.append(dict(path=str(p.relative_to(dist)),sha256=hashlib.sha256(r.content).hexdigest(),bytes=len(r.content),http_equal=True))
(O/'review-notes-joint-final-readback.json').write_text(json.dumps(dict(identity=identity,container=S['id'],cpu=m['HostConfig']['NanoCpus'],memory=m['HostConfig']['Memory'],tmpfs=m['HostConfig']['Tmpfs'],public_tables=0,unexecuted_tasks=tasks,production_assets=assets),indent=2))
print('Verified exact container caps, no task/node rows, actual HTTP bytes equal production dist')
