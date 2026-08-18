"""宿主机（Stella 宿主本机）检测与一键安装。"""
import platform
import shutil
import subprocess
from pathlib import Path

AGENT_SERVICE = "stella-agent"
AGENT_DIR = "/opt/stella-agent"


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


def install_host(token: str, center_url: str = "http://127.0.0.1:12031") -> dict:
    """本机一键安装 agent：创建独立用户 + 复制脚本 + 写 systemd 单元 + 启动。"""
    _ensure_user()
    _ensure_sudoers()

    src = Path(__file__).resolve().parents[2] / "agent" / "stella_agent.py"
    dst_dir = Path(AGENT_DIR)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / "stella_agent.py"
    dst.write_text(src.read_text(encoding="utf-8"))
    dst.chmod(0o755)

    unit = (
        "[Unit]\n"
        "Description=Stella Agent\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        "User=stella\n"
        "AmbientCapabilities=CAP_NET_RAW\n"
        f"ExecStart=/usr/bin/env python3 {dst} --url {center_url} --token {token}\n"
        "Restart=always\n"
        "RestartSec=5\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )
    Path(f"/etc/systemd/system/{AGENT_SERVICE}.service").write_text(unit)

    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "enable", AGENT_SERVICE], check=False, capture_output=True)
    subprocess.run(["systemctl", "restart", AGENT_SERVICE], check=False, capture_output=True)

    return {"installed": True, "service": AGENT_SERVICE}


def uninstall_host() -> None:
    """卸载本机 agent：disable → 删 unit → daemon-reload → 删目录 → stop（防 Restart=always 复活）。"""
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "disable", AGENT_SERVICE], check=False, capture_output=True)
    Path(f"/etc/systemd/system/{AGENT_SERVICE}.service").unlink(missing_ok=True)
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "daemon-reload"], check=False, capture_output=True)
    shutil.rmtree(AGENT_DIR, ignore_errors=True)
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "stop", AGENT_SERVICE], check=False, capture_output=True)


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
    """给 stella 用户 sudo 权限（仅卸载命令白名单，NOPASSWD）。"""
    sysctl = shutil.which("systemctl") or "/usr/sbin/systemctl"
    rm = shutil.which("rm") or "/usr/bin/rm"
    content = (
        f"stella ALL=(root) NOPASSWD: {sysctl} stop stella-agent, "
        f"{sysctl} disable stella-agent, {sysctl} daemon-reload, "
        f"{rm} -f /etc/systemd/system/stella-agent.service, "
        f"{rm} -rf /opt/stella-agent\n"
    )
    p = Path("/etc/sudoers.d/stella-uninstall")
    p.write_text(content)
    p.chmod(0o440)
