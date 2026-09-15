#!/usr/bin/env python3
"""App-only production release. No PostgreSQL changes or role promotion.

Protected GitLab File variables: STELLA_PRODUCTION_INVENTORY, _SSH_KEY,
_KNOWN_HOSTS. Inventory JSON is operator-owned (NEVER generated from inspect):
{"scope":"stella-production-app-v1","nodes":{"nyarch":{"host":"10.66.0.2",
"alias":"stella-prod-nyarch","mounts":[{"Source":"...","Destination":"...",
"RW":false}],"command":["/shadow-start.py"],"memory":1073741824,
"nano_cpus":2000000000,"startup_sha256":"<64 hex>"},"nas":{...}},
"manifest_sha256":"<64 hex>","signing_sha256":"<64 hex>",
"schema_revision":"b7c8d9e0f1a2","forward_compatible":true}
Mounts must describe the complete existing bind set, not PGDATA. The schema
revision and resource manifest are checked only; no migration/copy is allowed.
--validate-pack is offline; --dry-run does read-only SSH probes, no pull/login.
A sampled role guard is NOT fencing. Hard kill/SSH loss may require recovery;
receipts preserve each node's status rather than claim atomic cross-node rollback.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

NODES = {'nyarch': '10.66.0.2', 'nas': '10.66.0.3'}
REGISTRY = 'gitlab-registry.xiya.live/yaoyao/stellahaven'
BASE = '/var/lib/stella-ha-app-shadow-20260916/'


def require(value, message):
    if not value:
        raise ValueError(message)


def validate_inventory(inv):
    require(inv.get('scope') == 'stella-production-app-v1', 'production inventory scope')
    require(inv.get('forward_compatible') is True, 'explicit forward compatibility required')
    require(re.fullmatch('[a-zA-Z0-9_]{1,64}', inv.get('schema_revision', '')), 'schema revision required')
    for key in ('manifest_sha256', 'signing_sha256'):
        require(re.fullmatch('[0-9a-f]{64}', inv.get(key, '')), key + ' required')
    require(set(inv.get('nodes', {})) == set(NODES), 'exact two-node inventory required')
    for node, ip in NODES.items():
        item = inv['nodes'][node]
        require(item.get('host') == ip and item.get('alias') == 'stella-prod-' + node, 'pinned node/SSH identity')
        require(re.fullmatch('[0-9a-f]{64}', item.get('startup_sha256', '')), 'trusted startup hash required')
        require(isinstance(item.get('command'), list) and item['command'] and
                all(isinstance(x, str) for x in item['command']) and '/shadow-start.py' in item['command'], 'trusted existing startup command')
        require(type(item.get('memory')) is int and 0 < item['memory'] <= 4294967296, 'memory bound')
        require(type(item.get('nano_cpus')) is int and 0 < item['nano_cpus'] <= 4000000000, 'CPU bound')
        mounts = item.get('mounts', [])
        destinations = set()
        for mount in mounts:
            src, dest = mount.get('Source', ''), mount.get('Destination', '')
            require(src.startswith(BASE) and '..' not in Path(src).parts and '\n' not in src and ',' not in src, 'mount source outside production app bundle')
            require(dest in {'/app/data', '/var/cache/stella', '/tmp', '/scratch', '/data', '/data/secret_key', '/run/secrets/app-password', '/run/secrets/oidc-private.json', '/shadow-start.py'}, 'mount destination rejected')
            require(dest not in destinations and type(mount.get('RW')) is bool, 'duplicate/invalid mount')
            if dest not in {'/var/cache/stella', '/tmp', '/scratch', '/data'}:
                require(mount['RW'] is False, 'resource/secret/startup must be read-only')
            destinations.add(dest)
        require((('/tmp' in destinations) or ('/scratch' in destinations)) and {'/app/data', '/data/secret_key', '/run/secrets/app-password', '/run/secrets/oidc-private.json', '/shadow-start.py'} <= destinations, 'required mounts missing')
    return inv


class SSHTransport:
    def __init__(self, inventory, key, known_hosts, image):
        self.inventory, self.key, self.known_hosts, self.image = inventory, key, known_hosts, image
        require(Path(key).is_file() and Path(known_hosts).is_file(), 'SSH File variables required')
        self.source = (Path(__file__).with_name('node_production.py')).read_text()

    def call(self, node, op, **extra):
        cfg = self.inventory['nodes'][node]
        payload = dict(inventory=self.inventory, node=node, op=op, image=self.image, **extra)
        if op == 'release':
            payload['registry_user'] = os.environ.get('CI_REGISTRY_USER', '')
            payload['registry_password'] = os.environ.get('CI_REGISTRY_PASSWORD', '')
        # Program and JSON both travel via encrypted stdin. No remote install,
        # shell secret interpolation, persistent registry auth, or ssh config.
        bootstrap = 'import sys,json,base64; p=json.load(sys.stdin); exec(compile(base64.b64decode(p["source"]),"<stella-release>","exec"), {"__name__":"__main__","REQUEST":p["request"]})'
        argv = ['ssh', '-F', '/dev/null', '-i', self.key, '-o', 'IdentitiesOnly=yes',
                '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
                '-o', 'UserKnownHostsFile=' + self.known_hosts, '-o', 'HostKeyAlias=' + cfg['alias'],
                '-o', 'GlobalKnownHostsFile=/dev/null', ('root' if node == 'nyarch' else 'yaoyao') + '@' + cfg['host'], 'python3 -c ' + shlex.quote(bootstrap)]
        try:
            proc = subprocess.run(argv, input=json.dumps({'source':base64.b64encode(self.source.encode()).decode(), 'request':payload}),
                                  capture_output=True, text=True, timeout=600)
            require(proc.returncode == 0, 'SSH/node failed; readback required (stderr suppressed)')
            result = json.loads(proc.stdout)
            require(result.get('status') in {'healthy','deployed','unchanged','rolledback','blocked'}, 'invalid node receipt')
            return result
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            raise ValueError('SSH outcome unknown; operator recovery required') from None


def orchestrate(transport, inv, dry_run=False):
    receipt = {'status':'blocked', 'nodes':{}, 'schema_migrated':False, 'pg_mutated':False}
    def snapshot(expected=None):
        states = {n:transport.call(n, 'probe') for n in NODES}
        for n, s in states.items():
            require(s.get('status') == 'healthy' and s.get('node') == n, 'node probe failed')
            require((s['manifest'], s['signing'], s['revision']) ==
                    (inv['manifest_sha256'], inv['signing_sha256'], inv['schema_revision']), 'resource/signing/schema mismatch')
        roles = {n:s['primary'] for n,s in states.items()}
        require(all(type(x) is bool for x in roles.values()) and sum(roles.values()) == 1, 'exactly one primary required')
        require(all(s.get('roles') == roles for s in states.values()), 'peer role observations disagree')
        require(expected is None or roles == expected, 'roles drifted; no further deployment')
        receipt['roles'] = roles
        return roles
    try:
        roles = snapshot()
        if dry_run:
            return dict(receipt, status='unchanged', read_only=True)
        for node in sorted(NODES, key=lambda n:roles[n]):
            snapshot(roles)
            result = transport.call(node, 'release', expected_roles=roles)
            receipt['nodes'][node] = result
            require(result['status'] in ('deployed', 'unchanged'), 'node release did not complete')
            snapshot(roles)
        receipt['status'] = 'deployed' if any(s['status']=='deployed' for s in receipt['nodes'].values()) else 'unchanged'
    except Exception as exc:
        receipt['reason'] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        if receipt['nodes'] and all(s['status'] in ('rolledback','unchanged') for s in receipt['nodes'].values()):
            receipt['status'] = 'rolledback'
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', default=os.environ.get('STELLA_PRODUCTION_INVENTORY'))
    parser.add_argument('--image', default=os.environ.get('STELLA_PRODUCTION_IMAGE'))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--validate-pack', action='store_true')
    args = parser.parse_args()
    if args.validate_pack:
        compile(Path(__file__).with_name('node_production.py').read_text(), 'node_production.py', 'exec')
        print(json.dumps({'status':'validated', 'production_executed':False}))
        return 0
    try:
        require(os.environ.get('CI_COMMIT_BRANCH') == 'master' and os.environ.get('CI_COMMIT_REF_PROTECTED') == 'true' and
                os.environ.get('STELLA_DEPLOY_TARGET') == 'local-ha', 'protected master/local-ha required')
        require(re.fullmatch(re.escape(REGISTRY) + '@sha256:[0-9a-f]{64}', args.image or ''), 'full immutable image digest required')
        inv = validate_inventory(json.loads(Path(args.inventory).read_text()))
        # Explicit CI approval binds inventory to this release's schema/resource.
        require(os.environ.get('STELLA_EXPECTED_SCHEMA') == inv['schema_revision'], 'CI schema approval mismatch')
        require(os.environ.get('STELLA_RESOURCE_MANIFEST_SHA256') == inv['manifest_sha256'], 'CI resource approval mismatch')
        t = SSHTransport(inv, os.environ['STELLA_PRODUCTION_SSH_KEY'], os.environ['STELLA_PRODUCTION_KNOWN_HOSTS'], args.image)
        result = orchestrate(t, inv, args.dry_run)
    except Exception as exc:
        result = {'status':'blocked', 'reason':str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in ('deployed','unchanged') else 1

if __name__ == '__main__':
    sys.exit(main())
