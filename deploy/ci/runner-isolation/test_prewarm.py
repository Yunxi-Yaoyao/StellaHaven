"""Offline prewarm admission contracts. No daemon, network, credentials or DB."""
import copy
import importlib.util
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CALL = 'sh deploy/ci/runner-isolation/prewarm-before-build.sh'
PUBLIC = 'postgres:18@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336'
PRIVATE = 'gitlab-registry.xiya.live/yaoyao/stellahaven/ci-base/postgres@sha256:885953109528ad3dfc90362b1a6f50a78620b5315be19f187753d267e484dc5b'
FLAGS = '--oci-worker-snapshotter=overlayfs --oci-worker-gc=false'


class PrewarmContract(unittest.TestCase):
    def check_source(self, build, prewarm, dockerfile):
        self.assertEqual(build.splitlines().count(CALL), 1)
        self.assertLess(build.index('BLOCKED_SPACE'), build.index(CALL))
        self.assertLess(build.index('unset auth CI_REGISTRY_PASSWORD'), build.index(CALL))
        self.assertIn("export BUILDKITD_FLAGS='" + FLAGS + "'", build)
        self.assertLess(build.index("export BUILDKITD_FLAGS='" + FLAGS + "'"), build.index(CALL))
        self.assertLess(build.index(CALL), build.index('buildctl-daemonless.sh build'))
        self.assertIn('if ($4 < 8388608)', build)
        self.assertIn('bad || n != 2', build)
        self.assertIn('set -eu', build)
        self.assertIn('set -eu', prewarm)
        self.assertIn('[ "$(id -u)" = 1000 ]', prewarm)
        self.assertIn('[ ! -S /var/run/docker.sock ] && [ ! -S /run/docker.sock ]', prewarm)
        self.assertIn('${DOCKER_CONFIG:?', prewarm)
        self.assertIn('${BUILDKITD_FLAGS:?', prewarm)
        self.assertIn('[ -f "$DOCKER_CONFIG/config.json" ]', prewarm)
        self.assertIn('umask 077', prewarm)
        self.assertIn('set +x', prewarm)
        self.assertIn('mktemp -d /tmp/stella-pg18-prewarm.XXXXXX', prewarm)
        self.assertIn('trap \'rm -rf "$D"\' EXIT HUP INT TERM', prewarm)
        self.assertEqual(prewarm.count(PRIVATE), 1)
        self.assertIn('FROM ' + PRIVATE + ' AS source', prewarm)
        self.assertIn('FROM scratch', prewarm)
        for source, target in (
            ('/usr/lib/postgresql/18/bin/pg_dump', '/pg_dump'),
            ('/usr/lib/postgresql/18/bin/pg_restore', '/pg_restore'),
            ('/usr/lib/x86_64-linux-gnu/libpq.so.5.18', '/libpq.so.5.18'),
        ):
            self.assertIn('COPY --from=source ' + source + ' ' + target, prewarm)
        self.assertEqual(prewarm.count('buildctl-daemonless.sh build'), 1)
        self.assertIn('--local context="$D/context" --local dockerfile="$D/context"', prewarm)
        self.assertIn('--output "type=local,dest=$D/out"', prewarm)
        self.assertIn('FROM ' + PUBLIC + ' AS backup-pg-client', dockerfile)
        for unsafe in ('|| true', 'push=true', '--import-cache', '--export-cache', 'CI_REGISTRY_PASSWORD', 'export DOCKER_CONFIG=', 'export BUILDKITD_FLAGS=', 'RUN '):
            self.assertNotIn(unsafe, prewarm)
        for text in (build, prewarm):
            for unsafe in ('--oci-worker-no-process-sandbox', '--network=host', '--privileged', ':latest', 'docker build'):
                self.assertNotIn(unsafe, text)

    def test_admitted_same_worker_prewarm_precedes_unchanged_app_solve(self):
        build = (HERE / 'build-rootless.sh').read_text()
        # Assert call first so the pre-integration RED is a missing behavior,
        # not a FileNotFoundError.
        self.assertIn(CALL, build)
        self.check_source(build, (HERE / 'prewarm-before-build.sh').read_text(), (ROOT / 'Dockerfile').read_text())


    def check_ci(self, ci):
        build = ci['build-images']
        self.assertEqual(build['timeout'], '30m')
        self.assertFalse(build.get('allow_failure', False))
        self.assertEqual(build['needs'], ['backend-test', 'frontend-build', 'local-ha-contract', 'experience-gate'])
        self.assertEqual(build['script'], ['sh deploy/ci/runner-isolation/build-rootless.sh'])
        self.assertEqual(build['tags'], ['stella-isolated-build'])
        self.assertEqual(build['cache'], [])
        self.assertNotIn('environment', build)
        self.assertEqual(build['artifacts']['paths'], ['.ci-build-receipt/app.json', '.ci-build-receipt/pg.json'])
        self.assertEqual(len(build['before_script']), 1)
        for secret in ('STELLA_PRODUCTION_SSH_KEY', 'STELLA_PRODUCTION_INVENTORY', 'STELLA_PRODUCTION_KNOWN_HOSTS', 'KUBECONFIG', 'KUBE_CONFIG', 'LOCAL_HA_SSH_CONFIG', 'LOCAL_HA_INVENTORY', 'STELLA_SECRET_KEY', 'DATABASE_URL'):
            self.assertIn('${' + secret + ':-}', build['before_script'][0])
        self.assertIn('exit 1', build['before_script'][0])
        self.assertEqual(ci['.validation-secret-boundary']['before_script'], build['before_script'])
        for name in ('backend-test', 'frontend-build', 'experience-gate', 'local-ha-contract', 'build-image-receipt'):
            self.assertEqual(ci[name]['before_script'][0], build['before_script'][0])
        self.assertEqual(ci['backend-test']['parallel'], 7)
        for name, budget in [('backend-test', '25m'), ('frontend-build', '15m'), ('experience-gate', '15m'), ('local-ha-contract', '5m')]:
            self.assertEqual(ci[name]['timeout'], budget)
            self.assertFalse(ci[name].get('allow_failure', False))

    def test_active_and_rendered_ci_keep_budget_gates_and_secret_boundary(self):
        spec = importlib.util.spec_from_file_location('prewarm_renderer', HERE / 'render_candidate.py')
        assert spec is not None and spec.loader is not None
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        active = yaml.safe_load((ROOT / '.gitlab-ci.yml').read_text())
        rendered = renderer.compile_ci(active)
        self.assertEqual(active, rendered)
        for ci in (active, rendered):
            self.check_ci(ci)
            for mutate in (
                lambda c: c['build-images'].update(timeout='31m'),
                lambda c: c['build-images'].update(allow_failure=True),
                lambda c: c['build-images']['needs'].pop(),
                lambda c: c['build-images']['before_script'].clear(),
                lambda c: c['build-images']['before_script'].__setitem__(0, c['build-images']['before_script'][0].replace('${STELLA_PRODUCTION_SSH_KEY:-}', '')),
                lambda c: c['build-images']['artifacts']['paths'].append('/tmp/'),
            ):
                bad = copy.deepcopy(ci)
                mutate(bad)
                with self.assertRaises((AssertionError, IndexError)):
                    self.check_ci(bad)

    def test_source_mutations_rejected_independently_of_refreshed_hashes(self):
        build = (HERE / 'build-rootless.sh').read_text()
        prewarm = (HERE / 'prewarm-before-build.sh').read_text()
        dockerfile = (ROOT / 'Dockerfile').read_text()
        mutations = [
            ('missing-call', build.replace(CALL, ''), prewarm, dockerfile),
            ('ignored-failure', build.replace(CALL, CALL + ' || true'), prewarm, dockerfile),
            ('call-before-admission', CALL + '\n' + build.replace(CALL, ''), prewarm, dockerfile),
            ('lower-space-gate', build.replace('8388608', '7340032'), prewarm, dockerfile),
            ('new-manifest', build, prewarm.replace(PRIVATE, PRIVATE[:-1] + '0'), dockerfile),
            ('public-source-replaced', build, prewarm, dockerfile.replace(PUBLIC, PRIVATE)),
            ('prewarm-push', build, prewarm.replace('type=local,dest=$D/out', 'type=image,push=true'), dockerfile),
            ('auth-override', build, prewarm + '\nexport DOCKER_CONFIG=/shared\n', dockerfile),
            ('sandbox-disabled', build, prewarm + '\n# --oci-worker-no-process-sandbox\n', dockerfile),
            ('root-accepted', build, prewarm.replace('= 1000', '= 0'), dockerfile),
            ('temp-in-checkout', build, prewarm.replace('/tmp/stella-pg18-prewarm.', './stella-pg18-prewarm.'), dockerfile),
        ]
        for name, b, p, d in mutations:
            with self.subTest(mutation=name), self.assertRaises(AssertionError):
                self.check_source(b, p, d)

    def test_renderer_binds_both_rootless_scripts(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            subprocess.run([sys.executable, str(HERE / 'render_candidate.py'), '--out', tmp], check=True, capture_output=True)
            binding = json.loads((Path(tmp) / 'source-binding.json').read_text())
            self.assertIn('rootless_script_sha256', binding)
            self.assertEqual(set(binding['rootless_script_sha256']), {'build-rootless.sh', 'prewarm-before-build.sh'})
            spec = importlib.util.spec_from_file_location('prewarm_verifier', HERE / 'verify_bundle.py')
            assert spec is not None and spec.loader is not None
            verifier = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(verifier)
            self.assertEqual(verifier.verify(tmp)['status'], 'PASS')
            for name in binding['rootless_script_sha256']:
                bad = copy.deepcopy(binding)
                bad['rootless_script_sha256'][name] = '0' * 64
                (Path(tmp) / 'source-binding.json').write_text(json.dumps(bad))
                with self.assertRaises(AssertionError):
                    verifier.verify(tmp)
            (Path(tmp) / 'source-binding.json').write_text(json.dumps(binding))


FAKE_COMMAND = r'''import base64, json, os, pathlib, sys, tempfile
name = pathlib.Path(sys.argv[0]).name
root = pathlib.Path(os.environ['FAKE_ROOT'])
def record(data):
    with (root / 'calls.jsonl').open('a') as f:
        f.write(json.dumps(data) + '\n')
if name == 'id':
    print(os.environ.get('FAKE_UID', '1000'))
elif name == 'df':
    free = os.environ.get('FAKE_FREE', '8388608')
    print('Filesystem 1024-blocks Used Available Capacity Mounted on')
    print('fixture 16777216 0 ' + free + ' 0% /checkout')
    print('fixture 16777216 0 ' + free + ' 0% /worker')
elif name == 'mktemp':
    # Remap only production /tmp allocations into this test's owned scratch.
    assert sys.argv[1] == '-d'
    prefix = pathlib.Path(sys.argv[2]).name.removesuffix('XXXXXX')
    path = tempfile.mkdtemp(prefix=prefix, dir=root / 'temps')
    record({'temp': path})
    print(path)
elif name == 'buildctl-daemonless.sh':
    args = sys.argv[1:]
    context = pathlib.Path(next(a.split('=', 1)[1] for a in args if a.startswith('context='))).resolve()
    auth = pathlib.Path(os.environ['DOCKER_CONFIG']) / 'config.json'
    expected = base64.b64encode(b'fixture-user:fixture-password').decode()
    record({'argv': args, 'context': str(context), 'context_files': sorted(p.name for p in context.iterdir()),
            'dockerfile': (context / 'Dockerfile').read_text(),
            'docker_config': os.environ['DOCKER_CONFIG'], 'flags': os.environ.get('BUILDKITD_FLAGS'),
            'password_absent': 'CI_REGISTRY_PASSWORD' not in os.environ,
            'auth_valid': json.loads(auth.read_text()) == {'auths': {'gitlab-registry.xiya.live': {'auth': expected}}},
            'auth_mode': auth.stat().st_mode & 0o777})
    if context.name == 'context':
        sys.exit(int(os.environ.get('FAKE_PREWARM_EXIT', '0')))
    # Synthetic metadata only; no image/digest claimed by this harness.
    pathlib.Path(args[args.index('--metadata-file') + 1]).write_text('{}')
else:
    raise AssertionError(name)
'''


class PrewarmShellTests(unittest.TestCase):
    def exercise(self, overrides=None, standalone=False):
        with tempfile.TemporaryDirectory(prefix='prewarm-shell-', dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            checkout = root / 'checkout'
            scripts = checkout / 'deploy/ci/runner-isolation'
            scripts.mkdir(parents=True)
            for name in ('build-rootless.sh', 'prewarm-before-build.sh'):
                # Host may legitimately have a Docker socket. Redirect only
                # these fixture copies' socket probes to owned absent paths;
                # static contracts above still enforce the real job guard.
                text = (HERE / name).read_text()
                for socket_path in ('/var/run/docker.sock', '/run/docker.sock'):
                    text = text.replace(socket_path, str(root / 'absent-docker.sock'))
                (scripts / name).write_text(text)
            (checkout / 'Dockerfile').write_bytes((ROOT / 'Dockerfile').read_bytes())
            (root / 'temps').mkdir()
            (root / 'bin').mkdir()
            (root / 'home/.local/share/buildkit').mkdir(parents=True)
            for name in ('id', 'df', 'mktemp', 'buildctl-daemonless.sh'):
                command = root / 'bin' / name
                command.write_text('#!' + sys.executable + '\n' + FAKE_COMMAND)
                command.chmod(0o700)
            env = {'PATH': str(root / 'bin') + ':/usr/bin:/bin', 'HOME': str(root / 'home'),
                   'FAKE_ROOT': str(root), 'CI_COMMIT_SHA': 'a' * 40,
                   'CI_REGISTRY_USER': 'fixture-user', 'CI_REGISTRY_PASSWORD': 'fixture-password',
                   # An unsafe caller TMPDIR must not put temporary auth/context in checkout.
                   'TMPDIR': str(checkout)}
            env.update(overrides or {})
            command = 'prewarm-before-build.sh' if standalone else 'build-rootless.sh'
            p = subprocess.run(['sh', str(scripts / command)], env=env, cwd=checkout, capture_output=True, text=True, timeout=15)
            events = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()] if (root / 'calls.jsonl').exists() else []
            calls = [event for event in events if 'argv' in event]
            for event in events:
                if 'temp' in event:
                    self.assertFalse(Path(event['temp']).exists(), 'owned temp leaked')
            self.assertNotIn('fixture-password', p.stdout + p.stderr)
            receipt = checkout / '.ci-build-receipt'
            files = sorted(f.name for f in receipt.iterdir()) if receipt.exists() else []
            return p, calls, files

    def test_exact_prewarm_argv_auth_cleanup_and_original_build_outputs(self):
        p, calls, files = self.exercise()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(calls), 3)
        warm, app, pg = calls
        context = warm['context']
        dest = str(Path(context).parent / 'out')
        self.assertEqual(warm['argv'], ['build', '--frontend', 'dockerfile.v0', '--local', 'context=' + context, '--local', 'dockerfile=' + context, '--output', 'type=local,dest=' + dest])
        self.assertEqual(warm['context_files'], ['Dockerfile'])
        self.assertEqual(warm['dockerfile'].splitlines(), ['FROM ' + PRIVATE + ' AS source', 'FROM scratch', 'COPY --from=source /usr/lib/postgresql/18/bin/pg_dump /pg_dump', 'COPY --from=source /usr/lib/postgresql/18/bin/pg_restore /pg_restore', 'COPY --from=source /usr/lib/x86_64-linux-gnu/libpq.so.5.18 /libpq.so.5.18'])
        for call in calls:
            self.assertEqual(call['docker_config'], warm['docker_config'])
            self.assertEqual(call['flags'], FLAGS)
            self.assertTrue(call['password_absent'])
            self.assertTrue(call['auth_valid'])
            self.assertEqual(call['auth_mode'], 0o600)
        base = 'gitlab-registry.xiya.live/yaoyao/stellahaven'
        app_args = ['build', '--frontend', 'dockerfile.v0', '--local', 'context=.', '--local', 'dockerfile=.', '--opt', 'build-arg:STELLA_NODE_BASE=' + base + '/ci-base/node@sha256:efd0ab5780c2d9ab1f0f869571a00d5edb17793bff4cce4a2792e3eb0ffc7562', '--opt', 'build-arg:STELLA_PYTHON_BASE=' + base + '/ci-base/python@sha256:8fb4cfa1a2616d7b8e0c2175cc6ad68f5729c34ea8488c0b360d2934b7be9024', '--output', 'type=image,name=' + base + ':' + 'a' * 40 + ',push=true', '--metadata-file', app['argv'][-1]]
        pg_args = ['build', '--frontend', 'dockerfile.v0', '--local', 'context=.', '--local', 'dockerfile=.', '--opt', 'filename=Dockerfile.pg', '--opt', 'build-arg:STELLA_POSTGRES_BASE=' + base + '/ci-base/postgres@sha256:9551dd5bf356409a21b31248f49b33bba9bb1877365f3a7e933aecd9af3cf52d', '--output', 'type=image,name=' + base + '/pg-patroni:' + 'a' * 40 + ',push=true', '--metadata-file', pg['argv'][-1]]
        self.assertEqual(app['argv'], app_args)
        self.assertEqual(pg['argv'], pg_args)
        self.assertIn('FROM ' + PUBLIC + ' AS backup-pg-client', app['dockerfile'])
        self.assertEqual(files, ['app.json', 'pg.json'])
        self.assertNotIn('context', app['context_files'])

    def test_prewarm_failure_stops_before_app_and_removes_all_owned_temps(self):
        p, calls, files = self.exercise({'FAKE_PREWARM_EXIT': '23'})
        self.assertEqual(p.returncode, 23)
        self.assertEqual(len(calls), 1)
        self.assertEqual(files, [])

    def test_space_uid_credentials_and_standalone_guards_fail_closed(self):
        for overrides in ({'FAKE_FREE': '8388607'}, {'FAKE_UID': '0'}, {'CI_REGISTRY_PASSWORD': ''}, {'STELLA_PRODUCTION_SSH_KEY': 'fixture-forbidden'}, {'CI_COMMIT_SHA': 'bad'}):
            with self.subTest(overrides=overrides):
                p, calls, files = self.exercise(overrides)
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(calls, [])
                self.assertEqual(files, [])
        p, calls, files = self.exercise(standalone=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
