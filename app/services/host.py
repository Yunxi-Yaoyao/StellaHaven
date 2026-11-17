"""宿主机（Stella 宿主本机）检测与一键安装。"""
import platform
import os
import shutil
import subprocess
import json
from pathlib import Path
from app.services.agent_install import install_privileges, remove_legacy_docker_grants, _root_file

AGENT_SERVICE = "stella-agent"
AGENT_DIR = "/opt/stella-agent"
# Explicit host role slot, scoped again by authenticated center_id in installer.
# Never use the center's default slot (which may belong to a demonstration node).
HOST_INSTANCE = 'host'


def detect_os() -> str:
    """本机 OS（静态，探一次存进节点 platform）。Linux 取发行版名（Ubuntu/CentOS/Debian/Arch…）。"""
    system = platform.system()
    if system == "Linux":
        return _linux_distro()
    return system.lower()


def _linux_distro() -> str:
    """读 /etc/os-release 取发行版友好名（CentOS Linux→CentOS，Debian GNU/Linux→Debian）。"""
    name = ""
    try:
        info = platform.freedesktop_os_release()  # Python 3.10+
        name = info.get("NAME", "")
    except Exception:
        pass
    if not name:
        try:
            with open("/etc/os-release", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("NAME="):
                        name = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass
    for suffix in (" GNU/Linux", " Linux"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name or "linux"


def supports_local_install() -> bool:
    """A container's local process namespace is not the managed host."""
    return not (os.environ.get('KUBERNETES_SERVICE_HOST') or Path('/.dockerenv').exists() or Path('/run/.containerenv').exists())


def is_agent_installed() -> bool:
    """agent 是否在运行（动态，每次查 systemctl/pgrep）。"""
    return _is_agent_installed()


def _is_agent_installed() -> bool:
    if shutil.which("systemctl"):
        try:
            r = subprocess.run(["systemctl", "is-active", AGENT_SERVICE],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    if shutil.which("pgrep"):
        try:
            r = subprocess.run(["pgrep", "-f", "stella_agent.py"],
                               capture_output=True, timeout=5)
            if r.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
    return False


def install_host(token: str, center_url: str) -> dict:
    """Use the authenticated per-center installer; never claim a global process."""
    import re
    if not supports_local_install():
        raise ValueError('Stella 运行在容器内；请在真实宿主机执行本站安装命令')
    if platform.system() != 'Linux':
        raise ValueError('本机自动安装仅支持 Linux；请在宿主机执行对应平台安装命令')
    if os.geteuid() != 0:
        raise ValueError('本站进程没有 root 权限；请在真实宿主机以管理员执行本站安装命令')
    missing = [name for name in ('bash', 'python3', 'systemctl', 'visudo', 'useradd') if not shutil.which(name)]
    if missing:
        raise ValueError('本机缺少安装依赖：' + ', '.join(missing) + '；请准备依赖后重试')
    if not token or not center_url or any(c in token + center_url for c in '\r\n'):
        raise ValueError('本站安装地址或节点凭证无效')
    script = Path(__file__).resolve().parents[2] / 'agent' / 'install.sh'
    try:
        result = subprocess.run(['/bin/bash', str(script), '--url', center_url, '--instance', HOST_INSTANCE, '--no-deps'],
            env={**os.environ, 'STELLA_TOKEN': token}, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise ValueError('本机安装超时（180 秒），不能确认安装完成；请检查本站实例服务后重试，未接管原 Agent') from None
    except OSError:
        raise ValueError('无法启动本机安装器；请检查执行权限与本站安装脚本') from None
    if result.returncode != 0:
        # Installer output can contain capability material. Expose its outcome,
        # not raw stdout/stderr; existing instances remain installer-owned.
        raise ValueError(f'本机安装器失败（退出码 {result.returncode}）：中心认证、工件校验或实例安装未完成；请检查本站地址与宿主依赖，未接管原 Agent')
    match = re.search(r'stella-agent-[a-f0-9]{24}', result.stdout)
    if not match:
        raise ValueError('安装器未返回本站实例服务凭据，不能确认安装完成')
    return {'installed': True, 'service': match.group(0)}


def uninstall_host() -> None:
    """Unscoped center-side removal must never target the legacy host service."""
    raise ValueError('Explicit authenticated agent instance is required for uninstall')


def _ensure_user() -> None:
    """创建独立系统用户 stella（PBR 按 UID 识别 + 最小权限）。"""
    if shutil.which("id"):
        r = subprocess.run(["id", "-u", "stella"], capture_output=True)
        if r.returncode == 0:
            return
    if shutil.which("useradd"):
        subprocess.run(["useradd", "--system", "--no-create-home",
                        "--shell", "/usr/sbin/nologin", "stella"],
                       check=False, capture_output=True)


def _ensure_sudoers() -> None:
    """Install explicit uninstall rules, retain authorized networking, remove old Docker grant."""
    sysctl = shutil.which("systemctl") or "/usr/sbin/systemctl"
    rm = shutil.which("rm") or "/usr/bin/rm"
    content = (
        f"stella ALL=(root) NOPASSWD: {sysctl} stop stella-agent, "
        f"{sysctl} disable stella-agent, {sysctl} daemon-reload, "
        f"{rm} -f /etc/systemd/system/stella-agent.service, "
        f"{rm} -rf /opt/stella-agent\n"
    )
    p = Path("/etc/sudoers.d/stella-uninstall")
    existing = remove_legacy_docker_grants(p.read_text()) if p.exists() else ''
    # New rules are one command per line; do not erase prior network/WG grants.
    prefix = 'stella ALL=(root) NOPASSWD: '
    commands = content.strip()[len(prefix):].split(', ')
    lines: list[str] = [str(line) for line in existing.splitlines()]
    for command in commands:
        line = prefix + command
        if line not in lines:
            lines.append(line)
    visudo = shutil.which('visudo')
    if not visudo:
        raise RuntimeError('visudo required')
    _root_file(p, '\n'.join(lines) + '\n', 0o440,
               lambda stage: subprocess.run([visudo, '-cf', stage], check=True,
                                             capture_output=True, timeout=10))
