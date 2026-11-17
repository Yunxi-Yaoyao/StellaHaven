"""Remove only the exact labelled fixture; keep public cleanup evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    private=Path(sys.argv[1])
    receipt=json.loads(private.read_text())
    actual=json.loads(subprocess.check_output(['docker','inspect',receipt['id']]))[0]
    assert actual['Id']==receipt['id'] and actual['State']['Pid']==receipt['pid']
    assert actual['Config']['Labels']['io.stella.test.owner']==receipt['owner']
    assert actual['HostConfig']['NetworkMode']=='none' and not actual['NetworkSettings']['Ports']
    python='/opt/hermes-workstation/stella-ui-notes-integration-20261017/.venv/bin/python'
    code="""
import json,os,psycopg2
c=psycopg2.connect(host='127.0.0.1',port=5432,dbname=os.environ['POSTGRES_DB'],user=os.environ['POSTGRES_USER'],password=os.environ['POSTGRES_PASSWORD'])
with c,c.cursor() as q:
 q.execute('SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port()'); identity=q.fetchone()
 assert identity==(os.environ['POSTGRES_DB'],os.environ['POSTGRES_USER'],'127.0.0.1',5432)
 q.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'"); tables=q.fetchall(); assert tables==[],tables
 q.execute('SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=%s)',(os.environ['RESTORE_DB'],)); assert q.fetchone()[0] is False
print(json.dumps({'identity_verified':True,'public_tables':[],'restore_database_absent':True}))
c.close()
"""
    env={'PATH':'/usr/bin:/usr/sbin:/bin','HOME':receipt['root'],'TMPDIR':receipt['root'],
         'POSTGRES_DB':receipt['database'],'POSTGRES_USER':receipt['user'],'POSTGRES_PASSWORD':receipt['password'],
         'RESTORE_DB':receipt['restore_db']}
    pre=subprocess.run(['nsenter','-t',str(receipt['pid']),'-n',python,'-c',code],env=env,cwd=receipt['root'],capture_output=True,text=True,check=True)
    result=json.loads(pre.stdout)
    subprocess.run(['docker','rm','-f',receipt['id']],capture_output=True,check=True)
    absent=subprocess.run(['docker','inspect',receipt['id']],capture_output=True,text=True)
    assert absent.returncode!=0 and 'no such' in absent.stderr.lower()
    root=Path(receipt['root'])
    removed=0
    for path in root.rglob('password'):
        if path.is_file() and not path.is_symlink() and path.read_text()==receipt['password']:
            path.unlink();removed+=1
    private.unlink()
    result.update(container_id=receipt['id'],owner=receipt['owner'],network='none',published_ports={},
                  exact_container_absent=True,private_receipt_removed=not private.exists(),password_files_removed=removed)
    (root/'cleanup.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':main()
