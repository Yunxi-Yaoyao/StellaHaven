"""Owned read-only-host/private-net acceptance; never a production service write."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON = '/opt/hermes-workstation/stella-production-closure-20261017/.venv/bin/python'
EVIDENCE = Path('/opt/hermes-workstation/docs/records/2026-10-24-stella-agent-unified/agent')


def main():
    phase, *tests = sys.argv[1:]
    scratch = Path(tempfile.mkdtemp(prefix='unified-agent-', dir=os.environ['TMPDIR']))
    (scratch/'root').mkdir(); (scratch/'root'/'synthetic.txt').write_text('isolated root fixture\n')
    env = {'PATH': '/usr/bin:/bin:/usr/sbin', 'HOME': '/root', 'TMPDIR': '/mnt', 'PYTHONPATH': str(ROOT),
           'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'UNIFIED_INSTALLER_SANDBOX': '1',
           'UNIFIED_ROOTFS': '1'}
    pytest = [PYTHON, '-m', 'pytest', '-c', '/dev/null', '--rootdir', str(ROOT), '-p', 'no:cacheprovider',
              '--junitxml', str(EVIDENCE/(phase+'.xml')), '-q'] + [str(ROOT/t) for t in tests]
    argv = ['unshare', '-n', PYTHON, '-I', '-c',
            'import os,subprocess,sys;subprocess.run(["/usr/sbin/ip","link","set","lo","up"],check=True);os.execv("/usr/sbin/bwrap",sys.argv[1:])',
            'bwrap', '--ro-bind', '/', '/', '--bind', str(scratch), '/mnt', '--bind', str(scratch/'root'), '/root',
            '--ro-bind', '/root/miniconda', '/root/miniconda', '--bind', str(EVIDENCE), str(EVIDENCE), '--proc', '/proc', '--dev', '/dev', '--unshare-pid', '--die-with-parent',
            '--chdir', '/mnt', *pytest]
    # bwrap namespace is selected by a separate privileged child only.
    result = subprocess.run(argv, env=env, cwd=scratch, capture_output=True, text=True, timeout=240)
    (EVIDENCE/(phase+'.log')).write_text(result.stdout+result.stderr)
    (EVIDENCE/(phase+'-isolation.json')).write_text(json.dumps({'argv': argv, 'env': env, 'host_scratch': str(scratch),
        'cwd': '/mnt', 'host_root_read_only': True, 'private_network': True, 'synthetic_root': True,
        'exit_code': result.returncode}, indent=2))
    print(result.stdout, result.stderr)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
