#!/usr/bin/env python3
"""Release ONLY the fixed local PoC. No schema migration or production apply.

LOCAL_HA_PREVIEW_FIXTURE is a GitLab file variable containing JSON:
{"scope":"stella-ha-preview","username":"...","password":"...",
 "document_id":"00000000-0000-4000-8000-000000000001","document_contains":"fixture marker"}.
Provision the synthetic account/document out of band in stella_ha_stage.
Credentials travel over docker exec stdin, never logs or command arguments.
The old container is retained, renamed, until stable-port acceptance succeeds.
A hard SIGKILL/host failure during swap requires operator recovery; do not
blindly remove a leftover candidate/rollback container.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid

NAME = 'stella-ha-poc-built-app'
LABEL = 'stella-ha-poc'
SCOPE = '20260915'
REGISTRY = 'gitlab-registry.xiya.live/yaoyao/stellahaven'
BASE = '/opt/hermes-workstation/stella-ha-poc'
MOUNTS = {
    BASE + '/private/stage-app-password': ('/run/secrets/app-password', False),
    BASE + '/private/stage-signing-key': ('/data/secret_key', False),
    BASE + '/private/stage-oidc.json': ('/run/secrets/oidc-private.json', False),
    '/opt/hermes-workstation/stella-ha-integration/deploy/local-ha': ('/local-ha', False),
    BASE + '/resources': ('/app/data', False),
    BASE + '/container-cache': ('/var/cache/stella', True),
    BASE + '/container-tmp': ('/tmp', True),
}
REQUIRED_ENV = {
    'POSTGRES_HOST': '172.25.0.6', 'POSTGRES_PORT': '5432',
    'POSTGRES_DB': 'stella_ha_stage', 'POSTGRES_USER': 'postgres',
    'STELLA_PATRONI_URL': 'http://172.25.0.6:8008',
    'LOCAL_HA_PROFILE': 'manual', 'LOCAL_HA_ENABLE_APP': 'operator-approved',
    'LOCAL_HA_NODE': 'nyarch', 'STELLA_HA_MODE': 'primary-only',
    'STELLA_BLOB_STORAGE': 'postgres', 'STELLA_SHARED_STATE': 'postgres',
    'STELLA_BLOB_CACHE': '/var/cache/stella/blobs',
    'STELLA_OIDC_PRIVATE_KEY_FILE': '/run/secrets/oidc-private.json',
}
ALLOWED_ENV = set(REQUIRED_ENV) | {'PATH', 'GPG_KEY', 'PYTHON_VERSION', 'PYTHON_SHA256', 'PYTHONDONTWRITEBYTECODE'}


class Refused(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def command(port):
    return ['/local-ha/entrypoint.py', 'app', '/app/.venv/bin/uvicorn',
            'main:app', '--host', '127.0.0.1', '--port', str(port)]


def validate_container(c, name=NAME, port=24231):
    require(c['Name'] == '/' + name, 'container name rejected')
    config, host = c['Config'], c['HostConfig']
    require(config.get('Labels', {}).get(LABEL) == SCOPE, 'PoC label required')
    env = {}
    for item in config.get('Env', []):
        key, value = item.split('=', 1)
        require(key not in env and key in ALLOWED_ENV, 'environment not allowlisted')
        env[key] = value
    require(all(env.get(k) == v for k, v in REQUIRED_ENV.items()), 'test-only environment mismatch')
    require(config.get('Entrypoint') == ['/app/.venv/bin/python'] and
            config.get('Cmd') == command(port) and config.get('WorkingDir') == '/app', 'loopback command required')
    require(host.get('ReadonlyRootfs') and host.get('NetworkMode') == 'host' and not host.get('Privileged'), 'unsafe host config')
    require(host.get('Memory') == 1073741824 and host.get('NanoCpus') == 2000000000, 'resource limits required')
    require(host.get('CapDrop') == ['ALL'] and 'no-new-privileges' in host.get('SecurityOpt', []), 'sandbox required')
    for key in ('CapAdd', 'Devices', 'DeviceRequests', 'VolumesFrom', 'PortBindings', 'PidMode', 'UTSMode', 'ExtraHosts', 'Links'):
        require(not host.get(key), 'host feature rejected')
    require(not host.get('PublishAllPorts') and not host.get('AutoRemove'), 'unsafe lifecycle')
    require(host.get('RestartPolicy', {}).get('Name') == 'no', 'restart must be manual')
    require(len(c.get('Mounts', [])) == len(MOUNTS), 'mount count mismatch')
    seen = set()
    for m in c['Mounts']:
        src = m['Source']
        require(src in MOUNTS and src not in seen, 'mount source not allowlisted')
        require(m['Type'] == 'bind' and (m['Destination'], m['RW']) == MOUNTS[src] and
                m.get('Propagation') == 'rprivate', 'mount mode not allowlisted')
        seen.add(src)
    require(c.get('State', {}).get('Running'), 'existing preview must be running')
    return c


def validate_pg(docker):
    pg = docker.inspect('stella-ha-poc-pg-a')
    require(pg['Name'] == '/stella-ha-poc-pg-a' and pg['Config'].get('Labels', {}).get(LABEL) == SCOPE,
            'test PostgreSQL identity rejected')
    require(pg['State']['Running'] and pg['NetworkSettings']['Networks'].get('stella-ha-poc-net', {}).get('IPAddress') == '172.25.0.6',
            'test PostgreSQL address rejected')


def validate_fixture(f):
    require(f.get('scope') == 'stella-ha-preview', 'synthetic fixture scope required')
    require(all(isinstance(f.get(k), str) and f[k] for k in ('username', 'password', 'document_contains')), 'synthetic fixture missing')
    require(isinstance(f.get('document_id'), str) and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', f['document_id']) is not None, 'fixture document UUID required')


def release(docker, sha, fixture):
    require(re.fullmatch('[0-9a-f]{40}', sha) is not None, 'full commit SHA required')
    validate_fixture(fixture)
    old = validate_container(docker.inspect(NAME))
    validate_pg(docker)
    digest, image_id = docker.resolve(sha)
    receipt = {'scope': 'stella-ha-preview', 'commit': sha, 'digest': digest,
               'previous_image': old['Image'], 'url': 'http://127.0.0.1:24231',
               'production_touched': False, 'schema_migrated': False}
    if old['Image'] == image_id:
        docker.health(NAME, 24231, fixture)
        return dict(receipt, status='unchanged', container_id=old['Id'])
    suffix = uuid.uuid4().hex[:12]
    candidate, backup = NAME + '-candidate-' + suffix, NAME + '-rollback-' + suffix
    candidate_created = False
    stopped = renamed = replacement_created = False
    try:
        # Set cleanup intent before calls: a daemon may act then disconnect.
        candidate_created = True
        docker.create(old, candidate, digest, 24232)
        docker.start(candidate)
        validate_container(docker.inspect(candidate), candidate, 24232)
        docker.health(candidate, 24232, fixture)
        docker.remove(candidate)
        candidate_created = False
        # Recheck the exact original ID/config and PG immediately before swap.
        current = validate_container(docker.inspect(NAME))
        require(current['Id'] == old['Id'] and current['Image'] == old['Image'], 'preview changed during release')
        validate_pg(docker)
        stopped = True
        docker.stop(NAME)
        docker.rename(NAME, backup)
        renamed = True
        replacement_created = True
        docker.create(old, NAME, digest, 24231)
        docker.start(NAME)
        live = validate_container(docker.inspect(NAME))
        require(live['Image'] == image_id, 'replacement image mismatch')
        docker.health(NAME, 24231, fixture)
    except Exception:
        if candidate_created:
            try:
                docker.remove(candidate)
            except Exception:
                return dict(receipt, status='cleanup_failed', recovery_container=candidate)
        if stopped:
            try:
                if replacement_created:
                    docker.remove(NAME)
                if renamed:
                    docker.rename(backup, NAME)
                docker.start(NAME)
                restored = validate_container(docker.inspect(NAME))
                require(restored['Id'] == old['Id'] and restored['Image'] == old['Image'], 'rollback image mismatch')
                docker.health(NAME, 24231, fixture)
                return dict(receipt, status='rolled_back', container_id=restored['Id'])
            except Exception:
                return dict(receipt, status='rollback_failed', recovery_container=backup)
        return dict(receipt, status='candidate_failed', container_id=old['Id'])
    # Commit point: never roll back after backup deletion has started.
    try:
        docker.remove(backup)
    except Exception:
        return dict(receipt, status='deployed_cleanup_failed', recovery_container=backup)
    return dict(receipt, status='deployed', container_id=live['Id'])


# Executed inside the tested app's network namespace. No network is used by tests.
HEALTH_CODE = r'''
import json, sys, time, urllib.request, urllib.error, http.cookiejar
f = json.load(sys.stdin)
base = 'http://127.0.0.1:' + str(f.pop('port'))
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None
jar = http.cookiejar.CookieJar()
client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), urllib.request.HTTPCookieProcessor(jar))
def get(path, data=None):
    req = urllib.request.Request(base + path, data=None if data is None else json.dumps(data).encode(), headers={'Content-Type':'application/json'})
    with client.open(req, timeout=5) as r:
        if r.status != 200:
            raise ValueError('status')
        return json.load(r)
try:
    for attempt in range(45):
        try:
            get('/auth/status')
            break
        except Exception:
            if attempt == 44:
                raise
            time.sleep(2)
    try:
        get('/auth/me')
        raise ValueError('unauthenticated access allowed')
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
    user = get('/auth/login', {'username':f['username'], 'password':f['password'], 'remember':False, 'device':'local-ha-preview-ci'})
    try:
        client.addheaders.append(('Cookie','; '.join(c.name+'='+c.value for c in jar)))
        me = get('/auth/me')
        if user.get('id') is None or me.get('id') != user['id']:
            raise ValueError('identity')
        doc = get('/documents/' + str(f['document_id']))
        if doc.get('id') != f['document_id'] or f['document_contains'] not in json.dumps(doc, ensure_ascii=False):
            raise ValueError('document')
    finally:
        get('/auth/logout', {})
except Exception:
    sys.exit(1)
'''


class Docker:
    def call(self, *args, stdin=None, timeout=120):
        # Never expose CalledProcessError (it can contain environment/credentials).
        result = subprocess.run(['docker', *args], input=stdin, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        if result.returncode:
            raise RuntimeError('docker operation failed')
        return result.stdout.strip()

    def inspect(self, name):
        return json.loads(self.call('container', 'inspect', name))[0]

    def resolve(self, sha):
        ref = REGISTRY + ':' + sha
        self.call('pull', ref, timeout=300)
        image = json.loads(self.call('image', 'inspect', ref))[0]
        digests = [d for d in image.get('RepoDigests', []) if re.fullmatch(re.escape(REGISTRY) + '@sha256:[0-9a-f]{64}', d)]
        require(len(digests) == 1, 'unique immutable registry digest required')
        return digests[0], image['Id']

    def create(self, old, name, digest, port):
        args = ['create', '--name', name, '--label', LABEL + '=' + SCOPE,
                '--network', 'host', '--memory', '1g', '--cpus', '2', '--read-only',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--init',
                '--restart', 'no', '--log-opt', 'max-size=50m', '--log-opt', 'max-file=3',
                '--workdir', '/app', '--entrypoint', '/app/.venv/bin/python']
        for source, (dest, rw) in MOUNTS.items():
            args += ['--mount', 'type=bind,src=' + source + ',dst=' + dest + ('' if rw else ',readonly')]
        # Only explicitly approved environment is copied. No passwords in argv.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8') as envfile:
            envfile.write('\n'.join(old['Config']['Env']) + '\n')
            envfile.flush()
            args += ['--env-file', envfile.name, digest, *command(port)]
            self.call(*args)
        # Reject inherited image ENV/mounts before running any image code.
        created = self.inspect(name)
        created['State']['Running'] = True  # validation only; still stopped
        validate_container(created, name, port)

    def health(self, name, port, fixture):
        self.call('exec', '-i', name, '/app/.venv/bin/python', '-c', HEALTH_CODE,
                  stdin=json.dumps(dict(fixture, port=port)), timeout=360)
        require(self.inspect(name)['State']['Running'], 'container exited after health check')

    def stop(self, name):
        self.call('stop', '--time', '20', name)

    def start(self, name):
        self.call('start', name)

    def rename(self, old, new):
        self.call('rename', old, new)

    def remove(self, name):
        # Only names minted by this transaction (or fixed NAME during rollback).
        result = subprocess.run(['docker', 'container', 'inspect', name], capture_output=True, text=True, timeout=30)
        if result.returncode:
            if 'No such container' in result.stderr or 'No such object' in result.stderr:
                return
            raise RuntimeError('cleanup inspection failed')
        c = json.loads(result.stdout)[0]
        require(c['Config'].get('Labels', {}).get(LABEL) == SCOPE and
                (name == NAME or name.startswith(NAME + '-candidate-') or name.startswith(NAME + '-rollback-')), 'cleanup target rejected')
        self.call('rm', '-f', c['Id'])
        result = subprocess.run(['docker', 'container', 'inspect', c['Id']], capture_output=True, text=True, timeout=30)
        require(result.returncode != 0 and ('No such' in result.stderr), 'cleanup not verified')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--fixture', required=True)
    args = parser.parse_args()
    def interrupted(signum, frame):
        # A second signal must not interrupt best-effort rollback.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise RuntimeError('interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        require(os.environ.get('CI_COMMIT_BRANCH') == 'feature/local-ha-20260915', 'dedicated preview branch required')
        require(os.environ.get('CI_COMMIT_SHA') == args.commit, 'CI commit mismatch')
        require(os.environ.get('STELLA_DEPLOY_TARGET') == 'local-ha-preview', 'preview opt-in required')
        result = release(Docker(), args.commit, json.loads(Path(args.fixture).read_text()))
    except Exception as exc:
        result = {'scope': 'stella-ha-preview', 'status':'refused', 'error_type':type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in ('deployed', 'unchanged') else 1


if __name__ == '__main__':
    sys.exit(main())
