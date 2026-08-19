#!/usr/bin/env python3
"""Stella Agent — 被纳管服务器的采集上报 + 任务执行客户端。

单文件，仅依赖标准库 + psutil + httpx（跨 Linux / Windows / 飞牛OS）。

职责：
1. 采集本机数据：网卡流量（默认出口网卡）、系统指标（CPU/内存/磁盘）
2. 5s 上报流量 + 60s 上报系统指标（上报即心跳）
3. 内存队列补传：上报失败时数据压队列，恢复后按时间顺序批量补传
4. 5s 轮询待办任务（打流/MTR/命令），执行后回传结果
5. 检测默认出口网卡（默认路由），上报网卡清单供中心配置监控范围

用法：
    stella-agent --url http://<stella>:12031 --token <token>
    或环境变量 STELLA_URL / STELLA_TOKEN
"""
import argparse
import json
import os
import platform
import re
import select
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone

try:
    import psutil
except ImportError:
    psutil = None

try:
    import httpx
except ImportError:
    httpx = None


AGENT_VERSION = "0.6.0"
REPORT_INTERVAL = 5       # 流量上报间隔（秒）
SYS_INTERVAL = 60         # 系统指标上报间隔（秒）
MTR_INTERVAL = 1800       # 监控项定时 MTR 周期（30 分钟）
MTR_FAIL_DEBOUNCE = 600   # 失败触发 MTR 防抖（10 分钟）
POLL_INTERVAL = 1         # 任务轮询间隔（秒）——打流领取要快，1s 让图表几乎秒出
UPDATE_CHECK_INTERVAL = 300  # 版本自更新检查间隔（秒）
QUEUE_MAX = 24 * 3600 // REPORT_INTERVAL  # 队列上限 = 24h 的采样点数


