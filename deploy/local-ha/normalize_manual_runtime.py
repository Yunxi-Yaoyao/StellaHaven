#!/usr/bin/env python3
"""Opt-in, app-only repair of an operator-pinned prior manual deployment.

Default is a READ-ONLY local-node preflight (Docker inspect/exec; no SSH). The
parent operator must serialize NAS then Nyarch and compare both node readbacks.
This is not a general release path or fencing. It never pulls images, changes
PG/roles/schema/host routing, or reads application configuration/fixtures.

JSON stdin: scope=stella-manual-runtime-normalize-v1, node, inventory (approved
CI golden inventory), expected_roles (both booleans), approved_pg_id (local full
ID), approved_image (local image inspect Id, RootFS, Config, Architecture, Os),
approved_old (exact Id, Image, Config, HostConfig, Mounts from operator-approved
old inspect). These approvals MUST be reviewed independently, not generated and
automatically approved by this helper. Env/approval payload stays on stdin and
is never printed. Run --apply only with explicit operator approval, under the
same production resource_group. Locks serialize with ordinary local releases.
"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import re
import sys


def load_sibling(name):
    spec = importlib.util.spec_from_file_location('normalization_' + name, Path(__file__).with_name(name + '.py'))
    assert spec is not None and spec.loader is not None, 'trusted sibling helper missing'
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = load_sibling('node_production')
release_contract = load_sibling('production_release')
require = contract.require
OLD_FIELDS = ('Id', 'Image', 'Config', 'HostConfig', 'Mounts')


def same_approved_snapshot(actual, approved):
    # Docker inspect can reorder the complete Mounts array between reads.
    # Compare all mount attributes; only presentation order is irrelevant.
    for key in OLD_FIELDS:
        if key == 'Mounts':
            left = sorted(actual[key], key=lambda m: m['Destination'])
            right = sorted(approved[key], key=lambda m: m['Destination'])
            if left != right:
                return False
        elif actual[key] != approved[key]:
            return False
    return True



class Normalizer(contract.Node):
    def __init__(self, request):
        require(request.get('scope') == 'stella-manual-runtime-normalize-v1', 'manual normalization approval required')
        require(set(request) == {'scope', 'node', 'inventory', 'expected_roles', 'approved_old',
                                 'approved_image', 'approved_pg_id'}, 'exact normalization request required')
        release_contract.validate_inventory(request['inventory'])
        roles = request['expected_roles']
        require(isinstance(roles, dict) and set(roles) == set(contract.NODES)
                and all(type(v) is bool for v in roles.values()) and sum(roles.values()) == 1,
                'exact approved roles required')
        old = request['approved_old']
        require(set(old) == set(OLD_FIELDS), 'exact old snapshot fields required')
        require(re.fullmatch('[0-9a-f]{64}', old['Id']) is not None, 'full old container ID required')
        require(re.fullmatch('sha256:[0-9a-f]{64}', old['Image']) is not None, 'full local image ID required')
        require(re.fullmatch('[0-9a-f]{64}', request['approved_pg_id']) is not None, 'full PG container ID required')
        image = request['approved_image']
        require(image.get('Id') == old['Image'] and all(k in image for k in ('RootFS', 'Config', 'Architecture', 'Os')),
                'approved local image content required')
        super().__init__(copy.deepcopy(request))
        require(self.cfg['command'] == ['/shadow-start.py'], 'exact golden startup command required')
        require((self.cfg['memory'], self.cfg['nano_cpus']) == (1073741824, 2000000000),
                'exact golden resources required')
        env = dict(row.split('=', 1) for row in old['Config']['Env'])
        release_contract.validate_release_approval(self.inv, env.get('STELLA_AGENT_ROLLOUT_VERSION'))
        require(self.application_environment_matches(old), 'normalization must not change approved application environment')

    def validate_manual(self, c, name=None):
        require(same_approved_snapshot(c, self.r['approved_old']), 'old approved snapshot changed')
        require(c['Name'] == '/' + (name or self.name) and c['State']['Running'], 'manual app name/state mismatch')
        cfg, host = c['Config'], c['HostConfig']
        require(cfg.get('Entrypoint') is None and cfg.get('Cmd') == ['/app/.venv/bin/python', '/shadow-start.py'],
                'not the approved manual startup shape')
        require(host.get('Memory') == 0 and host.get('NanoCpus') == 0
                and host.get('CapDrop') is None and host.get('SecurityOpt') is None
                and host.get('RestartPolicy') == {'Name': 'no', 'MaximumRetryCount': 0},
                'not the approved manual runtime shape')
        require(type(host.get('ReadonlyRootfs')) is bool and host.get('Init') in (None, False, True),
                'invalid manual isolation shape')
        # Existing Node guard is NOT relaxed. Only the enumerated lost runtime
        # fields are substituted in a COPY, then all its security pins run.
        normalized = copy.deepcopy(c)
        normalized['Config'].update(Entrypoint=['/app/.venv/bin/python'], Cmd=self.cfg['command'])
        normalized['HostConfig'].update(ReadonlyRootfs=True, Init=True, Memory=self.cfg['memory'],
                                        NanoCpus=self.cfg['nano_cpus'], CapDrop=['ALL'],
                                        SecurityOpt=['no-new-privileges'])
        contract.Node.validate(self, normalized, name=name, approved_environment=True)
        return c

    def preflight(self):
        old = copy.deepcopy(self.inspect(self.name))
        self.validate_manual(old)
        self.pg_id = self.pg_guard()
        require(self.pg_id == self.r['approved_pg_id'], 'approved PG identity changed')
        info = json.loads(contract.run(['docker', 'image', 'inspect', old['Image']]))[0]
        require(info.get('Id') == old['Image'] and contract.same_image_content(info, self.r['approved_image']),
                'approved local image content changed')
        initial = self.probe()
        require(initial['roles'] == self.expected, 'initial roles mismatch')
        self.guard()
        return old, info, initial

    def validate_target(self, c, name, port, image):
        contract.Node.validate(self, c, name=name, port=port, replacement=port == 25132,
                               approved_environment=True)
        original = self.r['approved_old']
        # Docker-generated hostname and mount encodings may differ. Mounts are
        # independently checked by the unchanged exact Node mount contract.
        ignored_config = {'Hostname', 'Image', 'Entrypoint', 'Cmd'}
        if 'Image' in c['Config']:
            require(c['Config']['Image'] == image['Id'], 'target image reference must be pinned local ID')
        ignored_host = {'Binds', 'Mounts', 'Memory', 'NanoCpus', 'CapDrop', 'SecurityOpt',
                        'ReadonlyRootfs', 'Init', 'RestartPolicy'}
        for section, ignored in (('Config', ignored_config), ('HostConfig', ignored_host)):
            actual = {k: v for k, v in c[section].items() if k not in ignored}
            expected = {k: v for k, v in original[section].items() if k not in ignored}
            # Node.create's --memory uses Docker's default total RAM+swap bound:
            # restoring a zero/unlimited manual bound may yield exactly 2*RAM.
            # No arbitrary swap setting or other host-field change is tolerated.
            if section == 'HostConfig' and expected.get('MemorySwap') == 0:
                require(actual.get('MemorySwap') in (0, 2 * self.cfg['memory']), 'target swap bound changed')
                expected['MemorySwap'] = actual['MemorySwap']
            require(actual == expected, 'target non-normalized runtime fields changed')
        require(c['Config']['Env'] == original['Config']['Env'], 'target exact environment changed')
        require(c['Config'].get('Labels') == self.r['approved_old']['Config'].get('Labels'), 'target labels changed')
        require(c['HostConfig'].get('Init') is True, 'target init missing')
        require(c['HostConfig'].get('RestartPolicy') == {'Name': 'no' if port == 25132 else 'unless-stopped',
                                                       'MaximumRetryCount': 0}, 'target restart mismatch')
        require(self.image_matches(c['Image'], image), 'target local image content changed')
        return c

    def confirm_created(self, identifier, name):
        require(re.fullmatch('[0-9a-f]{64}', identifier) is not None
                and identifier not in {self.r['approved_old']['Id'], self.pg_id}, 'created app ID invalid')
        actual = self.inspect(name)
        require(actual['Id'] == identifier and actual['Name'] == '/' + name
                and not actual['State']['Running'], 'created app identity/state unconfirmed')
        return identifier

    def validate_created(self, name, port, image):
        # Check the complete constructor before executing ANY app code. The
        # running-state substitution exists only in a copy for Node.validate;
        # actual Running=False is separately required by confirm_created.
        pending = copy.deepcopy(self.inspect(name))
        require(not pending['State']['Running'], 'created app already running')
        pending['State']['Running'] = True
        self.validate_target(pending, name, port, image)

    def create_stable(self, old, image_id):
        contract.port_free(25131)
        args = ['docker', 'create', '--pull=never', '--name', self.name, '--network=host', '--read-only',
                '--init', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                '--memory', str(self.cfg['memory']), '--cpus', str(self.cfg['nano_cpus'] / 1000000000),
                '--restart=unless-stopped', '--workdir=/app', '--entrypoint=/app/.venv/bin/python']
        for mount in self.cfg['mounts']:
            args += ['--mount', 'type=bind,src=' + mount['Source'] + ',dst=' + mount['Destination']
                     + (',readonly' if not mount['RW'] else '')]
        for key, value in (old['Config'].get('Labels') or {}).items():
            args += ['--label', key + '=' + value]
        args += ['--env-file', '/dev/stdin', image_id, *self.cfg['command']]
        return contract.run(args, '\n'.join(old['Config']['Env']) + '\n')

    def normalize(self, apply=False):
        old, image, initial = self.preflight()
        base = dict(node=self.node, previous_id=old['Id'], image_id=old['Image'], roles=self.expected,
                    pg_mutated=False, environment_changed=False, image_changed=False)
        if not apply:
            return dict(base, status='validated', read_only=True, container_id=old['Id'])
        suffix = contract.uuid.uuid4().hex[:12]
        candidate = self.name + '-normalize-candidate-' + suffix
        backup = self.name + '-normalize-rollback-' + suffix
        candidate_id = replacement_id = None
        stop_attempted = False
        stage = 'candidate-create'
        try:
            self.guard()
            created = self.create(old, candidate, image['Id'], 25132)
            candidate_id = self.confirm_created(created, candidate)
            self.validate_created(candidate, 25132, image)
            self.target_names.add(candidate)
            stage = 'candidate-start'
            self.action('start', candidate_id)
            require(self.inspect(candidate)['Id'] == candidate_id, 'candidate identity changed')
            self.validate_target(self.inspect(candidate), candidate, 25132, image)
            stage = 'candidate-health'
            self.health(candidate, 25132)
            self.guard(candidate)
            self.validate_manual(self.inspect(self.name))
            stage = 'stop-old'
            # Set BEFORE calling: a timeout/post-action guard can follow a stop.
            stop_attempted = True
            self.action('stop', '--time', '30', old['Id'], probe_name=candidate)
            stage = 'rename-old'
            self.action('rename', old['Id'], backup, probe_name=candidate)
            self.guard(candidate)
            stage = 'stable-create'
            created = self.create_stable(old, image['Id'])
            replacement_id = self.confirm_created(created, self.name)
            self.validate_created(self.name, 25131, image)
            self.target_names.add(self.name)
            stage = 'stable-start'
            self.action('start', replacement_id, probe_name=candidate)
            require(self.inspect(self.name)['Id'] == replacement_id, 'stable identity changed')
            stage = 'stable-validate'
            live = self.validate_target(self.inspect(self.name), self.name, 25131, image)
            stage = 'stable-health'
            health = self.health(self.name, 25131)
            self.guard()
            # Retain exact containers as evidence; no broad or automatic cleanup.
            stage = 'candidate-stop'
            self.action('stop', candidate_id)
            stage = 'final-readback'
            self.validate_target(self.inspect(self.name), self.name, 25131, image)
            self.guard()
            require(not self.inspect(candidate_id)['State']['Running'], 'candidate stop unconfirmed')
            require(self.inspect(old['Id'])['Name'] == '/' + backup
                    and not self.inspect(old['Id'])['State']['Running'], 'backup state changed')
            return dict(base, status='normalized', container_id=live['Id'], backup=backup,
                        candidate=candidate, candidate_id=candidate_id, http=health['http'])
        except Exception as exc:
            self.target_names.discard(self.name)
            outcome_unknown = (stage == 'candidate-create' and candidate_id is None) or (
                stage == 'stable-create' and replacement_id is None)
            receipt = dict(base, status='blocked', failed_stage=stage, error_type=type(exc).__name__,
                           outcome_unknown=outcome_unknown, backup=backup, candidate=candidate, candidate_id=candidate_id,
                           failed_id=replacement_id)
            try:
                require(self.pg_guard() == self.pg_id, 'PG identity drift during recovery')
                if replacement_id:
                    # Never remove anything, or operate on a namesake unknown ID.
                    failed = self.inspect(replacement_id)
                    require(failed['Name'] == '/' + self.name, 'failed stable identity changed')
                    if failed['State']['Running']:
                        contract.run(['docker', 'stop', '--time', '30', replacement_id])
                    failed_name = self.name + '-normalize-failed-' + suffix
                    contract.run(['docker', 'rename', replacement_id, failed_name])
                    require(self.inspect(replacement_id)['Name'] == '/' + failed_name
                            and not self.inspect(replacement_id)['State']['Running'], 'failed stable retention unconfirmed')
                    receipt['failed_container'] = failed_name
                if stop_attempted:
                    current_old = self.inspect(old['Id'])
                    require(same_approved_snapshot(current_old, old), 'rollback old snapshot changed')
                    if current_old['Name'] == '/' + backup:
                        contract.run(['docker', 'rename', old['Id'], self.name])
                    else:
                        require(current_old['Name'] == '/' + self.name, 'rollback old name changed')
                    if not self.inspect(old['Id'])['State']['Running']:
                        contract.run(['docker', 'start', old['Id']])
                # validate_manual enforces exact original ID/image/Env/host/mounts.
                self.validate_manual(self.inspect(self.name))
                health = self.health(self.name, 25131, expected=False)
                require(self.pg_guard() == self.pg_id, 'PG identity drift after recovery')
                if candidate_id:
                    retained = self.inspect(candidate_id)
                    require(retained['Name'] == '/' + candidate, 'candidate retention identity changed')
                    if retained['State']['Running']:
                        contract.run(['docker', 'stop', '--time', '30', candidate_id])
                    require(not self.inspect(candidate_id)['State']['Running'], 'candidate stop unconfirmed')
                self.validate_manual(self.inspect(self.name))
                receipt.update(status='rolledback' if stop_attempted and not outcome_unknown else 'blocked',
                               reason=('exact old app verified; create outcome unknown; inspect retained names before retry'
                                       if outcome_unknown else 'normalization failed; exact old app verified'),
                               container_id=old['Id'], http=health['http'], rollback_roles=health['roles'])
            except Exception as recovery_error:
                receipt.update(reason='rollback incomplete or outcome unknown; manual recovery required',
                               recovery_error_type=type(recovery_error).__name__)
            return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='explicitly authorize app replacement')
    mode.add_argument('--dry-run', action='store_true', help='read-only node preflight (default)')
    mode.add_argument('--validate-pack', action='store_true', help='offline syntax check only')
    args = parser.parse_args(argv)
    if args.validate_pack:
        for filename in ('normalize_manual_runtime.py', 'node_production.py', 'production_release.py'):
            compile(Path(__file__).with_name(filename).read_text(), filename, 'exec')
        print(json.dumps({'status': 'validated', 'production_executed': False}))
        return 0
    try:
        node = Normalizer(json.load(sys.stdin))
        if args.apply:
            with open('/run/lock/stella-production-app-release.lock', 'a') as lock:
                contract.fcntl.flock(lock, contract.fcntl.LOCK_EX | contract.fcntl.LOCK_NB)
                result = node.normalize(apply=True)
        else:
            result = node.normalize(apply=False)
    except Exception as exc:
        # Exceptions may originate in libraries/parsers with payload contents.
        # Never emit the exception message, inspect Env, stderr or traceback.
        result = dict(status='blocked', reason='normalization preflight/lock failed', error_type=type(exc).__name__)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] in ('validated', 'normalized') else 1


if __name__ == '__main__':
    sys.exit(main())
