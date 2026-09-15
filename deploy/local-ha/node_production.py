#!/usr/bin/env python3
"""Ephemeral app-only SSH helper. Input/output JSON; never logs credentials.
No PG lifecycle, SQL writes, migration, role API writes, force, or reboot.
Old containers stay as stopped rollback backups after health success. Existing
candidate/rollback names are never swept; uncertain outcomes require inspection.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

NODES = {'nyarch':'10.66.0.2', 'nas':'10.66.0.3'}
REGISTRY = 'gitlab-registry.xiya.live/yaoyao/stellahaven'
BASE = '/var/lib/stella-ha-app-shadow-20260916/'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def run(args, data=None, timeout=90, env=None):
    p = subprocess.run(args, input=data, capture_output=True, text=True, timeout=timeout, env=env)
    require(p.returncode == 0, 'command failed: ' + args[0])
    return p.stdout.strip()


# Read-only SQL: both node endpoints, independent of HTTP readiness gate.
# Executed in the existing/candidate app to use its installed psycopg2. Password
# is read inside the container; no docker-inspect environment or key is returned.
PROBE = r'''
import hashlib,json,os,sys,urllib.request,urllib.error
from pathlib import Path
import psycopg2
p=json.load(sys.stdin)
from alembic.config import Config
from alembic.script import ScriptDirectory
if ScriptDirectory.from_config(Config('/app/alembic.ini')).get_heads() != [p['revision']]:
    raise ValueError('image schema revision mismatch')
client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def http(url):
    try:
        with client.open(url,timeout=3) as r: return r.status,json.load(r)
    except urllib.error.HTTPError as e: return e.code,{}
roles={}
for node,host in {'nyarch':'10.66.0.2','nas':'10.66.0.3'}.items():
    code,pat=http('http://'+host+':24808/patroni')
    assert code==200 and pat['state']=='running' and pat['role'] in ('master','primary','replica')
    code,_=http('http://'+host+':24808/primary')
    with psycopg2.connect(host=host,port=24532,dbname='stella',user=os.environ.get('POSTGRES_USER','stalla'),password=Path('/run/secrets/app-password').read_text().strip(),connect_timeout=3,options='-c statement_timeout=3000') as c:
        with c.cursor() as cur:
            cur.execute("SELECT pg_is_in_recovery(), current_setting('transaction_read_only') = 'on'")
            recovery,standby=cur.fetchone()
            cur.execute('SELECT version_num FROM alembic_version')
            assert cur.fetchall()==[(p['revision'],)]
    primary=pat['role'] in ('master','primary')
    assert (recovery,standby,code)==((False,False,200) if primary else (True,True,503))
    roles[node]=primary
assert sum(roles.values())==1
if p.get('expected_roles') is not None: assert roles==p['expected_roles']
root=Path('/app/data').resolve()
raw=(root/'manifest.json').read_bytes()
assert hashlib.sha256(raw).hexdigest()==p['manifest']
files=json.loads(raw)['files']; assert isinstance(files,dict) and files
for name,record in files.items():
    path=root/name
    assert not Path(name).is_absolute() and '..' not in Path(name).parts
    assert path.resolve().is_relative_to(root) and path.is_file() and not path.is_symlink()
    assert path.stat().st_size==record['size']
    with path.open('rb') as f: assert hashlib.file_digest(f,'sha256').hexdigest()==record['sha256']
signing=hashlib.sha256(Path('/data/secret_key').read_text().strip().encode()).hexdigest()
assert signing==p['signing']
result=dict(roles=roles,manifest=p['manifest'],signing=signing,revision=p['revision'])
if p.get('port'):
    live,_=http('http://127.0.0.1:'+str(p['port'])+'/live')
    ready,_=http('http://127.0.0.1:'+str(p['port'])+'/ready-primary')
    assert live==200 and ready==(200 if roles[p['node']] else 503)
    result['http']={'live':live,'ready_primary':ready}
print(json.dumps(result))
'''

# Fixed application start; does not invoke image entrypoint (may migrate DB).
START = "import os,sys; from pathlib import Path; os.environ['POSTGRES_PASSWORD']=Path('/run/secrets/app-password').read_text().strip(); import uvicorn; uvicorn.run('main:app',host='127.0.0.1',port=int(sys.argv[1]))"


def port_free(port):
    import socket
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', port))


def validate_environment(env):
    require(env.get('PGOPTIONS') == '-c statement_timeout=30000', 'production PGOPTIONS mismatch')
    forbidden = {'STELLA_SECRET_KEY', 'PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER',
                 'PGPASSWORD', 'PGSERVICE', 'PGSERVICEFILE', 'PGPASSFILE'}
    require(not forbidden.intersection(env), 'unapproved database/signing override')
    require(not any('\n' in k or '\n' in v or '\r' in v for k,v in env.items()), 'unsafe env-file value')


def same_image_content(a, b):
    """Engine IDs may identify index/manifest/config; compare resolved content."""
    keys = ('RootFS', 'Config', 'Architecture', 'Os')
    return all(k in a and k in b and a[k] == b[k] for k in keys)


class Node:
    def __init__(self, request):
        self.r = request
        self.node = request['node']
        require(self.node in NODES, 'node rejected')
        self.inv = request['inventory']
        require(self.inv.get('scope') == 'stella-production-app-v1' and self.inv.get('forward_compatible') is True, 'inventory approval required')
        self.cfg = self.inv['nodes'][self.node]
        require(self.cfg['host'] == NODES[self.node], 'node address mismatch')
        self.name = 'stella-app-shadow-' + self.node
        self.expected = request.get('expected_roles')

    def inspect(self, name):
        return json.loads(run(['docker','inspect',name]))[0]

    def validate(self, c, name=None, port=25131, replacement=False):
        require(c['Name'] == '/' + (name or self.name) and c['State']['Running'], 'app name/state mismatch')
        cfg, host = c['Config'], c['HostConfig']
        require(cfg.get('Entrypoint') == ['/app/.venv/bin/python'] and cfg.get('WorkingDir') == '/app', 'entrypoint/workdir mismatch')
        require(cfg.get('Cmd') == (['-c',START,str(port)] if replacement else self.cfg['command']), 'startup command mismatch')
        env = dict(x.split('=',1) for x in cfg['Env'])
        validate_environment(env)
        require(len(env) == len(cfg['Env']), 'duplicate environment')
        for k,v in {'POSTGRES_HOST':'127.0.0.1','POSTGRES_PORT':'24532','POSTGRES_DB':'stella',
                    'STELLA_HA_MODE':'primary-only','STELLA_BLOB_STORAGE':'postgres','STELLA_SHARED_STATE':'postgres',
                    'STELLA_PATRONI_URL':'http://' + NODES[self.node] + ':24808'}.items():
            require(env.get(k) == v, 'required environment mismatch: ' + k)
        require(not any(k in env for k in ('POSTGRES_PASSWORD','DATABASE_URL','DATABASE_URI','SQLALCHEMY_DATABASE_URI','PYTHONPATH','LD_PRELOAD')), 'unsafe environment override')
        require(host.get('NetworkMode') == 'host' and host.get('ReadonlyRootfs') is True and not host.get('Privileged'), 'host isolation mismatch')
        require(host.get('Memory') == self.cfg['memory'] and host.get('NanoCpus') == self.cfg['nano_cpus'] and
                0 < host['Memory'] <= 4294967296 and 0 < host['NanoCpus'] <= 4000000000, 'resource limits mismatch')
        require(host.get('CapDrop') == ['ALL'] and 'no-new-privileges' in host.get('SecurityOpt', []), 'sandbox mismatch')
        for k in ('CapAdd','Devices','DeviceRequests','VolumesFrom','PortBindings','PidMode','UTSMode','ExtraHosts','Links','Binds','Tmpfs'):
            # Binds are an alternative encoding of the verified Mounts, handled below.
            if k != 'Binds': require(not host.get(k), 'unsafe host feature: ' + k)
        require(not host.get('PublishAllPorts') and not host.get('AutoRemove'), 'unsafe lifecycle')
        expected = sorted(self.cfg['mounts'], key=lambda m:m['Destination'])
        actual = []
        for m in c['Mounts']:
            src = m['Source']; dest = m['Destination']
            require(m['Type'] == 'bind' and m.get('Propagation') == 'rprivate', 'bind mount only')
            require(src.startswith(BASE) and str(Path(src).resolve()).startswith(BASE) and '..' not in Path(src).parts and ',' not in src, 'mount source escaped approved bundle')
            require(dest in {'/app/data','/var/cache/stella','/tmp','/scratch','/data','/data/secret_key','/run/secrets/app-password','/run/secrets/oidc-private.json','/shadow-start.py'}, 'mount destination rejected')
            require(dest in {'/var/cache/stella','/tmp','/scratch','/data'} or not m['RW'], 'secret/resource writable')
            actual.append({k:m[k] for k in ('Source','Destination','RW')})
        require(sorted(actual,key=lambda m:m['Destination']) == expected, 'exact mount inventory mismatch')
        startup = next(m['Source'] for m in actual if m['Destination']=='/shadow-start.py')
        require(hashlib.sha256(Path(startup).read_bytes()).hexdigest() == self.cfg['startup_sha256'], 'startup hash mismatch')
        return c

    def pg_guard(self):
        pg = self.inspect('stella-pg-' + self.node + '-runtime')
        require(pg['State']['Running'] and pg['HostConfig']['NetworkMode'] == 'host', 'runtime PG identity/state')
        require(any(m['Source'] == '/var/lib/stella-ha-runtime/' + self.node + '/pgdata' and
                    m['Destination'] == '/var/lib/postgresql/data' for m in pg['Mounts']) or
                any(m['Source'] == '/var/lib/stella-ha-runtime/' + self.node + '/pgdata' and
                    'pgdata' in m['Destination'] for m in pg['Mounts']), 'runtime PGDATA identity')
        # Patroni scope is checked from its live configuration, read-only.
        config = '/run/nyarch-runtime-patroni.yml' if self.node == 'nyarch' else '/run/patroni.yml'
        check = "import yaml; d=yaml.safe_load(open(" + repr(config) + ")); print(d.get('scope',''))"
        scope = run(['docker','exec',pg['Id'],'python3','-c',check])
        require(scope == 'stella-pg', 'PG scope mismatch')
        return pg['Id']

    def probe(self, name=None, port=25131, expected=True):
        data = {'node':self.node,'port':port,'revision':self.inv['schema_revision'],
                'manifest':self.inv['manifest_sha256'],'signing':self.inv['signing_sha256'],
                'expected_roles':self.expected if expected else None}
        return json.loads(run(['docker','exec','-i',name or self.name,'/app/.venv/bin/python','-c',PROBE],json.dumps(data),timeout=90))

    def health(self, name, port, expected=True):
        for i in range(30):
            try: return self.probe(name,port,expected)
            except Exception:
                if i == 29: raise
                time.sleep(2)

    def guard(self, probe_name=None):
        require(self.pg_guard() == self.pg_id, 'PG runtime changed during release')
        return self.probe(probe_name,port=None)

    def action(self, *args, probe_name=None):
        self.guard(probe_name)
        result = run(['docker',*args])
        self.guard(probe_name)
        return result

    def create(self, old, name, image_id, port):
        port_free(port)
        restart = old['HostConfig']['RestartPolicy']['Name'] if port == 25131 else 'no'
        require(restart in ('no', 'always', 'unless-stopped'), 'unsupported restart policy')
        args = ['docker','create','--pull=never','--name',name,'--network=host','--read-only',
                '--init','--cap-drop=ALL','--security-opt=no-new-privileges','--memory',str(self.cfg['memory']),
                '--cpus',str(self.cfg['nano_cpus']/1000000000),'--restart='+restart,'--workdir=/app',
                '--entrypoint=/app/.venv/bin/python']
        for m in self.cfg['mounts']:
            args += ['--mount','type=bind,src='+m['Source']+',dst='+m['Destination']+(',readonly' if not m['RW'] else '')]
        # Env is existing approved config, not registry credentials; use stdin
        # Docker --env-file /dev/stdin to avoid passwords in process arguments.
        args += ['--env-file','/dev/stdin']
        for k,v in (old['Config'].get('Labels') or {}).items():
            args += ['--label',k+'='+v]
        args += [image_id,'-c',START,str(port)]
        return run(args, '\n'.join(old['Config']['Env'])+'\n')

    def image_matches(self, container_image, expected_info):
        actual = json.loads(run(['docker','image','inspect',container_image]))[0]
        return actual.get('Id') == expected_info.get('Id') and same_image_content(actual, expected_info)

    def release(self):
        old = self.inspect(self.name)
        new_style = old['Config'].get('Cmd') == ['-c',START,'25131']
        self.validate(old,replacement=new_style)
        self.pg_id = self.pg_guard()
        initial = self.probe()
        image = self.r['image']
        require(re.fullmatch(re.escape(REGISTRY)+'@sha256:[0-9a-f]{64}', image), 'immutable image required')
        require(self.expected == initial['roles'], 'initial roles mismatch')
        self.guard()
        # Auth lifetime is limited to pull. Never reuse ~/.docker/config.json.
        with tempfile.TemporaryDirectory(prefix='stella-release-docker-') as tmp:
            env = dict(os.environ, DOCKER_CONFIG=tmp)
            require(self.r.get('registry_user') and self.r.get('registry_password'), 'registry credentials required')
            run(['docker','login','gitlab-registry.xiya.live','-u',self.r['registry_user'],'--password-stdin'],self.r['registry_password'],env=env)
            run(['docker','pull',image],timeout=240,env=env)
        info = json.loads(run(['docker','image','inspect',image]))[0]
        image_id = info['Id']
        require(re.fullmatch('sha256:[0-9a-f]{64}',image_id), 'invalid local image identity')
        require(image in info.get('RepoDigests',[]), 'pulled digest identity missing')
        self.guard()
        base = dict(node=self.node,digest=image,image_id=image_id,previous_id=old['Id'],roles=initial['roles'])
        if self.image_matches(old['Image'], info):
            return dict(base,status='unchanged',container_id=old['Id'],http=self.health(self.name,25131)['http'])
        suffix = uuid.uuid4().hex[:12]
        candidate, backup = self.name+'-candidate-'+suffix, self.name+'-rollback-'+suffix
        candidate_id = replacement_id = None
        stopped = renamed = False
        try:
            self.guard()
            stage = 'candidate-create'
            candidate_id = self.create(old,candidate,image_id,25132)
            self.action('start',candidate)
            self.validate(self.inspect(candidate),candidate,25132,True)
            require(self.image_matches(self.inspect(candidate)['Image'], info), 'candidate local image mismatch')
            stage = 'candidate-health'
            self.health(candidate,25132)
            self.guard(candidate)
            require(self.inspect(self.name)['Id'] == old['Id'], 'old app changed')
            # Candidate remains running as read-only role-probe carrier while
            # the old app is stopped, renamed and replaced at its stable port.
            stage = 'stop-old'
            stopped = True
            self.action('stop','--time','30',old['Id'],probe_name=candidate)
            self.action('rename',old['Id'],backup,probe_name=candidate)
            renamed = True
            self.guard(candidate)
            stage = 'stable-create'
            replacement_id = self.create(old,self.name,image_id,25131)
            self.action('start',replacement_id,probe_name=candidate)
            stage = 'stable-validate'
            live = self.validate(self.inspect(self.name),replacement=True)
            require(self.image_matches(live['Image'], info), 'replacement image mismatch')
            stage = 'stable-health'
            health = self.health(self.name,25131)
            self.guard()
            self.action('stop',candidate_id)
            self.action('rm',candidate_id)
            candidate_id = None
            # Backup intentionally retained even after commit; no broad cleanup.
            return dict(base,status='deployed',container_id=live['Id'],http=health['http'],backup=backup)
        except Exception as original_error:
            # Rollback must be possible even after role drift. No PG operation.
            # Remove ONLY IDs created by this attempt, never a namesake unknown ID.
            try:
                if replacement_id:
                    run(['docker','stop',replacement_id]); run(['docker','rm',replacement_id])
                if stopped:
                    current_old = self.inspect(old['Id'])
                    if current_old['Name'] == '/' + backup:
                        run(['docker','rename',old['Id'],self.name])
                    else:
                        require(current_old['Name'] == '/' + self.name, 'rollback original identity changed')
                    run(['docker','start',old['Id']])
                    restored = self.validate(self.inspect(self.name),replacement=new_style)
                    require(restored['Id'] == old['Id'] and restored['Image'] == old['Image'], 'rollback identity failed')
                    health = self.health(self.name,25131,expected=False)
                else:
                    health = self.health(self.name,25131,expected=False)
                if candidate_id:
                    run(['docker','stop',candidate_id]); run(['docker','rm',candidate_id])
                return dict(base,status='rolledback' if stopped else 'blocked',container_id=old['Id'],http=health['http'],reason='release guard/health failed', failed_stage=locals().get('stage','preflight'), error_type=type(original_error).__name__, error_errno=getattr(original_error,'errno',None))
            except Exception:
                return dict(base,status='blocked',reason='rollback incomplete; manual recovery required',backup=backup,candidate=candidate)

    def execute(self):
        if self.r['op'] == 'probe':
            c = self.inspect(self.name)
            self.validate(c,replacement=c['Config'].get('Cmd') == ['-c',START,'25131'])
            self.pg_guard()
            result = self.probe()
            return dict(result,status='healthy',node=self.node,primary=result['roles'][self.node],container_id=c['Id'],image_id=c['Image'])
        require(self.r['op'] == 'release', 'operation rejected')
        # Host-local lock prevents other release jobs/processes from overlapping.
        # CI additionally serializes the entire two-node transaction.
        with open('/run/lock/stella-production-app-release.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self.release()


if __name__ == '__main__':
    try:
        request = globals().get('REQUEST')
        if request is None: request = json.load(sys.stdin)
        print(json.dumps(Node(request).execute()))
    except Exception as exc:
        print(json.dumps({'status':'blocked','reason':str(exc) if isinstance(exc,ValueError) else type(exc).__name__}))
