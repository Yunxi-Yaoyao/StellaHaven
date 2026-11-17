"""Real root installer + root/legacy-UID permission probes (no live tools)."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer_fixture", ROOT / "tests_isolated/test_agent_installer.py")
assert spec is not None and spec.loader is not None
fixture_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)


@pytest.fixture
def installer():
    fixture = fixture_module.LinuxInstances("runTest")
    fixture.setUp()
    try:
        fixture.root.chmod(0o755)  # probe must be able to search its own cwd
        # Model the already-existing trusted OS ancestors, not mkdir(parents=True)
        # intermediates invented by a relocated /etc or /usr in the fixture.
        for name in ("etc", "etc/systemd", "etc/systemd/system", "usr", "usr/local"):
            path = fixture.root / name
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o755)
        (fixture.root / "etc/sudoers.d").mkdir(mode=0o750)
        source = Path(os.environ.get("INSTALLER_UMASK_SOURCE", ROOT / "agent/install.sh"))
        text = source.read_text()
        for base in ("/opt/stella-agents", "/etc/stella-agents", "/etc/systemd/system", "/etc/sudoers.d", "/usr/local/libexec"):
            text = text.replace(base, str(fixture.root) + base)
        fixture.script.write_text(text)
        yield fixture
    finally:
        fixture.tearDown()


def install_with_umask(fixture, mask):
    result = subprocess.run(
        ["/bin/bash", "-c", 'umask "$1"; shift; exec /bin/bash "$@"', "fixture", mask,
         str(fixture.script), "--url", fixture.url, "--token", fixture_module.TOKEN, "--no-deps"],
        env=fixture.env, text=True, capture_output=True, timeout=15,
    )
    assert fixture_module.TOKEN not in result.stdout + result.stderr
    assert fixture.legacy.read_bytes() == b"legacy opaque sentinel"
    return result


def permission_probe(fixture, uid=65001):
    iid = fixture_module.instance_id(fixture_module.CENTER_A)
    # Enter the fixture before dropping privileges: the shared scratch home's
    # private ancestors remain 0700, and are deliberately NOT chmodded.
    probe = r'''
import json, os, pathlib, sys
os.chdir(sys.argv[1]); uid = int(sys.argv[3])
os.setgroups([]); os.setgid(uid); os.setuid(uid)
assert os.geteuid() == uid and os.getegid() == uid
iid = sys.argv[2]
paths = {'manifest': 'etc/stella-agents/'+iid+'/instance.json',
         'code': 'opt/stella-agents/'+iid+'/stella_agent.py',
         'secret': 'etc/stella-agents/'+iid+'/agent.env',
         'helper': 'usr/local/libexec/stella-agent-'+iid}
result = {}
for name, path in paths.items():
    try: pathlib.Path(path).read_bytes(); result[name] = 'readable'
    except PermissionError: result[name] = 'PermissionError'
print(json.dumps(result, sort_keys=True))
'''
    result = subprocess.run([sys.executable, "-I", "-c", probe, str(fixture.root), iid, str(uid)],
                            env=fixture.env, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def assert_permission_plan(fixture):
    iid = fixture_module.instance_id(fixture_module.CENTER_A)
    expected = {
        "opt/stella-agents": (0o755, 0),
        "etc/stella-agents": (0o755, 0),
        "usr/local/libexec": (0o755, 0),
        "etc/stella-agents/" + iid: (0o755, 0),
        "etc/stella-agents/" + iid + "/instance.json": (0o644, 0),
        "etc/stella-agents/" + iid + "/agent.env": (0o600, 0),
        "etc/stella-agents/." + iid + ".lock": (0o600, 0),
        "opt/stella-agents/" + iid: (0o700, 0),
        "opt/stella-agents/" + iid + "/stella_agent.py": (0o700, 0),
        "opt/stella-agents/" + iid + "/.update.lock": (0o600, 0),
        "etc/systemd/system/stella-agent-" + iid + ".service": (0o644, 0),
        "etc/sudoers.d/stella-agent-" + iid: (0o440, 0),
        "usr/local/libexec/stella-agent-" + iid: (0o755, 0),
    }
    actual = {}
    for name, (mode, uid) in expected.items():
        path = fixture.root / name
        st = path.lstat()
        assert not path.is_symlink()
        actual[name] = [oct(stat.S_IMODE(st.st_mode)), st.st_uid, st.st_gid]
        assert (stat.S_IMODE(st.st_mode), st.st_uid, st.st_gid) == (mode, uid, uid), actual
        assert not st.st_mode & 0o022
    # Do not widen an unrelated pre-existing restricted system directory.
    assert stat.S_IMODE((fixture.root / "etc/sudoers.d").stat().st_mode) == 0o750
    unit = (fixture.root / ("etc/systemd/system/stella-agent-" + iid + ".service")).read_text()
    assert "\nUser=root\n" in unit and "\nGroup=root\n" in unit
    assert fixture_module.TOKEN not in unit
    # The legacy account remains only for scoped removal compatibility. It must
    # not read root-private code or credentials; the actual service UID can.
    assert permission_probe(fixture, uid=0) == {"manifest": "readable", "code": "readable", "secret": "readable", "helper": "readable"}
    print("PERMISSION_PLAN", json.dumps(actual, sort_keys=True))


def test_umask_077_allows_instance_uid_public_reads_but_not_secret(installer):
    # Keep this historical collector ID; the instance service now runs as root,
    # while UID 65001 still exercises the unrelated/legacy-account boundary.
    result = install_with_umask(installer, "077")
    assert result.returncode == 0, result.stderr
    observed = permission_probe(installer)
    print("DROPPED_UID_PROBE", json.dumps(observed, sort_keys=True))
    assert observed == {"manifest": "readable", "code": "PermissionError", "secret": "PermissionError", "helper": "readable"}
    assert_permission_plan(installer)


@pytest.mark.parametrize("mask", ["022", "027"])
def test_other_umasks_keep_the_same_explicit_permission_plan(installer, mask):
    result = install_with_umask(installer, mask)
    assert result.returncode == 0, result.stderr
    assert permission_probe(installer) == {"manifest": "readable", "code": "PermissionError", "secret": "PermissionError", "helper": "readable"}
    assert_permission_plan(installer)


@pytest.mark.parametrize("restricted", ["instance-config", "all-public-paths"])
def test_reinstall_repairs_trusted_0700_public_dirs_without_widening_secret(installer, restricted):
    assert install_with_umask(installer, "022").returncode == 0
    iid = fixture_module.instance_id(fixture_module.CENTER_A)
    secret = installer.root / "etc/stella-agents" / iid / "agent.env"
    before_secret = (secret.read_bytes(), secret.stat().st_mode, secret.stat().st_uid)
    paths = ["etc/stella-agents/" + iid]
    if restricted == "all-public-paths":
        paths += ["opt/stella-agents", "etc/stella-agents", "usr/local/libexec"]
    for name in paths:
        (installer.root / name).chmod(0o700)
    before_probe = permission_probe(installer)
    print("REPAIR_BEFORE", restricted, json.dumps(before_probe, sort_keys=True))
    assert before_probe["manifest"] == "PermissionError"
    if restricted == "instance-config":
        assert before_probe == {"manifest": "PermissionError", "code": "PermissionError", "secret": "PermissionError", "helper": "readable"}
        manifest = installer.root / paths[0] / "instance.json"
        assert (stat.S_IMODE(manifest.stat().st_mode), manifest.stat().st_uid) == (0o644, 0)
    else:
        assert before_probe == {"manifest": "PermissionError", "code": "PermissionError", "secret": "PermissionError", "helper": "PermissionError"}
    result = install_with_umask(installer, "077")
    assert result.returncode == 0, result.stderr
    assert permission_probe(installer) == {"manifest": "readable", "code": "PermissionError", "secret": "PermissionError", "helper": "readable"}
    assert_permission_plan(installer)
    assert (secret.read_bytes(), secret.stat().st_mode, secret.stat().st_uid) == before_secret
    assert len([call for call in installer.calls() if call[0] == "useradd"]) == 1


def tree_state(fixture):
    result = {}
    for folder in ("opt", "etc", "usr"):
        for path in (fixture.root / folder).rglob("*"):
            st = path.lstat()
            contents = os.readlink(path) if path.is_symlink() else path.read_bytes() if path.is_file() else None
            result[str(path.relative_to(fixture.root))] = (st.st_mode, st.st_uid, st.st_gid, contents)
    return result


@pytest.mark.parametrize("name", ["opt/stella-agents", "etc/stella-agents", "usr/local/libexec", "instance-config"])
@pytest.mark.parametrize("attack", ["symlink", "writable", "foreign-owner"])
def test_permission_repair_does_not_adopt_untrusted_paths(installer, name, attack):
    assert install_with_umask(installer, "022").returncode == 0
    if name == "instance-config":
        name = "etc/stella-agents/" + fixture_module.instance_id(fixture_module.CENTER_A)
    path = installer.root / name
    if attack == "symlink":
        held = path.with_name(path.name + ".held")
        path.rename(held)
        path.symlink_to(held, target_is_directory=True)
    elif attack == "writable":
        path.chmod(0o777)
    else:
        os.chown(path, 65002, 65002)
    before = tree_state(installer)
    calls = len(installer.calls())
    result = install_with_umask(installer, "077")
    assert result.returncode != 0
    assert tree_state(installer) == before
    assert not any(call[0] in ("useradd", "userdel", "systemctl", "visudo") for call in installer.calls()[calls:])
