"""Offline regression contract for verified build sources and trust budgets.

The network/install evidence is collected separately in disposable containers;
these tests never contact a database, registry, or software mirror.
"""
import ast
from pathlib import Path
import re
import unittest

import yaml


HELPERS = ('deploy/ci/runner-isolation/backend_dependencies.py',
           'deploy/ci/runner-isolation/browser_dependencies.py')
MIRRORS = ('https://mirrors.tuna.tsinghua.edu.cn', 'https://deb.debian.org')
NODE_IMAGE = 'gitlab-registry.xiya.live/yaoyao/stellahaven/ci-base/node@sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d'


ROOT = Path(__file__).resolve().parents[1]


class BuildMirrorContract(unittest.TestCase):
    def assert_mandatory_helper(self, job, helper, mode):
        command = 'python3 ' + helper + ' ' + mode
        self.assertEqual(job['before_script'].count(command), 1)
        self.assertEqual(sum(helper in cmd for cmd in job['before_script']), 1)
        self.assertIs(job.get('allow_failure', False), False)
        self.assertFalse(any('apt-get' in cmd for cmd in job['before_script']))
        return command

    def helper_tree(self, helper):
        return ast.parse((ROOT / helper).read_text())

    def literal(self, tree, name):
        values = [node.value for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)]
        self.assertEqual(len(values), 1, name)
        return ast.literal_eval(values[0])

    def assert_syntax(self, tree, expected):
        # Inspect executable syntax, not comments/docstrings containing old commands.
        node, = ast.parse(expected).body
        if isinstance(node, ast.Expr):
            node = node.value
        self.assertIn(ast.dump(node), [ast.dump(n) for n in ast.walk(tree)], expected)

    def assert_helper_budget(self, helper):
        tree = self.helper_tree(helper)
        prepare, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare']
        budget = ('attempt = min(deadline, time.monotonic() + (150 if index == 0 else 90))'
                  if helper == HELPERS[0] else
                  'attempt = min(deadline, time.monotonic() + 150) if index == 0 else deadline')
        for syntax in (
            'deadline = time.monotonic() + 240',
            budget,
            "apt([*cache, '--no-download', '--no-install-recommends', 'install', '-y', *packages], 120)",
        ):
            self.assert_syntax(prepare, syntax)
        if helper == HELPERS[1]:
            for syntax in ('remaining = attempt - time.monotonic()', 'apt(args, remaining)',
                           "if remaining <= 0:\n    raise subprocess.TimeoutExpired('apt-get', 0)"):
                self.assert_syntax(prepare, syntax)
            self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                                 and n.func.id == 'max' for n in ast.walk(prepare)))
        # Behavioral cleanup/resolver cases live in the complete helper owning suites.
        guards = [n for n in ast.walk(prepare) if isinstance(n, ast.If)
                  and ast.dump(n.test) == ast.dump(ast.parse('chosen is None', mode='eval').body)]
        self.assertEqual(len(guards), 1)
        failure = guards[0].body[0]
        assert isinstance(failure, ast.Raise)
        assert isinstance(failure.exc, ast.Call)
        assert isinstance(failure.exc.func, ast.Name)
        self.assertEqual(failure.exc.func.id, 'RuntimeError')
        restores = [n for n in ast.walk(prepare) if isinstance(n, ast.Try) and n.finalbody]
        self.assertEqual(len(restores), 1)
        self.assertEqual([ast.dump(n) for n in restores[0].finalbody],
                         [ast.dump(ast.parse('SOURCES.write_text(original)').body[0])])
        self.assert_syntax(tree, "'Acquire::Retries=0'")
        self.assert_syntax(tree, "'Acquire::https::Timeout=15'")
        self.assert_syntax(tree, "'APT::Update::Error-Mode=any'")
        if helper == HELPERS[0]:
            self.assert_syntax(prepare, 'remaining = attempt - time.monotonic()')
            self.assert_syntax(prepare, 'apt(args, remaining)')
            self.assert_syntax(tree, 'os.killpg(proc.pid, signal.SIGKILL)')
            self.assert_syntax(tree, 'proc.wait()')
            self.assert_syntax(tree, 'proc.wait(timeout=timeout)')
            run, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run']
            calls = [n for n in ast.walk(run) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute) and n.func.attr == 'Popen']
            self.assertEqual(len(calls), 1)
            self.assertIn(('start_new_session', True),
                          [(k.arg, k.value.value) for k in calls[0].keywords if isinstance(k.value, ast.Constant)])

    def test_backend_sources_use_verified_https_endpoints(self):
        ci = (ROOT / ".gitlab-ci.yml").read_text()
        docker = (ROOT / "Dockerfile").read_text()
        index = "https://pypi.tuna.tsinghua.edu.cn/simple"
        # One shared CI index; Docker bootstraps uv and syncs dependencies with it.
        self.assertEqual(yaml.safe_load(ci)['variables']['PIP_INDEX_URL'], index)
        self.assertEqual(ci.count(index), 1)
        self.assertEqual(re.findall(r"--index-url\s+(\S+)", docker), [index, index])
        self.assertEqual(docker.count(index), 2)
        job = yaml.safe_load(ci)['backend-test']
        command = self.assert_mandatory_helper(job, HELPERS[0], 'backend')
        self.assertLess(job['before_script'].index(command), job['before_script'].index('pip install uv -q'))
        tree = self.helper_tree(HELPERS[0])
        self.assertEqual(self.literal(tree, 'MIRRORS'), MIRRORS)
        self.assertEqual(self.literal(tree, 'PACKAGES'), ['ffmpeg', 'sudo', 'nodejs', 'acl'])
        self.assertEqual(self.literal(tree, 'VERSIONS'), {
            'ffmpeg': ['ffmpeg', '-version'], 'sudo': ['sudo', '--version'],
            'nodejs': ['node', '--version'], 'acl': ['getfacl', '--version'],
            'npm': ['npm', '--version'],
        })
        for endpoint in ('https://mirrors.ustc.edu.cn/debian-security', 'https://mirrors.ustc.edu.cn/debian'):
            self.assertIn(endpoint, docker)

    def test_semantic_yaml_contract_rejects_wrong_values(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        source = (ROOT / '.gitlab-ci.yml').read_text()
        docker = (ROOT / 'Dockerfile').read_text()
        cases = [
            ('variables', 'PIP_INDEX_URL', 'http://pypi.tuna.tsinghua.edu.cn/simple', self.test_backend_sources_use_verified_https_endpoints),
            ('variables', 'PIP_INDEX_URL', 'https://example.invalid/simple', self.test_backend_sources_use_verified_https_endpoints),
            ('variables', 'PIP_DEFAULT_TIMEOUT', '31', self.test_retry_timeout_budgets_remain_bounded),
            ('variables', 'UV_HTTP_TIMEOUT', '300', self.test_retry_timeout_budgets_remain_bounded),
            ('variables', 'UV_HTTP_RETRIES', '3', self.test_retry_timeout_budgets_remain_bounded),
            ('backend-test', 'timeout', '16m', self.test_retry_timeout_budgets_remain_bounded),
        ]
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for filename in ('Dockerfile', 'Dockerfile.pg', *HELPERS):
                target = root / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text((ROOT / filename).read_text())
            (root / '.gitlab-ci.yml').write_text(source)
            with patch(__name__ + '.ROOT', root):
                self.test_backend_sources_use_verified_https_endpoints()
                self.test_browser_jobs_use_verified_signed_https_and_no_optional_desktop_packages()
                self.test_retry_timeout_budgets_remain_bounded()
                self.test_no_tls_signature_or_dependency_hash_bypass()
            for group, key, value, check in cases:
                parsed = yaml.safe_load(source)
                parsed[group][key] = value
                (root / '.gitlab-ci.yml').write_text(yaml.safe_dump(parsed, sort_keys=False))
                with self.subTest(variant=(key, value)), patch(__name__ + '.ROOT', root):
                    with self.assertRaises(AssertionError):
                        check()
            (root / '.gitlab-ci.yml').write_text(source)
            for before, after in [('Acquire::Retries=2', 'Acquire::Retries=3'),
                                  ('Acquire::https::Timeout=30', 'Acquire::https::Timeout=300')]:
                self.assertIn(before, docker)
                (root / 'Dockerfile').write_text(docker.replace(before, after))
                with self.subTest(variant=('Dockerfile', after)), patch(__name__ + '.ROOT', root):
                    with self.assertRaises(AssertionError):
                        self.test_retry_timeout_budgets_remain_bounded()
            (root / 'Dockerfile').write_text(docker)
            for job, mode, helper, check in (
                ('backend-test', 'backend', HELPERS[0], self.test_backend_sources_use_verified_https_endpoints),
                ('frontend-build', 'frontend', HELPERS[1], self.test_browser_jobs_use_verified_signed_https_and_no_optional_desktop_packages),
                ('experience-gate', 'experience', HELPERS[1], self.test_browser_jobs_use_verified_signed_https_and_no_optional_desktop_packages),
            ):
                command = 'python3 ' + helper + ' ' + mode
                for damage in ('missing', 'duplicate', 'ignored_failure', 'comment', 'wrong_mode', 'soft_job'):
                    parsed = yaml.safe_load(source)
                    setup = parsed[job]['before_script']
                    if damage == 'missing':
                        setup.remove(command)
                    elif damage == 'duplicate':
                        setup.append(command)
                    elif damage == 'soft_job':
                        parsed[job]['allow_failure'] = True
                    else:
                        setup[setup.index(command)] = {'ignored_failure': command + ' || true',
                            'comment': '# ' + command, 'wrong_mode': command + '-invalid'}[damage]
                    (root / '.gitlab-ci.yml').write_text(yaml.safe_dump(parsed, sort_keys=False))
                    with self.subTest(variant=(job, damage)), patch(__name__ + '.ROOT', root):
                        with self.assertRaises(AssertionError):
                            check()
            (root / '.gitlab-ci.yml').write_text(source)
            for helper in HELPERS:
                original = (ROOT / helper).read_text()
                budget_mutations = (
                    [('150 if index == 0 else 90', '151 if index == 0 else 90'),
                     ('150 if index == 0 else 90', '150 if index == 0 else 91')]
                    if helper == HELPERS[0] else
                    [('+ 150) if index == 0 else deadline', '+ 151) if index == 0 else deadline'),
                     ('else deadline', 'else time.monotonic() + 90'),
                     ('remaining <= 0', 'remaining < 0'),
                     ('apt(args, remaining)', 'apt(args, max(1, remaining))')]
                )
                for before, after, check in (
                    ("'https://mirrors.tuna.tsinghua.edu.cn', 'https://deb.debian.org'",
                     "'http://mirrors.tuna.tsinghua.edu.cn', 'https://deb.debian.org'",
                     self.test_backend_sources_use_verified_https_endpoints if helper == HELPERS[0] else self.test_browser_jobs_use_verified_signed_https_and_no_optional_desktop_packages),
                    ("'https://deb.debian.org')", "'http://deb.debian.org')",
                     self.test_backend_sources_use_verified_https_endpoints if helper == HELPERS[0] else self.test_browser_jobs_use_verified_signed_https_and_no_optional_desktop_packages),
                    ('+ 240', '+ 241', self.test_retry_timeout_budgets_remain_bounded),
                    *((before, after, self.test_retry_timeout_budgets_remain_bounded)
                      for before, after in budget_mutations),
                    ('*packages], 120)', '*packages], 121)', self.test_retry_timeout_budgets_remain_bounded),
                    ('Acquire::Retries=0', 'Acquire::Retries=2', self.test_retry_timeout_budgets_remain_bounded),
                    ('Acquire::https::Timeout=15', 'Acquire::https::Timeout=300', self.test_retry_timeout_budgets_remain_bounded),
                    ('raise RuntimeError(\'all bounded', 'print(\'all bounded', self.test_retry_timeout_budgets_remain_bounded),
                ):
                    self.assertIn(before, original)
                    (root / helper).write_text(original.replace(before, after, 1))
                    with self.subTest(variant=(helper, after)), patch(__name__ + '.ROOT', root):
                        with self.assertRaises(AssertionError):
                            check()
                    (root / helper).write_text(original)
            backend = (ROOT / HELPERS[0]).read_text()
            for before, after, check in (
                ("'nodejs': ['node', '--version']", "'nodejs': ['true']", self.test_backend_sources_use_verified_https_endpoints),
                ('start_new_session=True', 'start_new_session=False', self.test_retry_timeout_budgets_remain_bounded),
                ('os.killpg(proc.pid, signal.SIGKILL)', 'None', self.test_retry_timeout_budgets_remain_bounded),
                ('            proc.wait()\n', '            pass\n', self.test_retry_timeout_budgets_remain_bounded),
            ):
                self.assertIn(before, backend)
                (root / HELPERS[0]).write_text(backend.replace(before, after, 1))
                with self.subTest(variant=('backend version/process cleanup', after)), patch(__name__ + '.ROOT', root):
                    with self.assertRaises(AssertionError):
                        check()
                (root / HELPERS[0]).write_text(backend)
            browser = (ROOT / HELPERS[1]).read_text()
            for before, after in [("156.0.8078.47-1~deb12u1", "156.0.8078.48-1~deb12u1"),
                                  ("'chromium-common=' + CHROMIUM]", "'chromium-common=' + CHROMIUM, 'xterm']")]:
                self.assertIn(before, browser)
                (root / HELPERS[1]).write_text(browser.replace(before, after, 1))
                with self.subTest(variant=('browser version/packages', after)), patch(__name__ + '.ROOT', root):
                    with self.assertRaises(AssertionError):
                        self.test_browser_jobs_use_verified_signed_https_and_no_optional_desktop_packages()
                (root / HELPERS[1]).write_text(browser)
            # Trust and locked dependency negatives must hit assertions, not absent fixtures.
            for filename, before, after in [
                (HELPERS[0], 'Acquire::Retries=0', '--allow-unauthenticated'),
                (HELPERS[1], 'Acquire::Retries=0', 'Acquire::https::Verify-Peer=false'),
                ('.gitlab-ci.yml', '--require-hashes', '--no-deps'),
                ('Dockerfile', '--require-hashes', '--no-deps'),
            ]:
                original = (ROOT / filename).read_text()
                self.assertIn(before, original)
                (root / filename).write_text(original.replace(before, after, 1))
                with self.subTest(variant=(filename, after)), patch(__name__ + '.ROOT', root):
                    with self.assertRaises(AssertionError):
                        if filename in HELPERS:
                            self.assert_trusted_source(filename)
                        else:
                            self.test_no_tls_signature_or_dependency_hash_bypass()
                (root / filename).write_text(original)

    def assert_trusted_source(self, filename):
        source = (ROOT / filename).read_text()
        self.assertNotRegex(source, r"(?i)(trusted-host|allow-insecure-host|allow-unauthenticated|allow-insecure-repositories|trusted\s*=\s*yes|Verify-(?:Peer|Host)\s*=\s*false|curl\s+[^\n]*(?:--insecure|\s-k\b))")

    def test_no_tls_signature_or_dependency_hash_bypass(self):
        for filename in (".gitlab-ci.yml", "Dockerfile", "Dockerfile.pg", *HELPERS):
            with self.subTest(filename=filename):
                self.assert_trusted_source(filename)
        ci = (ROOT / ".gitlab-ci.yml").read_text()
        docker = (ROOT / "Dockerfile").read_text()
        self.assertIn("uv export --frozen --all-groups --no-emit-project", ci)
        self.assertIn('uv pip sync --index-url "$PIP_INDEX_URL" --require-hashes', ci)
        self.assertIn("uv export --frozen --no-dev --no-emit-project", docker)
        self.assertIn("--require-hashes /tmp/requirements.txt", docker)

    def test_retry_timeout_budgets_remain_bounded(self):
        ci = (ROOT / ".gitlab-ci.yml").read_text()
        parsed = yaml.safe_load(ci)
        self.assertEqual(parsed['backend-test']['timeout'], '25m')
        for key, value in (("PIP_DEFAULT_TIMEOUT", "30"), ("UV_HTTP_TIMEOUT", "30"), ("UV_HTTP_RETRIES", "2")):
            self.assertEqual(parsed['variables'][key], value)
        docker = (ROOT / 'Dockerfile').read_text()
        apt = re.findall(r"apt-get ([^\n]*?)(?:update|install)", docker)
        self.assertEqual(len(apt), 2)
        for options in apt:
            self.assertIn('Acquire::Retries=2', options.split())
            self.assertIn('Acquire::https::Timeout=30', options.split())
        for helper in HELPERS:
            self.assert_helper_budget(helper)
        self.assertIn("--timeout 30 --retries 2 uv", docker)
        self.assertIn("UV_HTTP_TIMEOUT=30 UV_HTTP_RETRIES=2 uv pip sync", docker)

    def test_browser_jobs_use_verified_signed_https_and_no_optional_desktop_packages(self):
        parsed = yaml.safe_load((ROOT / '.gitlab-ci.yml').read_text())
        for job, mode in [('frontend-build', 'frontend'), ('experience-gate', 'experience')]:
            self.assert_mandatory_helper(parsed[job], HELPERS[1], mode)
            self.assertEqual(parsed[job]['before_script'][-1], 'python3 ' + HELPERS[1] + ' ' + mode)
            self.assertEqual(parsed[job]['image'], NODE_IMAGE)
            self.assertEqual(parsed[job]['timeout'], '15m')
        tree = self.helper_tree(HELPERS[1])
        self.assertEqual(self.literal(tree, 'MIRRORS'), MIRRORS)
        self.assertEqual(self.literal(tree, 'CHROMIUM'), '156.0.8078.47-1~deb12u1')
        self.assert_syntax(tree, """MODES = {
            'frontend': ['chromium=' + CHROMIUM, 'chromium-common=' + CHROMIUM],
            'experience': ['chromium=' + CHROMIUM, 'chromium-common=' + CHROMIUM,
                           'ffmpeg', 'python3', 'python3-pil', 'git', 'nginx', 'openssl'],
        }""")
        self.assert_syntax(tree, "apt([*cache, '--no-download', '--no-install-recommends', 'install', '-y', *packages], 120)")

    def test_hardware_visual_and_isolated_gates_are_preserved(self):
        ci = (ROOT / ".gitlab-ci.yml").read_text()
        frontend = ci.split("frontend-build:\n", 1)[1].split("experience-gate:\n", 1)[0]
        for gate in ("vitest.hardware.config.mjs", "npm run test:monitor-loading", "src/modules/servers/hardware.visual.test.mjs"):
            self.assertIn(gate, frontend)
        self.assertIn('.venv/bin/python deploy/ci/run-backend-shard.py', ci)
        import importlib.util
        spec = importlib.util.spec_from_file_location('backend_shards_mirror', ROOT / 'deploy/ci/run-backend-shard.py')
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        total = yaml.safe_load(ci)['backend-test']['parallel']
        self.assertEqual(total, 7)
        commands = [cmd for index in range(1, total + 1) for cmd in module.plan(ROOT, index, total)]
        isolated = [cmd for cmd in commands if cmd[0].startswith('tests_isolated/')]
        self.assertCountEqual([cmd for cmd in commands if not cmd[0].startswith('tests_isolated/')], [list(cmd) for cmd in module.GROUP_COMMANDS] + [[str(p.relative_to(ROOT))] for d in ('tests_node_files','tests_node_files_delivery','tests_agent_unified','tests_agent_refresh_timeout') for p in sorted((ROOT/d).glob('test_*.py'))])
        expected = [[str(path.relative_to(ROOT)), '--noconftest'] for path in sorted((ROOT/'tests_isolated').glob('test_*.py'))]
        self.assertCountEqual(isolated, expected)
        self.assertEqual(yaml.safe_load(ci)['backend-test']['parallel'], 7)


if __name__ == "__main__":
    unittest.main()
