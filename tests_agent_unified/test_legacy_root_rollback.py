"""Frozen real .18 producer -> failed .19 root transition, real UID readback."""
import hashlib
import os
import stat
import subprocess
from pathlib import Path
from tests_agent_unified.conftest import admitted_os_fixture
from tests_agent_unified.test_root_installer import old


def metadata(path):
    st = path.stat()
    return st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)


def legacy_can_read(code):
    script = "import os,sys;os.chdir(sys.argv[1]);os.setgroups([]);os.setgid(65001);os.setuid(65001);open('stella_agent.py','rb').read()"
    return subprocess.run(['/usr/bin/python3','-I','-c',script,str(code)], capture_output=True, text=True).returncode


def test_failed_root_transition_restores_actual_legacy_directory_and_lock():
    fixture = old.LinuxInstances(methodName='runTest')
    fixture.setUp()
    try:
        candidate = fixture.script.read_text()
        baseline = Path(__file__).with_name('legacy_install.sh.txt').read_text()
        assert hashlib.sha256(baseline.encode()).hexdigest() == '4bc88965cc990261fc94c81777c1572de6c76ea5372101e9c7952f61fadbf130'
        for path in ('/opt/stella-agents','/etc/stella-agents','/etc/systemd/system','/etc/sudoers.d','/usr/local/libexec'):
            baseline = baseline.replace(path, str(fixture.root) + path)
        fixture.script.write_text(baseline)
        result = fixture.install()
        assert result.returncode == 0, result.stderr
        code = fixture.code()
        lock = code / '.update.lock'
        before = metadata(code), metadata(lock), legacy_can_read(code)
        assert before == ((65001,65001,0o700),(65001,65001,0o600),0)
        fixture.script.write_text(candidate)
        fixture.body += b'# candidate upgrade\n'
        result = fixture.install({'FAIL_RESTART':'1'})
        assert result.returncode != 0
        unit = fixture.root / 'etc/systemd/system' / ('stella-agent-' + old.instance_id(old.CENTER_A) + '.service')
        assert 'User=sta' + old.instance_id(old.CENTER_A) + '\n' in unit.read_text()
        assert (metadata(code), metadata(lock), legacy_can_read(code)) == before
    finally:
        fixture.tearDown()