class Agent:
    def __init__(self, url: str, token: str):
        if "://" not in url:
            url = "https://" + url
        self.url = url.rstrip("/")
        self.token = token
        self.queue = deque(maxlen=QUEUE_MAX)  # 内存队列：补传用
        self.last_net = None  # 上次网卡累计字节 {iface: (rx, tx)}
        self.monitored_ifaces = None  # 中心下发的监控网卡列表
        self.monitors_version = 0  # 监控项配置版本号（心跳 diff 用）
        self.monitors = {}  # monitor_id -> {type, target, interval, timeout, next_run}
        self._check_deps()

    def _check_deps(self):
        """依赖检查：httpx / psutil 缺失只降级，不 crash。"""
        if httpx is None:
            print("[warn] httpx 未安装，用 urllib 兜底", file=sys.stderr)
        if psutil is None:
            print("[warn] psutil 未安装，系统指标/网卡清单降级", file=sys.stderr)

    def _agent_bin(self) -> str:
        """agent 目录下的 bin/（install.sh 已 chown 给 stella，可写，放代装的单文件组件）。"""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")

    def _check_components(self) -> dict:
        """检测打流相关组件 + 防火墙是否安装（前端显示绿/红，未装可代装）。"""
        iperf3 = shutil.which("iperf3") is not None
        speedtest = any(shutil.which(x) for x in ("speedtest-go", "speedtest", "speedtest-cli")) \
            or os.path.exists(os.path.join(self._agent_bin(), "speedtest-go"))
        return {"iperf3": iperf3, "speedtest": speedtest, "firewall": self._check_firewall(),
                "docker": self._check_docker(), "mtr": shutil.which("mtr") is not None}

    def _check_docker(self) -> dict:
        """检测 Docker：是否安装 + 守护进程是否运行（systemctl is-active 查询不需要 root）。"""
        installed = shutil.which("docker") is not None
        running = False
        if installed:
            try:
                r = subprocess.run(["systemctl", "is-active", "docker"], capture_output=True, text=True, timeout=5)
                running = (r.stdout or "").strip() == "active"
            except Exception:
                pass
        return {"installed": installed, "running": running}

    def _check_firewall(self) -> dict:
        """检测防火墙：ufw / iptables 是否安装 + ufw 是否启用。
        ufw status 要 root（sudo -n，install.sh 白名单已放），不带 sudo 会误报未启用。"""
        ufw_installed = shutil.which("ufw") is not None
        ufw_active = False
        if ufw_installed:
            try:
                r = subprocess.run(["sudo", "-n", "ufw", "status"], capture_output=True, text=True, timeout=5)
                ufw_active = "Status: active" in (r.stdout or "")
            except Exception:
                pass
        iptables_installed = shutil.which("iptables") is not None
        return {"ufw": {"installed": ufw_installed, "active": ufw_active},
                "iptables": {"installed": iptables_installed}}

    def _probe_public_ip(self) -> dict | None:
        """探测本机出口公网 IP + 地区（中文）。双服务 fallback：ip-api.com → ipinfo.io。"""
        UA = {"User-Agent": "Mozilla/5.0 (Stella)"}  # ip-api 对默认 python UA 反爬
        # 主：ip-api.com（lang=zh-CN 直接返回中文）
        try:
            if httpx:
                d = httpx.get("http://ip-api.com/json/?lang=zh-CN&fields=status,country,regionName,city,query", timeout=5, headers=UA).json()
            else:
                import urllib.request
                req = urllib.request.Request("http://ip-api.com/json/?lang=zh-CN&fields=status,country,regionName,city,query", headers=UA)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    d = json.loads(resp.read())
            if d.get("status") == "success" and d.get("query"):
                return {"public_ip": d["query"], "ip_version": "IPv4",
                        "region": d.get("city") or d.get("country") or ""}
        except Exception:
            pass
        # 备：ipinfo.io（英文 region/country）
        try:
            if httpx:
                d = httpx.get("https://ipinfo.io/json", timeout=5, headers=UA).json()
            else:
                import urllib.request
                req = urllib.request.Request("https://ipinfo.io/json", headers=UA)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    d = json.loads(resp.read())
            if d.get("ip"):
                return {"public_ip": d["ip"], "ip_version": "IPv4",
                        "region": d.get("city") or d.get("country") or ""}
        except Exception:
            pass
        return None

    # ── HTTP 基础 ──
    def _get(self, path: str, **params):
        if httpx:
            r = httpx.get(self.url + path, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        import urllib.request
        import urllib.parse
        q = urllib.parse.urlencode(params)
        with urllib.request.urlopen(self.url + path + ("?" + q if q else ""), timeout=10) as resp:
            return json.loads(resp.read())

    def _post(self, path: str, json_body=None, **params):
        if httpx:
            r = httpx.post(self.url + path, json=json_body, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        import urllib.request
        import urllib.parse
        q = urllib.parse.urlencode(params)
        data = json.dumps(json_body).encode() if json_body is not None else b""
        req = urllib.request.Request(
            self.url + path + ("?" + q if q else ""),
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    # ── 采集 ──
    def detect_default_iface(self) -> str | None:
        """默认出口网卡 = 默认路由指向的网卡。Linux 读 /proc/net/route。"""
        if platform.system() == "Linux":
            try:
                with open("/proc/net/route") as f:
                    best = None
                    for line in f.read().splitlines()[1:]:
                        parts = line.split()
                        if len(parts) < 11:
                            continue
                        iface, dest, _, flags, _, _, _, metric = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6], parts[7]
                        if dest == "00000000" and flags == "0003":  # 默认路由 + up
                            m = int(metric)
                            if best is None or m < best[1]:
                                best = (iface, m)
                    return best[0] if best else None
            except OSError:
                return None
        return None

    def _is_physical_iface(self, name: str) -> bool:
        """物理网卡 = /sys/class/net/{name}/device 存在（有 PCI 设备）。虚拟口（veth/br/docker/tun 等）无 device。"""
        try:
            return os.path.isdir(f"/sys/class/net/{name}/device")
        except OSError:
            return False

    def _is_docker_iface(self, name: str) -> bool:
        """docker/容器虚拟网卡：docker0、veth*、br-*（docker bridge）、cni*。默认前端隐藏。"""
        if name == "docker0":
            return True
        return name.startswith(("veth", "br-", "cni", "docker", "virbr"))

    def _iface_ip(self, name: str) -> str | None:
        """网卡的 IPv4 地址（有则返回，无则 None）。"""
        try:
            if psutil:
                for addr in psutil.net_if_addrs().get(name, []):
                    if addr.family == socket.AF_INET:
                        return addr.address
        except Exception:
            pass
        return None

    def list_interfaces(self) -> dict:
        """枚举所有网卡 + 默认出口标记 + 物理/虚拟 + IP。虚拟口也报（中心决定是否监控）。"""
        default = self.detect_default_iface()
        ifaces = {}
        if psutil:
            for name, stats in psutil.net_if_stats().items():
                ifaces[name] = {
                    "is_default": name == default,
                    "up": bool(stats.isup),
                    "is_physical": self._is_physical_iface(name),
                    "docker": self._is_docker_iface(name),
                    "ip": self._iface_ip(name),
                }
        else:
            # 无 psutil：Linux 读 /proc/net/dev 兜底
            try:
                with open("/proc/net/dev") as f:
                    for line in f.read().splitlines()[2:]:
                        name = line.split(":")[0].strip()
                        ifaces[name] = {
                            "is_default": name == default,
                            "up": True,
                            "is_physical": self._is_physical_iface(name),
                            "docker": self._is_docker_iface(name),
                            "ip": self._iface_ip(name),
                        }
            except OSError:
                pass
        return ifaces

    def read_net_bytes(self) -> dict:
        """读各网卡累计字节 {iface: (rx, tx)}。"""
        result = {}
        if psutil:
            for name, io in psutil.net_io_counters(pernic=True).items():
                result[name] = (io.bytes_recv, io.bytes_sent)
        else:
            try:
                with open("/proc/net/dev") as f:
                    for line in f.read().splitlines()[2:]:
                        name, rest = line.split(":")
                        cols = rest.split()
                        result[name.strip()] = (int(cols[0]), int(cols[8]))
            except OSError:
                pass
        return result

    def collect_metrics(self) -> list:
        """采集流量增量。返回 [{iface, ts, rx_delta, tx_delta}]。"""
        now_net = self.read_net_bytes()
        now = datetime.now(timezone.utc)
        points = []
        for iface, (rx, tx) in now_net.items():
            # 只报监控范围内的网卡
            if self.monitored_ifaces is not None and iface not in self.monitored_ifaces:
                continue
            if self.last_net is None:
                self.last_net = now_net
                return []
            prev = self.last_net.get(iface)
            if prev is None:
                continue
            rx_delta = rx - prev[0]
            tx_delta = tx - prev[1]
            if rx_delta < 0 or tx_delta < 0:
                continue  # 计数器重置（网卡重启），跳过
            points.append({
                "iface": iface,
                "ts": now.isoformat(),
                "rx_delta": rx_delta,
                "tx_delta": tx_delta,
            })
        self.last_net = now_net
        return points

    def collect_sys(self) -> dict:
        """系统指标。"""
        now = datetime.now(timezone.utc).isoformat()
        cpu = mem = disk = None
        if psutil:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent
        return {"ts": now, "cpu_pct": cpu, "mem_pct": mem, "disk_pct": disk}

    # os_info 缓存：os_name/kernel/cpu_model/cpu_cores 基本不变，只读一次；负载/开机时间每次现算
    _os_static_cache: dict | None = None

    def _os_info(self) -> dict:
        """采集 OS 信息：发行版名/内核/CPU 型号/核数/负载/开机时间（前端基本信息面板用）。"""
        if self._os_static_cache is None:
            static: dict = {}
            if platform.system() == "Linux":
                # PRETTY_NAME：/etc/os-release 里的发行版友好名（如 "Arch Linux" / "Ubuntu 22.04 LTS"）
                try:
                    with open("/etc/os-release", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("PRETTY_NAME="):
                                static["os_name"] = line.split("=", 1)[1].strip().strip('"')
                                break
                except OSError:
                    pass
                # CPU 型号：/proc/cpuinfo 第一颗的 model name
                try:
                    with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if line.lower().startswith("model name"):
                                static["cpu_model"] = line.split(":", 1)[1].strip()
                                break
                except OSError:
                    pass
            else:
                # Windows：platform.platform() 给 "Windows-11-10.0.22631-SP0" 这类串
                static["os_name"] = platform.platform()
                static["cpu_model"] = platform.processor() or None
            static.setdefault("os_name", None)
            static.setdefault("cpu_model", None)
            static["kernel"] = platform.release() or None
            static["arch"] = platform.machine() or None
            static["cpu_cores"] = (psutil.cpu_count(logical=True) if psutil else os.cpu_count()) or None
            self._os_static_cache = static
        info = dict(self._os_static_cache)
        # 动态：负载（仅 Linux 有 getloadavg）+ 开机时间（前端算 uptime）
        try:
            la = os.getloadavg()
            info["load1"], info["load5"], info["load15"] = round(la[0], 2), round(la[1], 2), round(la[2], 2)
        except (OSError, AttributeError):
            info["load1"] = info["load5"] = info["load15"] = None
        info["boot_time"] = psutil.boot_time() if psutil else None
        return info

    def _physical_disks(self) -> list:
        """用 lsblk 列整块物理盘：容量=整盘 size，已用=盘上各文件系统分区已用之和。

        无 lsblk（如 Windows）时返回空，物理盘不显示。
        """
        out = []
        if not psutil:
            return out
        try:
            r = subprocess.run(
                ["lsblk", "-b", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT"],
                capture_output=True, text=True, timeout=5, check=True,
            )
            data = json.loads(r.stdout)
        except Exception:
            return out
        for disk in data.get("blockdevices", []):
            if disk.get("type") != "disk":
                continue
            total = int(disk.get("size") or 0)
            if total <= 0:
                continue
            used = 0

            def walk(node):
                nonlocal used
                mp = node.get("mountpoint")
                if mp and not mp.startswith("["):  # 排除 [SWAP] 等伪挂载
                    try:
                        used += psutil.disk_usage(mp).used
                    except OSError:
                        pass
                for child in node.get("children", []):
                    walk(child)

            walk(disk)
            name = "/dev/" + disk.get("name", "")
            out.append({
                "device": name, "mount": name, "fstype": "",
                "total": total, "used": used,
                "percent": round(used / total * 100, 1), "kind": "physical",
            })
        return out

    def list_storage(self) -> list:
        """存储视图：物理整块盘（lsblk）+ 网络挂载/虚拟卷（挂载点视角）。"""
        out = []
        if not psutil:
            return out
        import re
        # 1. 物理整块盘
        out.extend(self._physical_disks())
        # 2. 网络挂载（NFS/CIFS）+ 虚拟卷（LVM/md），挂载点视角
        NOISE_FS = {"tmpfs", "proc", "sysfs", "devtmpfs", "devpts", "securityfs",
                    "cgroup", "cgroup2", "pstore", "bpf", "autofs", "hugetlbfs",
                    "mqueue", "tracefs", "configfs", "debugfs", "fusectl",
                    "binfmt_misc", "nsfs", "overlay", "ramfs"}
        for p in psutil.disk_partitions(all=True):
            dev = p.device or ""
            fs = p.fstype or ""
            # 物理分区已归并到整块盘，跳过
            if re.match(r"^/dev/(sd|nvme|vd|hd|mmcblk|mmc)", dev):
                continue
            # 网络挂载 NFS/CIFS
            if ":/" in dev or dev.startswith("//"):
                kind = "network"
            elif dev.startswith("/dev/mapper/") or dev.startswith("/dev/md"):
                kind = "virtual"
            else:
                continue  # 其余（bind mount 等）跳过
            if fs in NOISE_FS:
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
            except (PermissionError, OSError):
                continue
            out.append({
                "device": dev, "mount": p.mountpoint, "fstype": fs,
                "total": int(u.total), "used": int(u.used),
                "percent": round(float(u.percent), 1), "kind": kind,
            })
        return out

    # ── 上报（含补传）──
    def report(self, metrics: list, sys_metrics: list):
        """上报流量 + 系统指标。失败时压入队列，成功时先补传队列再发当前。"""
        # 当前数据也进队列（发送成功才出队，保证不丢）；带组件检测状态（which 很便宜）
        self.queue.append({
            "metrics": metrics, "sys_metrics": sys_metrics,
            "components": self._check_components(),
            "os_info": self._os_info(),
        })

        # 尝试把队列里的所有数据按顺序补传
        while self.queue:
            batch = self.queue[0]
            try:
                resp = self._post("/agent/report", json_body=batch, token=self.token)
                self.queue.popleft()  # 发送成功才出队
                # 心跳响应带版本号：变了就拉配置 diff
                ver = resp.get("monitors_version")
                if ver is not None and ver != self.monitors_version:
                    self.refresh_config()
            except Exception:
                break  # 失败：留着队列，下次再补

    # ── 任务执行 ──
    def poll_and_execute(self):
        """轮询待办任务，执行并回传结果。"""
        try:
            tasks = self._get("/agent/tasks", token=self.token)
        except Exception:
            return

        # 卸载指令：优先处理（执行后不再跑其他任务）
        if tasks.get("uninstall"):
            self._run_uninstall()
            return

        for t in tasks.get("iperf_tasks", []):
            self._run_iperf(t)
        for t in tasks.get("mtr_tasks", []):
            self._run_mtr(t)
        for c in tasks.get("commands", []):
            self._run_command(c)
        for c in tasks.get("component_installs", []):
            self._run_component_install(c)
        for t in tasks.get("net_tasks", []):
            self._run_net_task(t)

    def _run_uninstall(self):
        """卸载自己：后台脚本停服务 + 删文件，先回传结果再自删。"""
        print("[uninstall] 收到卸载指令", file=sys.stderr, flush=True)
        try:
            # 后台脚本：sleep 留时间回传结果，再停服务删文件（停了服务 agent 就没法回传了）
            script = (
                "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; "
                "sleep 3; "
                "sudo systemctl disable stella-agent 2>/dev/null; "
                "sudo rm -f /etc/systemd/system/stella-agent.service; "
                "sudo systemctl daemon-reload; "
                "sudo rm -rf /opt/stella-agent; "
                "sudo systemctl stop stella-agent 2>/dev/null; "
            )
            subprocess.Popen(["nohup", "sh", "-c", script],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            self._post("/agent/uninstall/result", token=self.token, status="done")
            print("[uninstall] 已回传 done", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[uninstall] 回传失败: {e!r}", file=sys.stderr, flush=True)
            try:
                self._post("/agent/uninstall/result", token=self.token, status="failed", error=str(e))
            except Exception:
                pass

    # ── 监控项探测（agent 自探测）──
    def run_due_probes(self):
        """到点的监控项执行探测，结果上报中心。"""
        now = time.time()
        for mid, m in self.monitors.items():
            # MTR 定时通道（与探测节奏解耦）
            if now >= m.get("next_mtr", float("inf")):
                m["next_mtr"] = now + MTR_INTERVAL
                self._run_mtr_for_monitor(mid, m, "periodic")
            if now < m["next_run"]:
                continue
            m["next_run"] = now + m["interval"]  # 先排下次，避免探测慢堆积
            success, latency, loss = self.probe(m["type"], m["target"], m["timeout"])
            # 失败触发 MTR（防抖 10 分钟，挂了立刻有路径快照）
            if not success and now - m.get("last_fail_mtr", 0) > MTR_FAIL_DEBOUNCE:
                m["last_fail_mtr"] = now
                m["next_mtr"] = now + MTR_INTERVAL  # 失败这次顶掉定时那次
                self._run_mtr_for_monitor(mid, m, "failure")
            try:
                self._post("/agent/monitor-check", json_body={
                    "monitor_id": mid, "ts": datetime.now(timezone.utc).isoformat(),
                    "success": success, "latency_ms": latency, "loss_pct": loss,
                }, token=self.token)
            except Exception:
                pass

    def probe(self, mtype: str, target: str, timeout: int):
        """执行一次探测，返回 (success, latency_ms, loss_pct)。"""
        try:
            if mtype == "tcp":
                return self._probe_tcp(target, timeout)
            if mtype in ("http", "https"):
                return self._probe_http(target, timeout, mtype)
            if mtype == "ping":
                return self._probe_ping(target, timeout)
            if mtype == "udp":
                return self._probe_udp(target, timeout)
        except Exception:
            return (False, None, None)
        return (False, None, None)

    @staticmethod
    def _split_host_port(target: str):
        # 输入容错：全角冒号/空白（后端已规范化，这里是存量配置的兜底）
        target = target.replace("：", ":").strip()
        if ":" in target:
            host, port = target.rsplit(":", 1)
            return host, int(port)
        return target, 80

    def _probe_tcp(self, target, timeout):
        host, port = self._split_host_port(target)
        start = time.time()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                latency = (time.time() - start) * 1000
            return (True, latency, None)
        except OSError:
            return (False, (time.time() - start) * 1000, None)

    def _probe_http(self, target, timeout, scheme):
        target = target.replace("：", ":").strip()  # 全角冒号兜底
        url = target if target.startswith("http") else f"{scheme}://{target}"
        start = time.time()
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                latency = (time.time() - start) * 1000
                return (resp.status < 500, latency, None)
        except Exception:
            return (False, (time.time() - start) * 1000, None)

    def _probe_ping(self, target, timeout):
        """10 包探测：拿真实丢包率（-c 1 只有 0/100 两个值）+ 平均延迟。"""
        n = "-n" if platform.system() == "Windows" else "-c"
        try:
            r = subprocess.run(["ping", n, "10", "-W", str(timeout), target],
                               capture_output=True, text=True, timeout=timeout * 10 + 5)
            out = r.stdout + r.stderr
            loss_m = re.search(r"(\d+(?:\.\d+)?)%\s*packet\s*loss", out)
            rtt_m = re.search(r"(?:rtt|round-trip).*?=\s*[\d.]+/([\d.]+)/", out)
            loss = float(loss_m.group(1)) if loss_m else (0.0 if r.returncode == 0 else 100.0)
            latency = float(rtt_m.group(1)) if rtt_m else None
            return (r.returncode == 0 and loss < 100, latency, loss)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return (False, None, None)

    def _probe_udp(self, target, timeout):
        host, port = self._split_host_port(target)
        start = time.time()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(timeout)
            s.sendto(b"\x00", (host, port))
            try:
                s.recvfrom(1024)
            except socket.timeout:
                pass  # UDP 无响应不算 down（很多服务不回包），保守判 up
            finally:
                s.close()
            return (True, (time.time() - start) * 1000, None)
        except OSError:
            return (False, None, None)

    def _run_iperf(self, task):
        """执行 iperf3 打流。role=server 起 -s，role=client 起 -c（流式回传进度）。"""
        tid = task["id"]
        try:
            if task["mode"] == "speedtest":
                result = self._run_speedtest(task)
            elif task["role"] == "server":
                result = self._iperf_server(task)
            else:
                result = self._iperf_client(task)
                # 跨海 UDP/TCP 偶发「控制连接 reset」（端口协商失败）。server 端此时保持监听，
                # 这里自动重试（最多 2 次），每次回传重试事件给前端显示「xx原因，重试第x次」。
                attempt = 0
                while (isinstance(result, dict) and result.get("error")
                       and self._is_retryable_error(result["error"]) and attempt < 2):
                    attempt += 1
                    self._emit_retry_event(tid, attempt, result["error"])
                    time.sleep(2)  # 给 server 端时间从 reset 恢复回监听，再重试
                    result = self._iperf_client(task)
            if isinstance(result, dict) and result.get("error"):
                self._post(f"/agent/iperf-tasks/{tid}/result",
                           json_body=result, token=self.token, status="failed")
            else:
                self._post(f"/agent/iperf-tasks/{tid}/result",
                           json_body=result, token=self.token, status="done")
        except Exception as e:
            self._post(f"/agent/iperf-tasks/{tid}/result",
                       json_body={"error": str(e)}, token=self.token, status="failed")

    def _iperf_server(self, task) -> dict:
        """起 iperf3 server（-s），流式读 stdout，服务完一个 client 立即退出释放端口。

        - 不用 -1（单次）：client 的 TCP 探测连接会误触 -1 退出。
        - 不用 -J：结果前端不用，且 -J 写 stdout 没人读会塞满阻塞 server。
        - 逐行读 stdout（不累积，避免 PIPE 满）：-s 持续模式服务完一个 client 会输出
          汇总行（末尾 receiver/sender 标记），此时立即 terminate。否则遗留 server
          长时间占端口（数据量模式 + 低速率跑几十秒），后续任务 client 会连到旧 server，
          再被 _kill_stale_server 误杀 → "server has terminated"。
        - 兜底 Timer：client 一直不来时防止 server 永久挂起。"""
        port = task.get("port", 5201)
        # 先清掉可能遗留的旧 iperf3 -s（上一个任务已 done，安全清理，避免端口冲突）
        self._kill_stale_server(port)
        # 注意：-u 是 client-only 选项，server 端不能用；iperf3 -s 监听 TCP 控制端口，
        # client 用 -c -u 连上后 server 自动切换 UDP 数据，无需显式指定。
        # --forceflush：让 iperf3 每秒立即 flush interval 行（否则 stdout 块缓冲，
        # 测试结束才一次性吐出，server 端实时丢包率就变成"完成后才有"）。
        proc = subprocess.Popen(["iperf3", "-s", "-p", str(port), "--forceflush"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, bufsize=1)

        # 检测中止：前端点中止 → terminate server 释放端口
        threading.Thread(target=self._watch_cancel, args=(task["id"], proc), daemon=True).start()

        def _watch():
            try:
                if proc.stdout is None:
                    return
                accepted = False
                for line in proc.stdout:
                    # 探测连接（client 的 TCP connect 探测）只会输出 "unable to receive cookie"
                    # 并回到监听，不会输出 "Accepted connection"（那是真 client 的 iperf3 握手成功标志）。
                    # 所以两阶段检测：先等到真 client 连上，再等到它服务完回到监听，才退出释放端口。
                    if "Accepted connection" in line:
                        accepted = True
                    elif accepted and "Server listening" in line:
                        # 服务完一个 client 回到监听。不能盲目退出：跨海 UDP 偶发「控制连接 reset」
                        # （协商失败），client 端会重试，需要 server 还活着。所以查任务状态：
                        # client 已回传 done/failed/cancelled 才退出，否则继续监听等重试。
                        try:
                            st = self._get(f"/agent/iperf-tasks/{task['id']}/status", token=self.token)
                            if st.get("status") in ("done", "failed", "cancelled"):
                                self._terminate_proc(proc)
                                break
                            accepted = False  # 任务还在跑，继续监听等 client 重试
                        except Exception:
                            self._terminate_proc(proc)
                            break
                    # server 是接收端，每秒 interval 行带真实接收速率/丢包/抖动（正向时 client 是
                    # 发送端，sender 统计可能虚高），实时回传 role=server，前端用接收端数据画吞吐。
                    elif accepted:
                        self._emit_server_progress(task["id"], line)
            except Exception:
                pass

        threading.Thread(target=_watch, daemon=True).start()
        # 兜底：client 一直不来（领不到任务/探测失败）时，防止 server 永久占端口
        wait = (task["duration"] + 30) if not task.get("bytes") else 180
        threading.Timer(wait, self._terminate_proc, args=(proc,)).start()
        return {"role": "server"}

    def _emit_server_progress(self, task_id: int, line: str) -> None:
        """server 端（接收端）每秒回传接收速率 + 真实丢包/抖动（正向 UDP 实时丢包）。

        server 的 receiver interval 行：`1.22 MBytes  10.2 Mbits/sec  0.023 ms  0/39 (0%)`，
        带真实 jitter + lost/total（client 端是 sender 视角，看不到丢包）。"""
        # 过滤汇总行（末尾带 receiver/sender 标记，是 0-N 秒的汇总，不是每秒 interval）
        if "receiver" in line or "sender" in line:
            return
        # 过滤末尾不完整秒行：跨海延迟导致结束瞬间多吐一行（interval 不足 1 秒）。
        # 正向接收端是 "20.00-20.00"（起始==结束），反向发送端是 "10.00-10.05"（起始≠结束），
        # 所以不能只看起始==结束，统一用「interval 长度 < 1 秒」判断才对两种方向都生效。
        iv = re.search(r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*sec', line)
        if iv:
            _s = float(iv.group(1)); _e = float(iv.group(2))
            if _e - _s < 0.99:
                return
        m = re.search(r'(\d+(?:\.\d+)?)\s*(Gbits|Mbits|Kbits|bits)/sec', line)
        if not m:
            return
        bits = self._to_bits(float(m.group(1)), m.group(2))
        jm = re.search(r'(\d+(?:\.\d+)?)\s*ms', line)
        jitter = float(jm.group(1)) if jm else None
        lm = re.search(r'(\d+)/(\d+)\s*\(', line)
        lost = (int(lm.group(1)) / int(lm.group(2)) * 100.0) if lm else None
        ts = datetime.now(timezone.utc).isoformat()
        params = {"ts": ts, "bitrate": bits, "role": "server", "token": self.token}
        if lost is not None:
            params["lost_pct"] = lost
        if jitter is not None:
            params["jitter_ms"] = jitter
        try:
            self._post(f"/agent/iperf-tasks/{task_id}/progress", **params)
        except Exception:
            pass  # 进度回传失败不致命

    def _kill_stale_server(self, port: int) -> None:
        """kill 掉占用端口的遗留 iperf3 -s 进程，并等它真正退出（避免端口没释放就起新 server）。"""
        try:
            subprocess.run(["pkill", "-f", f"iperf3 -s -p {port}"], timeout=5)
            time.sleep(0.8)  # 等旧进程释放端口
        except Exception:
            pass

    def _terminate_proc(self, proc) -> None:
        """后台定时器回调：terminate 服务进程。"""
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _watch_cancel(self, task_id: int, proc) -> None:
        """后台线程：检测任务被中止（前端点中止 → status=cancelled），则 terminate iperf3 进程。

        iperf3 client/server 进程在跑时主线程阻塞在流式读 stdout，没法轮询任务状态，
        所以用独立线程每 2s 查一次，cancel 了就把 iperf3 杀掉，让主线程读 stdout 到 EOF 退出。"""
        while proc.poll() is None:
            try:
                t = self._get(f"/agent/iperf-tasks/{task_id}/status", token=self.token)
                if t.get("status") == "cancelled":
                    self._terminate_proc(proc)
                    break
            except Exception:
                pass
            time.sleep(2)

    def _iperf_client(self, task) -> dict:
        """iperf3 client（流式）：--interval 1 --forceflush 逐行读 stdout，每秒解析吞吐回传 progress，结束返回汇总。"""
        server = task.get("server_host")
        if not server:
            return {"error": "无 server host"}
        if shutil.which("iperf3") is None:
            return {"error": "本节点未安装 iperf3，请先在服务器列表代装"}
        port = task.get("port", 5201)
        # 先等 server 的 iperf3 端口就绪（server agent 可能还在轮询领取，没起 -s）
        # server 端 iperf3 -s 监听 TCP 控制端口（UDP 模式也一样，控制连接走 TCP），探测通用
        if not self._wait_server_ready(server, port=port):
            return {"error": f"等待 server {server}:{port} 就绪超时（server 未起 iperf3）"}
        cmd = ["iperf3", "-c", server, "--interval", "1", "--forceflush",
               "-p", str(port), "-P", str(task["parallel"])]
        # 数据量（-n）与时长（-t）二选一：bytes 有值按数据量，否则按时长
        if task.get("bytes"):
            cmd += ["-n", self._norm_units(task["bytes"])]
        else:
            cmd += ["-t", str(task["duration"])]
        if task.get("direction") == "reverse":
            cmd.append("-R")
        if task.get("udp"):
            cmd.append("-u")
            # UDP 必填目标带宽，空则默认 100M（否则 iperf3 默认 1Mbps，大数据量会卡十几分钟）
            cmd += ["-b", self._norm_units(task.get("bitrate")) or "100M"]
        elif task.get("bitrate"):
            # TCP 可选限速：填了 -b 就限速发送
            cmd += ["-b", self._norm_units(task["bitrate"])]
        if task.get("window"):
            cmd += ["-w", task["window"]]
        if task.get("length"):
            cmd += ["-l", task["length"]]
        if task.get("omit"):
            cmd += ["-O", str(task["omit"])]
        if task.get("zerocopy"):
            cmd.append("-Z")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, bufsize=1)
        except FileNotFoundError:
            return {"error": "iperf3 未安装"}

        # 检测中止：前端点中止 → terminate iperf3 client，读 stdout 到 EOF 退出
        threading.Thread(target=self._watch_cancel, args=(task["id"], proc), daemon=True).start()

        points: list = []
        if proc.stdout is None:
            return {"error": "无法读取 iperf3 输出"}

        # 流式解析：interval 行（每秒吞吐，多流按秒聚合）；sender/receiver 行记录最终汇总
        # UDP interval 行带 jitter(ms) + lost/total(x%)：正向时是 sender 视角（恒 0），
        # 反向(-R) 时 client 是接收端，interval 行是 receiver 视角（真实丢包/抖动）——所以反向才实时可见。
        cur_key: str | None = None
        cur_bits = 0.0
        cur_lost = 0      # 该秒丢包数（分子，多流累加）
        cur_total = 0     # 该秒总包数（分母，多流累加）
        cur_jitter_sum = 0.0
        cur_jitter_n = 0
        sender_line = ""    # 发送端汇总（TCP 重传在这）
        receiver_line = ""  # 接收端汇总（UDP 真实丢包/抖动/接收速率在这）

        def emit(bits: float, lost_pct=None, jitter_ms=None):
            ts = datetime.now(timezone.utc).isoformat()
            p = {"ts": ts, "bitrate": bits}
            params = {"ts": ts, "bitrate": bits, "token": self.token}
            if lost_pct is not None:
                p["lost_pct"] = lost_pct
                params["lost_pct"] = lost_pct
            if jitter_ms is not None:
                p["jitter_ms"] = jitter_ms
                params["jitter_ms"] = jitter_ms
            points.append(p)
            try:
                self._post(f"/agent/iperf-tasks/{task['id']}/progress", **params)
            except Exception:
                pass  # 进度回传失败不致命，继续采

        for line in proc.stdout:
            line = line.strip()
            if "sender" in line:
                sender_line = line  # 发送端汇总（最后一条是最终 SUM）
                continue
            if "receiver" in line:
                receiver_line = line  # 接收端汇总（UDP 真实数据在这里）
                continue
            m = re.search(r'(\d+(?:\.\d+)?)\s*(Gbits|Mbits|Kbits|bits)/sec', line)
            if not m:
                continue
            bits = self._to_bits(float(m.group(1)), m.group(2))
            iv = re.search(r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*sec', line)
            if not iv:
                continue
            key = iv.group(1)
            # 过滤末尾不完整秒行（interval 长度 < 1 秒）：正向 "20.00-20.00"、反向 "10.00-10.05"，
            # 都是结束瞬间的残留，回传会多一个点撑长 x 轴。用长度判断对正反向都生效。
            if float(iv.group(2)) - float(iv.group(1)) < 0.99:
                continue
            if cur_key is None:
                cur_key = key
            if key != cur_key:
                # 换到下一秒，回传上一秒聚合值
                lost = (cur_lost / cur_total * 100.0) if cur_total else None
                jit = (cur_jitter_sum / cur_jitter_n) if cur_jitter_n else None
                emit(cur_bits, lost, jit)
                cur_key = key
                cur_bits = 0.0
                cur_lost = 0; cur_total = 0; cur_jitter_sum = 0.0; cur_jitter_n = 0
            cur_bits += bits
            # UDP interval 行带 jitter + lost/total；TCP 行无此字段，正则匹配不到即跳过
            jm = re.search(r'(\d+(?:\.\d+)?)\s*ms', line)
            if jm:
                cur_jitter_sum += float(jm.group(1)); cur_jitter_n += 1
            lm = re.search(r'(\d+)/(\d+)\s*\(', line)
            if lm:
                cur_lost += int(lm.group(1)); cur_total += int(lm.group(2))
        if cur_key is not None:
            lost = (cur_lost / cur_total * 100.0) if cur_total else None
            jit = (cur_jitter_sum / cur_jitter_n) if cur_jitter_n else None
            emit(cur_bits, lost, jit)

        proc.wait()
        err = (proc.stderr.read() or "") if proc.stderr else ""
        if proc.returncode != 0:
            return {"error": err[-500:] or "iperf3 连接失败"}

        avg = sum(p["bitrate"] for p in points) / len(points) if points else 0.0
        peak = max((p["bitrate"] for p in points), default=0.0)
        if task.get("udp"):
            # UDP：真实丢包/抖动/接收速率在 receiver 汇总行
            recv = self._parse_receiver_line(receiver_line)
            total_bytes = recv.get("total_bytes")
            lost_pct = recv.get("lost_pct")
            jitter_ms = recv.get("jitter_ms")
            retransmits = None
            if task.get("direction") == "reverse":
                # 反向(-R)：client 是接收端，每秒 interval 行已是接收端真实速率，
                # avg/peak 直接用 points（真实每秒），不用 receiver 汇总覆盖（否则峰值被抹平成平均）。
                pass
            else:
                # 正向：client 是发送端，每秒 interval 行是发送速率（恒 -b 目标带宽，无意义），
                # 用 receiver 汇总的接收速率覆盖 avg/peak。
                recv_bitrate = recv.get("recv_bitrate")
                if recv_bitrate is not None:
                    avg = recv_bitrate
                    peak = recv_bitrate
        else:
            # TCP：sender 统计可能虚高（iperf3 3.21/3.16 兼容偶发 bug，报的发送字节数远超网卡实际），
            # 用 receiver 汇总行（接收端真实接收）代替 sender 行。
            recv = self._parse_receiver_line(receiver_line)
            total_bytes = recv.get("total_bytes")
            lost_pct = None
            jitter_ms = None
            # 重传在 sender 行（只有发送端知道重传了多少），仍从 sender 行取
            retransmits = self._parse_sender_line(sender_line).get("retransmits")
            if task.get("direction") == "reverse":
                # 反向(-R)：client 是接收端，points 已是接收端真实速率，avg/peak 用 points
                pass
            else:
                # 正向：client 是发送端，points 是发送速率（可能虚高），用 receiver 汇总的接收速率覆盖
                recv_bitrate = recv.get("recv_bitrate")
                if recv_bitrate is not None:
                    avg = recv_bitrate
                    peak = recv_bitrate
        # 发送端平均速率（基准虚线）：sender 汇总行的 bitrate（sender 永远是发送端）
        send_avg = self._parse_sender_line(sender_line).get("bitrate")
        result = {
            "role": "client",
            "avg_bitrate": avg,
            "peak_bitrate": peak,
            "send_avg_bitrate": send_avg,
            "total_bytes": total_bytes,
            "lost_pct": lost_pct,
            "jitter_ms": jitter_ms,
            "retransmits": retransmits,
            "duration": task["duration"],
            "parallel": task["parallel"],
            "direction": task.get("direction", "forward"),
            "udp": bool(task.get("udp")),
        }
        # 合理性校验：跨海家宽物理上不可能 > 1 Gbps，超过说明 iperf3 统计虚高
        # （3.16/3.21 兼容偶发 bug，两端计数器都虚高，物理网卡实际只有几十 Mbps）。
        # 标记 suspicious，前端提示数据异常，避免误把 20 Gbps 当真实带宽。
        # 但同机 loopback（Stella→Stella）走内存回环，几十 Gbps 是真实的，不套这个阈值。
        if not task.get("same_host") and (avg > 1e9 or peak > 1e9):
            result["suspicious"] = True
        return result

    @staticmethod
    def _to_bits(val: float, unit: str) -> float:
        return val * {"bits": 1.0, "Kbits": 1e3, "Mbits": 1e6, "Gbits": 1e9}.get(unit, 1.0)

    @staticmethod
    def _is_retryable_error(err: str) -> bool:
        """判断 iperf3 错误是否值得重试（跨海 UDP 偶发的控制连接 reset / 端口协商失败）。"""
        if not err:
            return False
        return any(k in err for k in (
            "unable to receive control message",
            "Connection reset",
            "Transport endpoint is not connected",
            "unable to read from stream socket",
            "unable to start listener",
        ))

    def _emit_retry_event(self, task_id: int, attempt: int, reason: str) -> None:
        """回传重试事件（前端显示「xx原因，重试第x次」）。

        存进 progress_json，用 retry=True 标记区分普通吞吐点，bitrate=0 占位。
        前端按 retry 标记单独提取显示，不画进吞吐曲线。"""
        try:
            self._post(f"/agent/iperf-tasks/{task_id}/progress",
                       ts=datetime.now(timezone.utc).isoformat(),
                       bitrate=0, role="client", retry=True,
                       attempt=attempt, reason=reason.strip()[-120:],
                       token=self.token)
        except Exception:
            pass  # 重试事件回传失败不致命

    @staticmethod
    def _norm_units(val, default_unit: str = "M") -> str | None:
        """规范化速率/数据量输入：'100' → '100M'，'1G' → '1000M'，'10M' → '10M'。

        统一成 iperf3 的 M 单位（-b 是 Mbps，-n 是 MB），让命令明确无歧义。
        前端让用户填纯数字（速率默认 Mbps，数据量默认 MB），这里自动拼后缀。"""
        if not val:
            return None
        val = str(val).strip().upper()
        m = re.match(r'^(\d+(?:\.\d+)?)\s*(K|M|G)?$', val)
        if not m:
            return val  # 非标准格式，原样交给 iperf3 报错
        num = float(m.group(1))
        unit = m.group(2) or default_unit
        factor = {"K": 0.001, "M": 1.0, "G": 1000.0}.get(unit, 1.0)
        result = num * factor
        if result == int(result):
            result = int(result)
        return f"{result}M"

    @staticmethod
    def _to_bytes(val: float, unit: str) -> float:
        return val * {"Bytes": 1.0, "KBytes": 1e3, "MBytes": 1e6, "GBytes": 1e9}.get(unit, 1.0)

    @staticmethod
    def _parse_sender_line(line: str) -> dict:
        """解析 iperf3 sender 汇总行：总数据量 + 丢包/抖动(UDP) + 重传(TCP)。"""
        if not line:
            return {}
        r: dict = {}
        m = re.search(r'(\d+(?:\.\d+)?)\s*(GBytes|MBytes|KBytes|Bytes)', line)
        if m:
            r["total_bytes"] = Agent._to_bytes(float(m.group(1)), m.group(2))
        b = re.search(r'(\d+(?:\.\d+)?)\s*(Gbits|Mbits|Kbits|bits)/sec', line)
        if b:
            r["bitrate"] = Agent._to_bits(float(b.group(1)), b.group(2))
        if "ms" in line:
            # UDP：抖动 + 丢包率
            j = re.search(r'(\d+(?:\.\d+)?)\s*ms', line)
            if j:
                r["jitter_ms"] = float(j.group(1))
            l = re.search(r'\((\d+(?:\.\d+)?)%\)', line)
            if l:
                r["lost_pct"] = float(l.group(1))
        else:
            # TCP：重传次数（sender 前一个字段）
            rt = re.search(r'(\d+)\s+sender', line)
            if rt:
                r["retransmits"] = int(rt.group(1))
        return r

    @staticmethod
    def _parse_receiver_line(line: str) -> dict:
        """解析 iperf3 receiver 汇总行：接收端真实数据（接收数据量/接收速率/丢包/抖动）。"""
        if not line:
            return {}
        r: dict = {}
        m = re.search(r'(\d+(?:\.\d+)?)\s*(GBytes|MBytes|KBytes|Bytes)', line)
        if m:
            r["total_bytes"] = Agent._to_bytes(float(m.group(1)), m.group(2))
        b = re.search(r'(\d+(?:\.\d+)?)\s*(Gbits|Mbits|Kbits|bits)/sec', line)
        if b:
            r["recv_bitrate"] = Agent._to_bits(float(b.group(1)), b.group(2))
        if "ms" in line:
            j = re.search(r'(\d+(?:\.\d+)?)\s*ms', line)
            if j:
                r["jitter_ms"] = float(j.group(1))
            l = re.search(r'\((\d+(?:\.\d+)?)%\)', line)
            if l:
                r["lost_pct"] = float(l.group(1))
        return r

    def _wait_server_ready(self, server: str, port: int = 5201, timeout: float = 30.0) -> bool:
        """等 server 的 iperf3 端口就绪（TCP connect），最多 timeout 秒。server agent 可能还没起 -s。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with socket.create_connection((server, port), timeout=2):
                    return True
            except OSError:
                time.sleep(1)
        return False

    def _emit_stage_note(self, task_id: int, note: str) -> None:
        """回传阶段提示点（speedtest 无秒级数据，用 note 点让前端显示进行到哪一步）。"""
        try:
            self._post(f"/agent/iperf-tasks/{task_id}/progress", token=self.token,
                       ts=datetime.now(timezone.utc).isoformat(), bitrate=0,
                       role="stage", note=note)
        except Exception:
            pass

    def _proxy_reachable(self, proxy_url: str) -> bool:
        """探测本机 socks5 代理端口是否可达（127.0.0.1:1080 之类）。"""
        try:
            host_port = proxy_url.split("://", 1)[1]
            host, _, port = host_port.rpartition(":")
            with socket.create_connection((host, int(port)), timeout=2):
                return True
        except Exception:
            return False

    def _run_speedtest_once(self, exe: str, task, proxy: str | None) -> dict | None:
        """跑一轮 speedtest；返回结果 dict，或 {"error": ...}。proxy 非 None 时走代理。"""
        cmd = [exe, "--json"]
        # -s 只有 speedtest-go 支持；speedtest-cli 用 --server
        st_server = task.get("speedtest_server")
        if st_server:
            cmd += ["-s", str(st_server)] if "speedtest-go" in exe else ["--server", str(st_server)]
        env = None
        if proxy:
            if "speedtest-go" in exe:
                cmd += ["--proxy", proxy]
            else:
                # speedtest-cli 没有 --proxy，用标准环境变量
                env = dict(os.environ, HTTPS_PROXY=proxy, HTTP_PROXY=proxy)
        # 完整测速含 ping + 下载 + 上传 + 丢包分析，可能 ~60s，留足超时
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        # 阶段心跳：子进程跑期间每 15s 报一次「测速中」，前端不再黑屏干等
        waited = 0
        while proc.poll() is None:
            time.sleep(5)
            waited += 5
            if waited % 15 == 0:
                self._emit_stage_note(task["id"], f"测速中（ping → 下载 → 上传）… 已进行 {waited}s")
            if waited >= 90:
                proc.kill()
                raise subprocess.TimeoutExpired(cmd, 90)
        out, err_out = proc.communicate()
        if proc.returncode == 0:
            try:
                return json.loads(out)
            except json.JSONDecodeError:
                return {"raw": out[-2000:]}
        # 非零退出：带上 stderr 真实原因（如网络不可达），别再误报「未安装」
        return {"error": f"speedtest 失败：{(err_out or out).strip()[-300:] or f'exit {proc.returncode}'}"}

    def _run_speedtest(self, task) -> dict:
        """公共 speedtest（用 speedtest-go 或 speedtest-cli，都没有则报错）。
        task.speedtest_server 指定测速服务器 ID（speedtest-go 的 -s 参数），None=自动。
        直连失败且本机有 xray 代理（127.0.0.1:1080 可达）时自动走代理重试——
        PBR 让 agent 直连物理网卡，家宽直连 Cloudflare(speedtest.net) 会被墙。"""
        exes = ["speedtest-go", "speedtest", "speedtest-cli"]
        bin_st = os.path.join(self._agent_bin(), "speedtest-go")
        if os.path.exists(bin_st):
            exes.insert(0, bin_st)  # 优先 agent bin 里代装的
        st_server = task.get("speedtest_server")
        self._emit_stage_note(task["id"], "选择测速服务器…" if not st_server else f"连接指定服务器 #{st_server}…")
        last_err = "未安装 speedtest-go / speedtest-cli"
        proxy = "socks5://127.0.0.1:1080"
        use_proxy = False
        for exe in exes:
            for attempt in range(2):  # 0=直连, 1=代理重试（仅代理可达时）
                if attempt == 1:
                    if not self._proxy_reachable(proxy):
                        break
                    use_proxy = True
                    self._emit_stage_note(task["id"], "直连失败，切换代理通道重试…")
                try:
                    r = self._run_speedtest_once(exe, task, proxy if use_proxy else None)
                    if r is not None and "error" not in r:
                        if use_proxy:
                            r["via_proxy"] = True  # 标记走的代理，结果页可区分
                        return r
                    last_err = (r or {}).get("error", last_err)
                    # 直连失败才有下一轮（代理重试）；代理也失败就换下一个 exe
                    if use_proxy:
                        break
                except FileNotFoundError:
                    break
                except subprocess.TimeoutExpired:
                    last_err = "speedtest 超时（90s）"
                    continue
        return {"error": last_err}

    def _run_component_install(self, task):
        """代装组件：iperf3 用 sudo 包管理器；speedtest 下载 speedtest-go 单文件。"""
        tid = task["id"]
        comp = task["component"]
        try:
            if comp == "iperf3":
                err = self._install_iperf3()
            elif comp == "speedtest":
                err = self._install_speedtest_go()
            elif comp in ("ufw", "docker", "mtr"):
                err = self._install_pkg(comp)
            else:
                err = f"未知组件 {comp}"
            if err:
                self._post(f"/agent/component-installs/{tid}/result",
                           token=self.token, status="failed", error=err)
            else:
                self._post(f"/agent/component-installs/{tid}/result",
                           token=self.token, status="done")
        except Exception as e:
            self._post(f"/agent/component-installs/{tid}/result",
                       token=self.token, status="failed", error=str(e))

    def _install_iperf3(self) -> str | None:
        """用系统包管理器装 iperf3（需要 install.sh 给的 sudo 白名单）。返回错误信息或 None=成功。"""
        pkgs = [("apt-get", ["sudo", "-n", "apt-get", "install", "-y", "iperf3"]),
                ("dnf", ["sudo", "-n", "dnf", "install", "-y", "iperf3"]),
                ("yum", ["sudo", "-n", "yum", "install", "-y", "iperf3"]),
                ("apk", ["sudo", "-n", "apk", "add", "iperf3"]),
                ("pacman", ["sudo", "-n", "pacman", "-S", "--noconfirm", "iperf3"])]
        for mgr, cmd in pkgs:
            if shutil.which(mgr):
                try:
                    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    if out.returncode == 0 and shutil.which("iperf3"):
                        return None
                    return (out.stderr or out.stdout)[-500:] or "iperf3 安装失败"
                except Exception as e:
                    return str(e)
        return "未识别包管理器，无法代装 iperf3（请手动安装）"

    def _install_pkg(self, pkg: str) -> str | None:
        """通用包代装（ufw / docker / mtr）：sudo 白名单按「包管理器+包名」精确匹配，装不上报真实原因。"""
        # docker 在 Debian/Ubuntu 仓库里叫 docker.io；mtr 在 Debian/Ubuntu 叫 mtr-tiny
        names = {"docker": {"apt-get": "docker.io"}, "ufw": {}, "mtr": {"apt-get": "mtr-tiny"}}
        binname = pkg  # 装完验证用的二进制名
        pkgs = [("apt-get", ["sudo", "-n", "apt-get", "install", "-y"]),
                ("dnf", ["sudo", "-n", "dnf", "install", "-y"]),
                ("yum", ["sudo", "-n", "yum", "install", "-y"]),
                ("apk", ["sudo", "-n", "apk", "add"]),
                ("pacman", ["sudo", "-n", "pacman", "-S", "--noconfirm"])]
        last = None
        for mgr, base in pkgs:
            if not shutil.which(mgr):
                continue
            pkgname = names.get(pkg, {}).get(mgr, pkg)
            try:
                out = subprocess.run(base + [pkgname], capture_output=True, text=True, timeout=600)
                if out.returncode == 0 and shutil.which(binname):
                    if pkg == "docker":
                        # 装完顺手拉起守护进程（enable 失败不致命）
                        subprocess.run(["sudo", "-n", "systemctl", "enable", "--now", "docker"],
                                       capture_output=True, text=True, timeout=30)
                    return None
                last = (out.stderr or out.stdout)[-500:] or f"{pkg} 安装失败"
            except Exception as e:
                last = str(e)
        return last or f"未识别包管理器，无法代装 {pkg}（请手动安装）"

    def _install_speedtest_go(self) -> str | None:
        """下载 speedtest-go 到 agent 目录 bin/。先 GitHub 直链，被限流则从后端兜底。"""
        try:
            if platform.system() != "Linux":
                return "Windows 暂不支持代装 speedtest-go"
            arch = platform.machine() or "x86_64"
            arch_map = {"x86_64": "x86_64", "aarch64": "arm64", "armv7l": "armv7",
                        "armv6l": "armv6", "i686": "i386"}
            go_arch = arch_map.get(arch, "x86_64")
            dest_dir = self._agent_bin()
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, "speedtest-go")

            # 1) GitHub 直链（资产名带版本号 speedtest-go_<tag>_Linux_<arch>.tar.gz）
            tag = "v1.7.11"  # 兜底
            try:
                r = subprocess.run(
                    ["curl", "-sSL", "-o", "/dev/null", "-w", "%{url_effective}",
                     "https://github.com/showwin/speedtest-go/releases/latest"],
                    capture_output=True, text=True, timeout=30)
                tail = (r.stdout or "").strip().rstrip("/").split("/")[-1]
                if tail.startswith("v"):
                    tag = tail
            except Exception:
                pass
            url = (f"https://github.com/showwin/speedtest-go/releases/download/{tag}/"
                   f"speedtest-go_{tag}_Linux_{go_arch}.tar.gz")
            tarball = os.path.join(dest_dir, "speedtest-go.tar.gz")
            try:
                # 带浏览器 UA：GitHub release 下载对 curl 默认 UA 会返回 404
                subprocess.run(["curl", "-sSL", "-A", "Mozilla/5.0", url, "-o", tarball],
                               check=True, timeout=120)
                # 有效 tar.gz 约 3MB；404 错误页只有几字节，据此判断下载是否真成功
                if os.path.getsize(tarball) > 100_000:
                    subprocess.run(["tar", "-xzf", tarball, "-C", dest_dir], check=True, timeout=60)
                    os.chmod(dest, 0o755)
            except Exception:
                pass
            try:
                os.remove(tarball)
            except OSError:
                pass

            # 2) 兜底：GitHub 直链被限流（下载到 404 页）时，从后端下载预置二进制
            if not (os.path.exists(dest) and os.path.getsize(dest) > 100_000):
                try:
                    subprocess.run(
                        ["curl", "-sSL", "-o", dest,
                         f"{self.url}/agent/component/speedtest-go?token={self.token}"],
                        check=True, timeout=120)
                    os.chmod(dest, 0o755)
                except Exception:
                    pass

            if os.path.exists(dest) and os.path.getsize(dest) > 100_000:
                return None
            return "speedtest-go 下载失败（GitHub 直链被限流且后端无预置二进制），稍后重试"
        except Exception as e:
            return str(e)

    @staticmethod
    def _mtr_cmd(target: str, proto: str, params: dict | None = None) -> list[str]:
        """组 mtr 命令（--raw 流式输出，逐包解析做实时显示）。
        target 可带端口（host:port，tcp/udp 用）；icmp 忽略端口。
        params: count(-c 包数)/interval(-i 秒)/max_hops(-m)/psize(-s 字节)，后端已校验范围。"""
        p = params or {}
        host, port = target, None
        if ":" in target:
            h, _, ps = target.rpartition(":")
            if h and ps.isdigit():
                host, port = h, int(ps)
        cmd = ["mtr", "--raw", "-c", str(int(p.get("count", 10)))]
        if p.get("interval"):
            # mtr 限制：非 root 用户 -i 最小 1.0 秒，钳住防失败
            cmd += ["-i", str(max(float(p["interval"]), 1.0))]
        if p.get("max_hops"):
            cmd += ["-m", str(int(p["max_hops"]))]
        if p.get("psize"):
            cmd += ["-s", str(int(p["psize"]))]
        if proto in ("udp", "tcp"):
            cmd += ["--" + proto, "-P", str(port or 80)]
        cmd.append(host)
        return cmd

    def _mtr_stream(self, target: str, proto: str, params: dict | None = None,
                    live_cb=None) -> dict:
        """跑 mtr --raw 并流式聚合逐跳统计（x=发包 h=主机 d=DNS名 p=回包，rtt 单位 µs）。

        返回 mtr --json 兼容结构（hub 多带 name/last/stdev，前端终端式表格直接用）。
        live_cb(hubs) 每 ~2s 回调一次最新快照（工具页实时逐跳表）。"""
        p = params or {}
        count = int(p.get("count", 10))
        interval = float(p.get("interval", 1.0))
        cmd = self._mtr_cmd(target, proto, params)
        # 解析目标 IP：raw 流里目的跳被应答后，mtr 会往「目的+1」再发一个幻影探针
        # （同 IP、只发一次），后处理要靠它把幻影跳剔掉
        target_host = cmd[-1]
        target_ips: set[str] = set()
        try:
            for fam, _, _, _, sa in socket.getaddrinfo(target_host, None):
                if fam in (socket.AF_INET, socket.AF_INET6):
                    target_ips.add(str(sa[0]))
        except OSError:
            pass
        hops: dict[int, dict] = {}

        def snapshot() -> list[dict]:
            hubs = []
            for idx in sorted(hops):
                h = hops[idx]
                rtts = h["rtts"]
                snt = h["sent"]
                recv = len(rtts)
                hubs.append({
                    "count": idx + 1,
                    "host": h.get("name") or h.get("host") or "???",
                    "loss%": round((snt - recv) / snt * 100, 1) if snt else 0.0,
                    "snt": snt,
                    "last": round(rtts[-1], 3) if rtts else None,
                    "avg": round(sum(rtts) / recv, 3) if rtts else None,
                    "best": round(min(rtts), 3) if rtts else None,
                    "wrst": round(max(rtts), 3) if rtts else None,
                    "stdev": round(statistics.pstdev(rtts), 3) if recv > 1 else (0.0 if rtts else None),
                })
            return hubs

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, bufsize=1)
        assert proc.stdout is not None
        deadline = time.time() + count * max(interval, 1.0) + 45
        last_emit = 0.0
        completed = False  # 正常跑完（raw 模式对目的跳有少打 x/p 行的怪癖，跑完才能按 count 校准 Snt）
        try:
            while True:
                if time.time() > deadline:
                    proc.kill()
                    raise subprocess.TimeoutExpired(cmd, int(deadline))
                # select 1s 轮询读行：readline 裸阻塞会让 deadline 失效
                r, _, _ = select.select([proc.stdout], [], [], 1.0)
                if not r:
                    if proc.poll() is not None:
                        completed = True  # 进程结束且管道已读空
                        break
                    continue
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        completed = True
                        break
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                kind = parts[0]
                try:
                    idx = int(parts[1])
                except ValueError:
                    continue
                h = hops.setdefault(idx, {"host": None, "name": None, "sent": 0, "rtts": []})
                if kind == "x":
                    h["sent"] += 1
                elif kind == "h" and len(parts) >= 3:
                    if not h["host"]:
                        h["host"] = parts[2]
                elif kind == "d" and len(parts) >= 3:
                    h["name"] = parts[2]
                elif kind == "p" and len(parts) >= 3:
                    try:
                        h["rtts"].append(int(parts[2]) / 1000.0)  # µs → ms
                    except ValueError:
                        pass
                now = time.time()
                if live_cb and now - last_emit >= 2.0:
                    last_emit = now
                    live_cb(snapshot())
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
        if completed:
            # 剔幻影跳：raw 流里目的跳被应答后，mtr 会往「目的+1」多发一个探针
            # （同 IP、只发一次）。找到第一个主机==目标 IP（或解析名==目标）的跳，
            # 它后面的都是幻影，直接丢掉（幻影的回包不并入目的跳，否则 recv>snt）。
            if target_ips and hops:
                dest_idx = None
                for idx in sorted(hops):
                    h = hops[idx]
                    if (h.get("host") in target_ips) or (h.get("name") in target_ips) \
                            or (h.get("name") == target_host) or (h.get("host") == target_host):
                        dest_idx = idx
                        break
                if dest_idx is not None:
                    for idx in [i for i in hops if i > dest_idx]:
                        del hops[idx]
            # 正常跑完：每一跳的发包数都等于 count（对照 mtr -r 的 Snt 列语义）。
            # raw 流对目的跳只打 1 行 x/p（mtr 自身怪癖），不校准会把末跳 Snt 显示成 1。
            for h in hops.values():
                h["sent"] = count
        err = ""
        try:
            err = proc.stderr.read() if proc.stderr else ""
        except Exception:
            pass
        hubs = snapshot()
        if proc.returncode not in (0, None) and not hubs:
            raise RuntimeError((err or f"mtr exit {proc.returncode}")[-500:])
        result = {"report": {"mtr": {"dst": target, "tos": 0,
                                     "psize": int(p.get("psize", 64)),
                                     "bitpattern": 0, "tests": count},
                             "hubs": hubs}}
        return result

    def _run_mtr(self, task):
        """执行 mtr（--raw 流式：边跑边回传实时快照，结束回传完整结果）。"""
        tid = task["id"]

        def live(hubs):
            try:
                self._post(f"/agent/mtr-tasks/{tid}/live",
                           json_body={"hops": hubs}, token=self.token)
            except Exception:
                pass  # 实时快照丢了不致命，下一秒还会再发

        try:
            result = self._mtr_stream(task["target"], task.get("protocol", "icmp"),
                                      task.get("params"), live_cb=live)
            self._post(f"/agent/mtr-tasks/{tid}/result",
                       json_body=result, token=self.token, status="done")
        except (subprocess.TimeoutExpired, FileNotFoundError, RuntimeError) as e:
            self._post(f"/agent/mtr-tasks/{tid}/result",
                       json_body={"error": str(e)}, token=self.token, status="failed")

    def _run_mtr_for_monitor(self, mid: int, m: dict, trigger: str):
        """监控项的定时/失败触发 MTR：单独线程跑（10 包 ~15s，不阻塞探测循环），结果走 mtr-report。"""
        if shutil.which("mtr") is None:
            return  # 未装 mtr 就跳过（前端组件检测会提示可代装）
        target = f"{m['mtr_host']}:{m['mtr_port']}" if m.get("mtr_port") else m["mtr_host"]
        proto = m.get("mtr_proto", "icmp")

        def _job():
            try:
                result = self._mtr_stream(target, proto)
                self._post("/agent/mtr-report", json_body={
                    "monitor_id": mid, "trigger": trigger, "ok": True, "result_json": result},
                    token=self.token)
            except Exception as e:
                try:
                    self._post("/agent/mtr-report", json_body={
                        "monitor_id": mid, "trigger": trigger, "ok": False, "error": str(e)},
                        token=self.token)
                except Exception:
                    pass

        threading.Thread(target=_job, daemon=True).start()

    def _run_command(self, task):
        """执行命令，回传 stdout/stderr/exit_code。"""
        cid = task["id"]
        cmd = task["command"]
        try:
            out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            self._post(f"/agent/commands/{cid}/result",
                       token=self.token, status="done",
                       stdout=out.stdout[-5000:], stderr=out.stderr[-5000:],
                       exit_code=out.returncode)
        except subprocess.TimeoutExpired:
            self._post(f"/agent/commands/{cid}/result",
                       token=self.token, status="failed",
                       stderr="timeout", exit_code=-1)

    # ── 网络操作任务（改 IP 回退 / 防火墙修改）──
    def _run_net_task(self, task):
        """执行网络操作任务。kind=ip_change 走回退流程；kind=firewall_scan 结构化采集防火墙。"""
        tid = task["id"]
        try:
            if task["kind"] == "ip_change":
                result = self._run_ip_change(task)
            elif task["kind"] == "firewall_scan":
                result = self._firewall_scan()
            elif task["kind"] == "docker_scan":
                result = self._docker_scan()
            elif task["kind"] == "docker_ctl":
                result = self._docker_ctl(task.get("payload") or {})
            else:
                result = {"error": f"未知任务类型 {task['kind']}"}
            if isinstance(result, dict) and result.get("error"):
                self._post(f"/agent/net-tasks/{tid}/result",
                           token=self.token, status="failed", json_body=result)
            else:
                self._post(f"/agent/net-tasks/{tid}/result",
                           token=self.token, status="done", json_body=result)
        except Exception as e:
            self._post(f"/agent/net-tasks/{tid}/result",
                       token=self.token, status="failed", json_body={"error": str(e)})

    # ── 防火墙结构化采集（一期：只读展示，不写规则）──
    def _firewall_scan(self) -> dict:
        """采集 ufw + iptables 结构化状态。ufw 用 status numbered/verbose，iptables 用 iptables-save 解析五表。"""
        return {"ufw": self._scan_ufw(), "iptables": self._scan_iptables()}

    @staticmethod
    def _sudo_run(cmd: list[str], timeout: int = 10) -> str | None:
        """sudo 只读命令：成功返回 stdout，失败返回 None（不抛异常，采集器各自降级）。"""
        try:
            r = subprocess.run(["sudo", "-n"] + cmd, capture_output=True, text=True, timeout=timeout)
            return r.stdout if r.returncode == 0 else None
        except Exception:
            return None

    # ── Docker 面板：容器列表 + 启停重启 ──
    def _docker_scan(self) -> dict:
        """容器列表：docker ps -a --format json 逐行 JSON 解析。"""
        if not shutil.which("docker"):
            return {"installed": False}
        out = self._sudo_run(["docker", "ps", "-a", "--format", "{{json .}}"], timeout=20)
        if out is None:
            return {"installed": True, "error": "docker 命令需要 root（sudo 白名单未含 docker）"}
        containers = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                j = json.loads(line)
                containers.append({
                    "id": j.get("ID"), "name": j.get("Names"), "image": j.get("Image"),
                    "status": j.get("Status"), "state": j.get("State"),
                    "ports": j.get("Ports") or "", "created": j.get("CreatedAt") or j.get("RunningFor") or "",
                })
            except json.JSONDecodeError:
                continue
        return {"installed": True, "containers": containers}

    def _docker_ctl(self, payload: dict) -> dict:
        """容器启停重启。action 白名单 + 容器名校验（防注入）。"""
        action = payload.get("action")
        name = str(payload.get("container") or "")
        if action not in ("start", "stop", "restart"):
            return {"error": f"不支持的操作 {action}"}
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.\-]*", name):
            return {"error": "容器名不合法"}
        try:
            r = subprocess.run(["sudo", "-n", "docker", action, name],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                return {"ok": True, "action": action, "container": name}
            return {"error": (r.stderr or r.stdout).strip()[-300:]}
        except Exception as e:
            return {"error": str(e)}

    def _scan_ufw(self) -> dict:
        if not shutil.which("ufw"):
            return {"installed": False}
        verbose = self._sudo_run(["ufw", "status", "verbose"]) or ""
        numbered = self._sudo_run(["ufw", "status", "numbered"]) or ""
        active = "Status: active" in verbose
        # Default: deny (incoming), allow (outgoing), disabled (routed)
        m = re.search(r"^Default:\s*(.+)$", verbose, re.M)
        defaults = m.group(1).strip() if m else None
        m = re.search(r"^Logging:\s*(.+)$", verbose, re.M)
        logging = m.group(1).strip() if m else None
        # 规则行：[ 1] 22/tcp  ALLOW IN  Anywhere   /  [ 2] Anywhere  ALLOW OUT  22/tcp  (out)  / 尾部可能有 (v6)
        rules = []
        for line in numbered.splitlines():
            rm = re.match(r"^\[\s*(\d+)\]\s+(\S+(?:\s+\S+?)?)\s{2,}(ALLOW IN|ALLOW OUT|DENY IN|DENY OUT|LIMIT IN|LIMIT OUT|REJECT IN|REJECT OUT)\s{2,}(.+?)(\s+\(v6\))?\s*$", line)
            if rm:
                rules.append({
                    "num": int(rm.group(1)),
                    "to": rm.group(2).strip(),
                    "action": rm.group(3),
                    "from": rm.group(4).strip(),
                    "v6": bool(rm.group(5)),
                })
        return {"installed": True, "active": active, "defaults": defaults, "logging": logging,
                "rules": rules, "raw": (numbered or verbose)[-4000:]}

    def _scan_iptables(self) -> dict:
        if not shutil.which("iptables-save"):
            return {"installed": False}
        raw = self._sudo_run(["iptables-save"], timeout=15)
        if raw is None:
            return {"installed": True, "error": "iptables-save 需要 root（sudo 白名单未生效）"}
        tables: dict = {}
        cur: str | None = None
        for line in raw.splitlines():
            if line.startswith("*"):
                cur = line[1:].strip()
                tables[cur] = {"chains": [], "rules": []}
            elif line.startswith(":") and cur:
                # :INPUT ACCEPT [123:4567]  —— 链名 策略 [包:字节]；策略为 "-" 的是自定义链
                m = re.match(r"^:(\S+)\s+(\S+)\s+\[(\d+):(\d+)\]", line)
                if m:
                    tables[cur]["chains"].append({
                        "name": m.group(1), "policy": None if m.group(2) == "-" else m.group(2),
                        "packets": int(m.group(3)), "bytes": int(m.group(4)),
                    })
            elif line.startswith("-A") and cur:
                tables[cur]["rules"].append(self._parse_iptables_rule(line))
        return {"installed": True, "tables": tables, "raw": raw[-4000:]}

    @staticmethod
    def _parse_iptables_rule(line: str) -> dict:
        """把 -A 规则拆成列：链/目标/协议/端口/源/目的/入出接口。raw 保留完整原文。"""
        toks = line.split()
        d: dict = {"raw": line, "chain": toks[1] if len(toks) > 1 else None,
                   "target": None, "proto": None, "sport": None, "dport": None,
                   "source": None, "dest": None, "in_iface": None, "out_iface": None}
        i = 2
        while i < len(toks):
            t = toks[i]
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if t == "-j": d["target"] = nxt; i += 1
            elif t == "-p": d["proto"] = nxt; i += 1
            elif t == "-s": d["source"] = nxt; i += 1
            elif t == "-d": d["dest"] = nxt; i += 1
            elif t == "-i": d["in_iface"] = nxt; i += 1
            elif t == "-o": d["out_iface"] = nxt; i += 1
            elif t == "--dport": d["dport"] = nxt; i += 1
            elif t == "--sport": d["sport"] = nxt; i += 1
            i += 1
        return d

    @staticmethod
    def _ping(target: str, count: int = 3, timeout: int = 2) -> bool:
        try:
            r = subprocess.run(["ping", "-c", str(count), "-W", str(timeout), target],
                               capture_output=True, text=True, timeout=count * timeout + 5)
            return r.returncode == 0
        except Exception:
            return False

    def _detect_persist_backend(self) -> str | None:
        """检测 IP 持久化后端：netplan → NetworkManager → networkd（netplan 优先，其后端可能是 networkd）。"""
        try:
            import glob as _glob
            if shutil.which("netplan") and _glob.glob("/etc/netplan/*.yaml"):
                return "netplan"
            if shutil.which("nmcli"):
                r = subprocess.run(["nmcli", "-t", "-f", "DEVICE", "device"],
                                   capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    return "networkmanager"
            if _glob.glob("/etc/systemd/network/*.network"):
                return "networkd"
        except Exception:
            pass
        return None

    def _persist_ip(self, iface: str, new_ip: str, prefix: int, gateway: str | None) -> bool:
        """写持久化配置（尽力而为，失败返回 False，不阻塞回退流程）。"""
        backend = self._detect_persist_backend()
        cidr = f"{new_ip}/{prefix}"
        try:
            if backend == "netplan":
                import glob as _glob
                for yf in _glob.glob("/etc/netplan/*.yaml"):
                    with open(yf) as f:
                        content = f.read()
                    if iface in content:
                        subprocess.run(["cp", yf, yf + ".bak"], timeout=5)
                        r = subprocess.run(["sudo", "netplan", "set", f"ethernets.{iface}.addresses=[\"{cidr}\"]"],
                                           capture_output=True, timeout=20)
                        if r.returncode == 0:
                            if gateway:
                                subprocess.run(["sudo", "netplan", "set", f"ethernets.{iface}.routes=[{{\"to\":\"default\",\"via\":\"{gateway}\"}}]"],
                                               capture_output=True, timeout=20)
                            subprocess.run(["sudo", "netplan", "apply"], capture_output=True, timeout=40)
                            return True
            elif backend == "networkmanager":
                # 找到 iface 对应的连接名，改 ipv4.addresses
                r = subprocess.run(["nmcli", "-t", "-f", "DEVICE,CONNECTION", "device", "status"],
                                   capture_output=True, text=True, timeout=10)
                conn = None
                for line in r.stdout.splitlines():
                    if line.startswith(iface + ":"):
                        conn = line.split(":", 1)[1].strip()
                        break
                if conn:
                    r = subprocess.run(["sudo", "nmcli", "con", "mod", conn, "ipv4.addresses", cidr,
                                        "ipv4.method", "manual"],
                                       capture_output=True, timeout=20)
                    if gateway:
                        subprocess.run(["sudo", "nmcli", "con", "mod", conn, "ipv4.gateway", gateway],
                                       capture_output=True, timeout=20)
                    subprocess.run(["sudo", "nmcli", "con", "up", conn], capture_output=True, timeout=40)
                    return True
            elif backend == "networkd":
                import glob as _glob
                for nf in _glob.glob(f"/etc/systemd/network/*{iface}*.network"):
                    with open(nf) as f:
                        content = f.read()
                    subprocess.run(["cp", nf, nf + ".bak"], timeout=5)
                    # 简化：写一个新的 .network 覆盖（Address= 行替换）
                    lines = []
                    for line in content.splitlines():
                        if line.startswith("Address="):
                            lines.append(f"Address={cidr}")
                        elif line.startswith("Gateway=") and gateway:
                            lines.append(f"Gateway={gateway}")
                        else:
                            lines.append(line)
                    with open(nf, "w") as f:
                        f.write("\n".join(lines) + "\n")
                    subprocess.run(["networkctl", "reload"], capture_output=True, timeout=20)
                    return True
        except Exception:
            pass
        return False

    def _run_ip_change(self, task) -> dict:
        """改 IP + ping 回退（本地自包含：改 IP 后即使断网，agent 常驻进程也能回退，不依赖中心下发）。

        流程：备份旧 IP → 临时 ip addr 改 → 等 3s → ping 测试 → 通写持久化 / 不通本地回退。"""
        payload = task["payload"] or {}
        iface = payload.get("iface")
        new_ip = payload.get("new_ip")
        prefix = payload.get("prefix", 24)
        gateway = payload.get("gateway")
        ping_target = payload.get("ping_target")
        if not iface or not new_ip or not ping_target:
            return {"error": "参数缺失（iface/new_ip/ping_target）"}

        old_ip = self._iface_ip(iface)
        if not old_ip:
            return {"error": f"无法获取 {iface} 当前 IP"}
        if old_ip == new_ip:
            return {"error": f"新 IP 与当前 IP 相同（{new_ip}）"}

        def _addr(action: str, ip: str):
            subprocess.run(["sudo", "ip", "addr", action, f"{ip}/{prefix}", "dev", iface],
                           capture_output=True, timeout=10)

        # 1. 临时改 IP
        try:
            _addr("del", old_ip)
            _addr("add", new_ip)
        except Exception as e:
            # 改失败，恢复旧 IP
            try:
                _addr("add", old_ip)
            except Exception:
                pass
            return {"error": f"临时改 IP 失败: {e}", "rolled_back": True, "old_ip": old_ip}

        # 2. 改网关（可选）
        if gateway:
            subprocess.run(["sudo", "ip", "route", "del", "default"], capture_output=True, timeout=10)
            subprocess.run(["sudo", "ip", "route", "add", "default", "via", gateway], capture_output=True, timeout=10)

        # 3. 等网络生效
        time.sleep(3)

        # 4. ping 测试
        if self._ping(ping_target):
            # 通 → 写持久化
            persisted = self._persist_ip(iface, new_ip, prefix, gateway)
            return {"ok": True, "old_ip": old_ip, "new_ip": new_ip,
                    "persisted": persisted, "backend": self._detect_persist_backend()}
        else:
            # 不通 → 本地回退（不是中心下发，因可能断网）
            try:
                _addr("del", new_ip)
                _addr("add", old_ip)
            except Exception:
                pass
            if gateway:
                subprocess.run(["sudo", "ip", "route", "add", "default", "via", gateway], capture_output=True, timeout=10)
            return {"error": f"ping {ping_target} 不通，已回退旧 IP {old_ip}",
                    "rolled_back": True, "old_ip": old_ip, "new_ip": new_ip}

    # ── 拉配置 ──
    def refresh_config(self):
        """拉中心下发的配置：监控网卡 + 负责的监控项 + 版本号。"""
        try:
            cfg = self._get("/agent/config", token=self.token)
            self.monitored_ifaces = cfg.get("monitored_ifaces")
            self.monitors_version = cfg.get("monitors_version", 0)
            self._apply_monitors(cfg.get("monitors", []))
        except Exception:
            pass

    def _apply_monitors(self, monitors: list):
        """diff 监控项：新增/更新 → 起定时器，删除 → 移除。"""
        now = time.time()
        new_ids = set()
        for m in monitors:
            mid = m["id"]
            new_ids.add(mid)
            cur = self.monitors.get(mid)
            if cur is None:
                self.monitors[mid] = {
                    "type": m["type"], "target": m["target"],
                    "interval": m["interval"], "timeout": m["timeout"],
                    "mtr_host": m.get("mtr_host", m["target"]),
                    "mtr_proto": m.get("mtr_proto", "icmp"),
                    "mtr_port": m.get("mtr_port"),
                    "next_run": now,  # 立即探测一次
                    "next_mtr": now + 60,  # 首次 MTR 错开 1 分钟（避免和首批探测挤一起）
                }
            else:
                cur["type"] = m["type"]
                cur["target"] = m["target"]
                cur["interval"] = m["interval"]
                cur["timeout"] = m["timeout"]
                cur["mtr_host"] = m.get("mtr_host", m["target"])
                cur["mtr_proto"] = m.get("mtr_proto", "icmp")
                cur["mtr_port"] = m.get("mtr_port")
        for mid in list(self.monitors.keys()):
            if mid not in new_ids:
                del self.monitors[mid]

    # ── 版本自更新 ──
    def check_update(self):
        """对比中心最新版本，不同则下载新脚本覆盖自己并重启。"""
        try:
            info = self._get("/agent/version")
            latest = info.get("version", "")
            if not latest or latest == AGENT_VERSION:
                return
            print(f"[update] 检测到新版本 {latest}（当前 {AGENT_VERSION}），自更新中", file=sys.stderr, flush=True)
            self._download_and_restart()
        except Exception as e:
            print(f"[update] 版本检查失败：{e!r}", file=sys.stderr)

    def _download_and_restart(self):
        me = os.path.abspath(__file__)
        # 下载最新脚本
        try:
            if httpx:
                code = httpx.get(self.url + "/agent/script", timeout=30).text
            else:
                import urllib.request
                with urllib.request.urlopen(self.url + "/agent/script", timeout=30) as resp:
                    code = resp.read().decode("utf-8")
        except Exception as e:
            print(f"[update] 下载失败：{e!r}", file=sys.stderr)
            return
        # 原子替换：写临时文件 + os.replace，避免半截文件
        tmp = me + ".new"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(code)
            os.chmod(tmp, 0o755)
            os.replace(tmp, me)
        except OSError as e:
            print(f"[update] 写入失败：{e!r}", file=sys.stderr)
            return
        print("[update] 已替换脚本，重启中", file=sys.stderr, flush=True)
        # 重启：systemd 管理则后台 systemctl restart（会 SIGTERM 当前进程），
        # 否则（前台跑）exec 替换自己。
        try:
            subprocess.Popen(["systemctl", "restart", "stella-agent"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            time.sleep(5)  # 给 systemd 完成 stop+start；若仍活着说明非 systemd 管理
        except Exception:
            pass
        os.execv(sys.executable, [sys.executable, me] + sys.argv[1:])

    # ── 主循环 ──
    def run(self):
        print(f"[stella-agent {AGENT_VERSION}] 启动，中心 {self.url}", file=sys.stderr)
        # 首次上报网卡清单（含默认出口）+ 存储视图 + 拉配置
        try:
            self._post("/agent/report", json_body={
                "metrics": [], "sys_metrics": [],
                "interfaces": self.list_interfaces(),
                "agent_version": AGENT_VERSION,
                "storage": self.list_storage(),
                "components": self._check_components(),
                "os_info": self._os_info(),
                "public_ip_info": self._probe_public_ip(),
            }, token=self.token)
        except Exception as e:
            print(f"[warn] 首次上报失败：{e}", file=sys.stderr)
        self.refresh_config()

        last_sys = 0
        last_refresh = 0
        last_update = 0
        last_report = 0
        while True:
            try:
                now = time.time()

                # 流量：5s 采样上报（主循环 1s 一圈，流量上报仍保持 5s 粒度）
                if now - last_report >= REPORT_INTERVAL:
                    metrics = self.collect_metrics()
                    sys_metrics = []
                    if now - last_sys >= SYS_INTERVAL:
                        sys_metrics = [self.collect_sys()]
                        last_sys = now
                    if metrics or sys_metrics:
                        self.report(metrics, sys_metrics)
                    last_report = now

                # 配置：60s 拉一次
                if now - last_refresh >= 60:
                    self.refresh_config()
                    last_refresh = now

                # 版本自更新：每 5 分钟检查一次
                if now - last_update >= UPDATE_CHECK_INTERVAL:
                    self.check_update()
                    last_update = now

                # 监控项探测：到点的探测并上报
                self.run_due_probes()

                # 任务：1s 轮询（打流领取要快）
                self.poll_and_execute()

            except Exception as e:
                print(f"[error] 主循环异常：{e}", file=sys.stderr)

            time.sleep(POLL_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="Stella Agent")
    parser.add_argument("--url", default=os.environ.get("STELLA_URL", "http://127.0.0.1:12031"))
    parser.add_argument("--token", default=os.environ.get("STELLA_TOKEN", ""))
    args = parser.parse_args()

    if not args.token:
        print("错误：缺少 --token（或 STELLA_TOKEN 环境变量）", file=sys.stderr)
        sys.exit(1)

    Agent(args.url, args.token).run()


if __name__ == "__main__":
    main()
