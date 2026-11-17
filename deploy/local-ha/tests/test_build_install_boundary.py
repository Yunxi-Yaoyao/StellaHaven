"""Offline contracts for real Docker/CI npm installation, not app/deploy tests.

Small shell grammar deliberately fails closed on unsupported npm invocations.
YAML block scalars and Docker continuations are parsed before checking commands.
"""
from pathlib import Path
import re
import shlex
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]


def installs(script, environment=None):
    env = {k.lower(): str(v).lower() for k, v in (environment or {}).items()}
    found = []
    # Preserve actual command boundaries, not physical continuation lines.
    script = re.sub(r"\\\r?\n", " ", script)
    for line in script.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        groups = [[]]
        for token in lexer:
            if token in {";", "&&", "||", "|", "&"}:
                groups.append([])
            else:
                groups[-1].append(token)
        for words in groups:
            if not words:
                continue
            local = dict(env)
            assignments = {}
            for token in words:
                if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*=", token):
                    k, v = token.split("=", 1)
                    assignments[k.lower()] = v.lower()
                else:
                    if token not in {"export", "env"}:
                        break
            local.update(assignments)
            if words[0] == "unset":
                for key in words[1:]:
                    env.pop(key.lower(), None)
                continue
            if words[0] == "export":
                env.update(assignments)
            elif len(assignments) == len(words):
                # A plain shell assignment is not exported unless inherited.
                env.update({k: v for k, v in assignments.items() if k in env})
            if "npm" not in words:
                continue
            index = words.index("npm")
            args = words[index + 1:]
            if args and args[0] in {"ci", "install", "i", "clean-install"}:
                ignored = local.get("npm_config_ignore_scripts") == "true"
                include_dev = local.get("npm_config_include") == "dev"
                for arg in args[1:]:
                    if arg in {"--ignore-scripts", "--ignore-scripts=true"}:
                        ignored = True
                    elif arg in {"--ignore-scripts=false", "--no-ignore-scripts"}:
                        ignored = False
                    elif arg == "--include=dev":
                        include_dev = True
                found.append((words, ignored, include_dev))
    return found


def real_installs(root=ROOT):
    result = []
    env = {}
    text = re.sub(r"\\\r?\n", " ", (root / "Dockerfile").read_text())
    for line in text.splitlines():
        if line.startswith("FROM "):
            env = {}
        elif line.startswith("ENV "):
            for entry in shlex.split(line[4:]):
                k, v = entry.split("=", 1)
                env[k] = v
        elif line.startswith("RUN "):
            result.extend(("Dockerfile", *item) for item in installs(line[4:], env))
    gh = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    for name, job in gh["jobs"].items():
        for step in job.get("steps", []):
            env = {**gh.get("env", {}), **job.get("env", {}), **step.get("env", {})}
            result.extend((f"GitHub:{name}", *item) for item in installs(step.get("run", ""), env))
    gl = yaml.safe_load((root / ".gitlab-ci.yml").read_text())
    for name, job in gl.items():
        if not isinstance(job, dict) or "script" not in job:
            continue
        env = {**gl.get("variables", {}), **job.get("variables", {})}
        scripts = job.get("before_script", []) + job.get("script", []) + job.get("after_script", [])
        result.extend((f"GitLab:{name}", *item) for item in installs("\n".join(scripts), env))
    return result


