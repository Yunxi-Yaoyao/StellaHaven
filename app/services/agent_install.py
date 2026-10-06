"""Root-only agent privilege installation; never called merely by importing.

Docker access is exclusively the fixed helper; networking grants are managed
separately and intentionally retained for authorized server-admin operations.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HELPER_PATH = Path('/usr/local/libexec/stella-docker-helper')
DOCKER_CONFIG = Path('/etc/stella-agent/docker')
SUDOERS_PATH = Path('/etc/sudoers.d/stella-docker')
HELPER_SOURCE = Path(__file__).resolve().parents[2] / 'deploy/agent-privileges/stella-docker-helper.py'


def docker_sudoers():
    return ''.join(f'stella ALL=(root) NOPASSWD: {HELPER_PATH} {action}{suffix}\n'
                   for action, suffix in [('ps', ''), ('inspect', ' *'), ('logs', ' *'),
                                          ('start', ' *'), ('stop', ' *'), ('restart', ' *')])


def _trusted_directory(path):
    # Check before mkdir too: no attacker-writable/symlink ancestor is acceptable.
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise PermissionError('symlink privilege directory refused')
        if part.exists():
            st = part.stat()
            if not part.is_dir() or st.st_uid != 0 or st.st_mode & 0o022:
                raise PermissionError('privilege directory must be root-owned and not group/world writable')
    path.mkdir(parents=True, exist_ok=True, mode=0o755)


def _root_file(path, text, mode, validator=None):
    _trusted_directory(path.parent)
    if path.is_symlink():
        raise PermissionError('symlink privilege file refused')
    fd, stage = tempfile.mkstemp(prefix='.stella-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(stage, 0, 0)
        os.chmod(stage, mode)
        if validator:
            validator(stage)
        os.replace(stage, path)
    finally:
        Path(stage).unlink(missing_ok=True)


def remove_legacy_docker_grants(content):
    """Remove only installer-owned bare Docker grants; retain admin networking.

    Refuse unfamiliar Docker sudoers syntax instead of guessing at aliases,
    continuations, wildcards or caller-authored rules. Audit other files manually.
    """
    lines = []
    prefix = 'stella ALL=(root) NOPASSWD: '
    for line in content.splitlines():
        if 'docker' not in line or line.lstrip().startswith('#'):
            lines.append(line)
            continue
        if not line.startswith(prefix) or '\\' in line:
            raise ValueError('unrecognized legacy Docker sudoers; manual review required')
        for command in line[len(prefix):].split(','):
            command = command.strip()
            if command.startswith('/') and len(command.split()) == 1 and Path(command).name == 'docker':
                continue
            lines.append(prefix + command)
    return '\n'.join(lines) + '\n'


def install_privileges():
    if os.geteuid() != 0:
        raise PermissionError('agent privilege installation requires root')
    visudo = shutil.which('visudo')
    if not visudo:
        raise RuntimeError('visudo is required to install agent privileges')
    source = HELPER_SOURCE.read_text(encoding='utf-8')
    compile(source, str(HELPER_SOURCE), 'exec')
    _trusted_directory(DOCKER_CONFIG)
    _root_file(HELPER_PATH, source, 0o755)
    _root_file(SUDOERS_PATH, docker_sudoers(), 0o440,
               lambda stage: subprocess.run([visudo, '-cf', stage], check=True,
                                             capture_output=True, text=True, timeout=10))
