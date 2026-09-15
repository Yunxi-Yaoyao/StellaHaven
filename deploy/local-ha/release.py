#!/usr/bin/env python3
"""Fail-closed, standby-first local HA app release. No DB/ingress mutation."""
import re
import json
import subprocess


def switchover_guard(snapshot, *, requested=False):
    if requested:
        raise Refused('switchover disabled: independent fencing availability has not been accepted')
    return 'not-requested'


class SSHTransport:
    """Read-only probes through pre-provisioned, pinned SSH aliases."""
    def __init__(self, hosts, ssh_config=None):
        if set(hosts) != {'nyarch', 'nas'} or len(set(hosts.values())) != 2:
            raise Refused('two distinct inventory aliases required')
        if any(not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', h) for h in hosts.values()):
            raise Refused('SSH inventory must contain aliases, not commands or options')
        self.hosts = hosts
        self.ssh_config = ssh_config

    def request(self, node, payload):
        command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                   '-o', 'ConnectTimeout=5']
        if self.ssh_config:
            command += ['-F', self.ssh_config]
        command += [self.hosts[node], 'python3 /opt/stella-local-ha/node.py']
        result = subprocess.run(command, input=json.dumps(payload), text=True,
                                capture_output=True, check=True, timeout=30)
        return json.loads(result.stdout)

    def snapshot(self):
        nodes = []
        for name in ('nyarch', 'nas'):
            report = self.request(name, {'op': 'probe'})
            if report.get('name') != name:
                raise Refused('remote node identity disagrees with inventory')
            nodes.append(report)
        return {'scope': SCOPE, 'profile': 'manual', 'nodes': nodes}

    def update(self, node, image, expected_image):
        raise Refused('host writes disabled until independent fencing acceptance; read-only transport only')

SCOPE = 'stella-local-ha-v1'
IMAGE_RE = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9._:/-]*@sha256:[0-9a-f]{64}\Z')


class Refused(ValueError):
    pass


def image_ref(value):
    if not isinstance(value, str) or not IMAGE_RE.fullmatch(value):
        raise Refused('immutable repository@sha256 digest required')
    return value


def plan(snapshot, image):
    image_ref(image)
    if snapshot.get('scope') != SCOPE or snapshot.get('profile') != 'manual':
        raise Refused('only isolated manual profile is implemented; automatic fencing NOT verified')
    nodes = snapshot.get('nodes', [])
    if len(nodes) != 2 or {n.get('name') for n in nodes} != {'nyarch', 'nas'}:
        raise Refused('exactly nyarch and nas required; third Shanghai node is deferred')
    for node in nodes:
        image_ref(node.get('image'))
        if node.get('resources_ok') is not True or node.get('app_ok') is not True:
            raise Refused('resources or app liveness unavailable')
        role = (node.get('primary_http'), node.get('in_recovery'), node.get('read_only'))
        if role not in [(200, False, False), (503, True, True)]:
            raise Refused('Patroni /primary and SQL role disagree')
        if type(node.get('in_recovery')) is not bool or type(node.get('read_only')) is not bool:
            raise Refused('SQL role must use JSON booleans')
    for field in ('signing_key_id', 'bundle_id'):
        if not nodes[0].get(field) or nodes[0][field] != nodes[1].get(field):
            raise Refused(field + ' mismatch')
    primaries = [n for n in nodes if n['primary_http'] == 200]
    if len(primaries) != 1:
        raise Refused('exactly one live writable primary required')
    primary = primaries[0]
    standby = next(n for n in nodes if n['name'] != primary['name'])
    return {'scope': SCOPE, 'status': 'planned', 'primary': primary['name'],
            'automatic_failover': False,
            'actions': [{'op': 'update-app', 'node': standby['name'],
                         'image': image, 'original_image': standby['image']}],
            'next': 'operator-planned-switchover-required'}


def run(transport, image, *, apply=False, compatible=False):
    result = plan(transport.snapshot(), image)
    if not apply:
        return result
    if compatible is not True:
        raise Refused('reviewed backward-compatible schema contract required for mixed-version release')
    action = result['actions'][0]
    if plan(transport.snapshot(), image) != result:
        raise Refused('live topology or image changed since planning; re-plan')
    try:
        transport.update(action['node'], image, action['original_image'])
        after = transport.snapshot()
        verified = plan(after, image)
        node = next(n for n in after['nodes'] if n['name'] == action['node'])
        if node['image'] != image or verified['primary'] != result['primary']:
            raise Refused('post-update image or role verification failed')
        result['status'] = 'standby-updated'
    except Exception as exc:
        # Never roll back schema, storage, PG, routing, or a newly promoted app.
        result.update(status='manual-intervention', error=type(exc).__name__)
        try:
            current = transport.snapshot()
            node = next(n for n in current['nodes'] if n['name'] == action['node'])
            if (node['primary_http'], node['in_recovery'], node['read_only']) != (503, True, True):
                raise Refused('rollback target is no longer a standby')
            if node['image'] not in (image, action['original_image']):
                raise Refused('concurrent image change; rollback refused')
            transport.update(action['node'], action['original_image'], node['image'])
            after = transport.snapshot()
            checked = plan(after, image)
            node = next(n for n in after['nodes'] if n['name'] == action['node'])
            if node['image'] != action['original_image'] or checked['primary'] != result['primary']:
                raise Refused('rollback readback failed')
            result.update(status='rolled-back', rollback={'image': node['image'], 'verified': True})
        except Exception as rollback_exc:
            result['rollback'] = {'verified': False, 'error': type(rollback_exc).__name__}
    return result
