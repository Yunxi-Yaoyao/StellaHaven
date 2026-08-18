"""探测执行器：ping / tcp / http(s) / udp 可达性探测。

中心探测用（node_id 为 NULL 的监控项）。agent 探测走任务下发，不在这里。
"""
import socket
import subprocess
import time
from urllib.parse import urlparse

import httpx


def probe_ping(host: str, timeout: int) -> tuple[bool, float | None, float | None]:
    """ICMP ping（走系统 ping）。返回 (success, avg_ms, loss_pct)。"""
    try:
        out = subprocess.run(
            ["ping", "-c", "3", "-W", str(timeout), host],
            capture_output=True, text=True, timeout=timeout + 3,
        )
        if out.returncode != 0:
            return False, None, 100.0
        # 解析 "3 packets transmitted, 3 received, 0% packet loss" 和 "min/avg/max"
        loss = 100.0
        avg = None
        for line in out.stdout.splitlines():
            if "packet loss" in line:
                # "0% packet loss"
                pct = line.split("%")[0].strip().split()[-1]
                try:
                    loss = float(pct)
                except ValueError:
                    pass
            if "min/avg/max" in line or "min/avg/max/mdev" in line:
                # "rtt min/avg/max/mdev = 1.2/3.4/5.6/0.9 ms"
                nums = line.split("=")[-1].strip().split("/")
                if len(nums) >= 2:
                    try:
                        avg = float(nums[1])
                    except ValueError:
                        pass
        return loss < 100.0, avg, loss
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, None, 100.0


def probe_tcp(host: str, port: int, timeout: int) -> tuple[bool, float | None, float | None]:
    """TCP connect 探测。返回 (success, latency_ms, None)。"""
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency = (time.monotonic() - start) * 1000
            return True, latency, None
    except (socket.timeout, OSError, ConnectionRefusedError):
        return False, None, None


def probe_http(url: str, timeout: int) -> tuple[bool, float | None, float | None]:
    """HTTP(s) GET 探测，2xx/3xx 算通。返回 (success, latency_ms, None)。"""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    start = time.monotonic()
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        latency = (time.monotonic() - start) * 1000
        return resp.status_code < 400, latency, None
    except (httpx.HTTPError, httpx.TimeoutException):
        return False, None, None


def probe_udp(host: str, port: int, timeout: int) -> tuple[bool, float | None, float | None]:
    """UDP 探测：sendto + 收 ICMP unreachable（有回=端口不可达，无回=可能通）。

    UDP 无连接，语义上「没收到不可达」只能算「可能通」。个人工具够用。
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(b"\x00", (host, port))
        try:
            sock.recvfrom(1024)
            return True, None, None  # 收到任何回包 = 通
        except socket.timeout:
            return True, None, None  # 超时无不可达 = 可能通
    except OSError:
        return False, None, None


def run_probe(mtype: str, target: str, timeout: int) -> tuple[bool, float | None, float | None]:
    """按类型分发探测。target 解析规则：
    - ping: host
    - tcp/udp: host:port
    - http/https: url
    """
    mtype = mtype.lower()
    if mtype == "ping":
        return probe_ping(target, timeout)
    if mtype == "tcp":
        host, _, port = _split_host_port(target)
        return probe_tcp(host, port, timeout)
    if mtype == "udp":
        host, _, port = _split_host_port(target)
        return probe_udp(host, port, timeout)
    if mtype in ("http", "https"):
        return probe_http(target, timeout)
    return False, None, None


def _split_host_port(target: str) -> tuple[str, str, int]:
    """'host:port' 或 'host'（默认 80）→ (host, port_str, port_int)。"""
    if ":" in target and not target.startswith("["):
        host, port = target.rsplit(":", 1)
    else:
        host, port = target, "80"
    return host, port, int(port)