class BuildInstallBoundary(unittest.TestCase):
    def test_every_real_install_disables_lifecycle_and_includes_dev(self):
        found = real_installs()
        self.assertEqual(len(found), 4, found)
        for origin, words, ignored, dev in found:
            with self.subTest(origin=origin, command=words):
                self.assertTrue(ignored, "dependency lifecycle scripts enabled")
                self.assertTrue(dev, "build tools must be explicitly installed")

    def test_multiline_env_is_not_a_same_line_regex(self):
        cases = [
            ("export npm_config_ignore_scripts=true\nnpm ci --include=dev", True),
            ("npm_config_ignore_scripts=true \\\n npm ci --include=dev", True),
            ("npm ci \\\n --ignore-scripts --include=dev", True),
            ("# --ignore-scripts\nnpm ci --include=dev", False),
            ("npm_config_ignore_scripts=true echo unrelated\nnpm ci --include=dev", False),
            ("export npm_config_ignore_scripts=true\nnpm ci --no-ignore-scripts --include=dev", False),
            ("export npm_config_ignore_scripts=false\nnpm ci --include=dev", False),
            ("npm_config_ignore_scripts=true\nnpm ci --include=dev", False),
            ("export npm_config_ignore_scripts=true\nunset npm_config_ignore_scripts\nnpm ci --include=dev", False),
        ]
        for script, expected in cases:
            with self.subTest(script=script):
                self.assertEqual(installs(script)[0][1], expected)
        self.assertTrue(installs("npm ci --include=dev", {"npm_config_ignore_scripts": "true"})[0][1])

    def test_document_environment_scopes_and_multiline_blocks(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="stella-install-contract-") as directory:
            fixture = Path(directory)
            (fixture / ".github/workflows").mkdir(parents=True)
            (fixture / "Dockerfile").write_text(
                "FROM node AS frontend\nENV npm_config_ignore_scripts=true \\\n npm_config_include=dev\nRUN npm ci \\\n --no-audit\nFROM python\nRUN npm ci --include=dev\n"
            )
            (fixture / ".github/workflows/ci.yml").write_text(yaml.safe_dump({
                "jobs": {"frontend-build": {"env": {"npm_config_ignore_scripts": "false"}, "steps": [
                    {"env": {"npm_config_ignore_scripts": "true"}, "run": "npm ci \\\n --include=dev"},
                    {"run": "npm ci --include=dev"},
                ]}}
            }))
            (fixture / ".gitlab-ci.yml").write_text(yaml.safe_dump({
                "variables": {"npm_config_ignore_scripts": "false"},
                "frontend-build": {"before_script": ["export npm_config_ignore_scripts=true"],
                                   "script": ["npm ci \\\n --include=dev"]},
            }))
            found = real_installs(fixture)
            self.assertEqual([item[2] for item in found], [True, False, True, False, True])
            self.assertTrue(all(item[3] for item in found))

    def test_ci_validation_has_no_deploy_environment_or_persistent_token(self):
        gh = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        self.assertEqual(gh.get("permissions"), {"contents": "read"})
        for job in gh["jobs"].values():
            self.assertNotIn("environment", job)
            self.assertNotIn("secrets.", str(job))
            for step in job["steps"]:
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertIs(step.get("with", {}).get("persist-credentials"), False)
        gl = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text())
        for name in ("backend-test", "frontend-build", "experience-gate", "local-ha-contract", "build-images"):
            job = gl[name]
            self.assertNotIn("environment", job)
            # Inline guard precedes execution of repository code/install hooks.
            self.assertIn("STELLA_PRODUCTION_SSH_KEY", job["before_script"][0])
            self.assertIn("exit 1", job["before_script"][0])
            scripts = "\n".join(job.get("script", []))
            self.assertNotRegex(scripts, r"--(?:ui|api)(?:[=\s]|$)")

    def test_secret_guard_executes_before_repository_commands(self):
        import subprocess
        gl = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text())
        guard = gl["frontend-build"]["before_script"][0]
        clean = subprocess.run(["/bin/sh", "-c", guard], env={"PATH": "/usr/bin:/bin"}, capture_output=True)
        self.assertEqual(clean.returncode, 0)
        for key in re.findall(r"\$\{([A-Z_]+):-\}", guard):
            with self.subTest(key=key):
                blocked = subprocess.run(["/bin/sh", "-c", guard], env={"PATH": "/usr/bin:/bin", key: "synthetic-private-value"}, capture_output=True)
                self.assertNotEqual(blocked.returncode, 0)
                self.assertNotIn(b"synthetic-private-value", blocked.stdout + blocked.stderr)

    def test_runtime_build_does_not_retain_installer_caches(self):
        docker = (ROOT / "Dockerfile").read_text()
        self.assertIn("UV_NO_CACHE=1", docker)
        ignore = (ROOT / ".dockerignore").read_text().splitlines()
        for pattern in ("**/.env", "**/.env.*", "**/.npmrc", "**/.cache", "**/.npm", "**/.ssh", "**/node_modules", "**/__pycache__", "**/*.pyc"):
            self.assertIn(pattern, ignore)

    def test_explicit_application_build_is_retained(self):
        self.assertIn("RUN npm run build", (ROOT / "Dockerfile").read_text())
        gh = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        self.assertIn("npm run build", [s.get("run") for s in gh["jobs"]["frontend-build"]["steps"]])
        gl = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text())
        self.assertIn("npm run build", gl["frontend-build"]["script"])


if __name__ == "__main__":
    unittest.main()
