"""Offline regression contract for verified build sources and trust budgets.

The network/install evidence is collected separately in disposable containers;
these tests never contact a database, registry, or software mirror.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BuildMirrorContract(unittest.TestCase):
    def test_backend_sources_use_verified_https_endpoints(self):
        ci = (ROOT / ".gitlab-ci.yml").read_text()
        docker = (ROOT / "Dockerfile").read_text()
        backend = ci.split("backend-test:\n", 1)[1].split("frontend-build:\n", 1)[0]
        self.assertIn('PIP_INDEX_URL: "https://pypi.org/simple"', ci)
        for source in (backend, docker):
            with self.subTest(source="backend" if source == backend else "Dockerfile"):
                self.assertNotIn("tuna.tsinghua.edu.cn", source)
                self.assertIn("https://mirrors.ustc.edu.cn/debian-security", source)
                self.assertIn("https://mirrors.ustc.edu.cn/debian", source)
        self.assertEqual(docker.count("--index-url https://pypi.org/simple"), 2)

    def test_no_tls_signature_or_dependency_hash_bypass(self):
        for filename in (".gitlab-ci.yml", "Dockerfile", "Dockerfile.pg"):
            source = (ROOT / filename).read_text()
            with self.subTest(filename=filename):
                self.assertNotRegex(source, r"(?i)(trusted-host|allow-insecure-host|allow-unauthenticated|allow-insecure-repositories|trusted\s*=\s*yes|Verify-(?:Peer|Host)\s*=\s*false|curl\s+[^\n]*(?:--insecure|\s-k\b))")
        ci = (ROOT / ".gitlab-ci.yml").read_text()
        docker = (ROOT / "Dockerfile").read_text()
        self.assertIn("uv export --frozen --all-groups --no-emit-project", ci)
        self.assertIn('uv pip sync --index-url "$PIP_INDEX_URL" --require-hashes', ci)
        self.assertIn("uv export --frozen --no-dev --no-emit-project", docker)
        self.assertIn("--require-hashes /tmp/requirements.txt", docker)

    def test_retry_timeout_budgets_remain_bounded(self):
        ci = (ROOT / ".gitlab-ci.yml").read_text()
        backend = ci.split("backend-test:\n", 1)[1].split("frontend-build:\n", 1)[0]
        self.assertIn("timeout: 15m", backend)
        for key, value in (("PIP_DEFAULT_TIMEOUT", "30"), ("UV_HTTP_TIMEOUT", "30"), ("UV_HTTP_RETRIES", "2")):
            self.assertIn(f'{key}: "{value}"', ci)
        for source in (backend, (ROOT / "Dockerfile").read_text()):
            apt = re.findall(r"apt-get ([^\n]*?)(?:update|install)", source)
            self.assertEqual(len(apt), 2)
            for options in apt:
                self.assertIn("Acquire::Retries=2", options)
                self.assertIn("Acquire::https::Timeout=30", options)
        docker = (ROOT / "Dockerfile").read_text()
        self.assertIn("--timeout 30 --retries 2 uv", docker)
        self.assertIn("UV_HTTP_TIMEOUT=30 UV_HTTP_RETRIES=2 uv pip sync", docker)

    def test_hardware_visual_and_isolated_gates_are_preserved(self):
        ci = (ROOT / ".gitlab-ci.yml").read_text()
        frontend = ci.split("frontend-build:\n", 1)[1].split("experience-gate:\n", 1)[0]
        for gate in ("vitest.hardware.config.mjs", "npm run test:monitor-loading", "src/modules/servers/hardware.visual.test.mjs"):
            self.assertIn(gate, frontend)
        self.assertIn('for file in tests_isolated/test_*.py; do .venv/bin/python -m pytest -q "$file" --noconftest || exit $?; done', ci)


if __name__ == "__main__":
    unittest.main()
