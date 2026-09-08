#!/bin/bash
# Stella Agent 安装脚本（Linux / 飞牛OS）
# 用法：curl -sSL <此脚本URL> | sudo bash -s -- --url http://<stella> --token <token> [--pbr] [--deps | --no-deps]
set -eE
STAGE="初始化"
_AGENT_TMP=""
fail() { echo "错误：[$STAGE] $1" >&2; exit 1; }
# Never print BASH_COMMAND: the failing command may contain the token.
trap 'rc=$?; echo "错误：[$STAGE] 安装失败（退出码 $rc）" >&2; exit "$rc"' ERR
trap 'if [[ -n "$_AGENT_TMP" ]]; then rm -f -- "$_AGENT_TMP"; fi' EXIT

STELLA_URL="${STELLA_URL:-http://127.0.0.1:12031}"
TOKEN=""
INSTALL_DIR="/opt/stella-agent"
PBR=0
DEPS_MODE="ask"   # ask（默认交互询问）| auto（--deps 自动装）| skip（--no-deps 跳过）

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) STELLA_URL="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --pbr) PBR=1; shift ;;
    --deps) DEPS_MODE="auto"; shift ;;
    --no-deps) DEPS_MODE="skip"; shift ;;
    *) shift ;;
  esac
done

if [[ -z "$TOKEN" ]]; then
  echo "错误：缺少 --token" >&2
  exit 1
fi

echo "==> Stella Agent 安装中..."
STAGE="前置检查"
[[ "$(id -u)" == "0" ]] || fail "请以 root / sudo 运行"
_SYSCTL=$(command -v systemctl) || fail "缺少 systemctl，必须使用 systemd"
_RM=$(command -v rm) || fail "缺少 rm"
command -v curl >/dev/null 2>&1 || fail "缺少 curl，请安装后重试"

# 交互式询问（从 /dev/tty 读，避免 curl|bash 时 stdin 被管道占用；无 TTY 则用默认值）
ask_yn() {
  local prompt="$1" default="$2" ans=""
  if ( : < /dev/tty ) 2>/dev/null; then
    read -r -p "$prompt " ans < /dev/tty || ans=""
  fi
  case "$ans" in
    [Yy]|[Yy][Ee][Ss]) return 0 ;;
    [Nn]|[Nn][Oo]) return 1 ;;
    *) [[ "$default" == "y" ]] && return 0 || return 1 ;;
  esac
}

STAGE="python3"
# ── 1. 检测 python3（硬依赖，缺失则询问安装） ──
if command -v python3 >/dev/null 2>&1; then
  echo "    python3: $(python3 --version)"
else
  echo "    [缺] python3（Stella Agent 必需）"
  if [[ "$DEPS_MODE" == "skip" ]]; then
    echo "错误：--no-deps 且未检测到 python3，无法继续" >&2
    exit 1
  fi
  if [[ "$DEPS_MODE" == "ask" ]]; then
    ask_yn "    是否自动安装 python3（含 pip）？[Y/n]" "y" || { echo "    已取消，退出" >&2; exit 1; }
  fi
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq python3 python3-pip
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y -q python3 python3-pip
  elif command -v yum >/dev/null 2>&1; then
    yum install -y -q python3 python3-pip
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache python3 py3-pip
  else
    echo "错误：无法识别包管理器，请手动安装 python3 后重试" >&2
    exit 1
  fi
  echo "    python3: $(python3 --version)"
fi

STAGE="用户与 sudoers"
# ── 2. 独立系统用户（PBR 按 UID 识别 + 最小权限） ──
if ! id -u stella >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin stella 2>/dev/null || \
    useradd -r -M -s /usr/sbin/nologin stella
  echo "    已创建独立用户 stella"
fi

# sudoers：允许 stella 卸载自己 + 代装 iperf3（NOPASSWD 白名单，路径按当前系统动态取）
_APT=$(command -v apt-get || true)
_DNF=$(command -v dnf || true)
_YUM=$(command -v yum || true)
_APK=$(command -v apk || true)
_PACMAN=$(command -v pacman || true)
_CMDS="${_SYSCTL} stop stella-agent, ${_SYSCTL} disable stella-agent, ${_SYSCTL} daemon-reload, ${_RM} -f /etc/systemd/system/stella-agent.service, ${_RM} -rf /opt/stella-agent"
# 组件代装：允许 stella 装 iperf3（各发行版包管理器，精确到包名，不放开任意安装）
[ -n "$_APT" ] && _CMDS="${_CMDS}, ${_APT} install -y iperf3"
[ -n "$_DNF" ] && _CMDS="${_CMDS}, ${_DNF} install -y iperf3"
[ -n "$_YUM" ] && _CMDS="${_CMDS}, ${_YUM} install -y iperf3"
[ -n "$_APK" ] && _CMDS="${_CMDS}, ${_APK} add iperf3"
[ -n "$_PACMAN" ] && _CMDS="${_CMDS}, ${_PACMAN} -S --noconfirm iperf3"
# 组件代装：ufw / docker（Debian 系 docker 包名是 docker.io）/ mtr（Debian 系叫 mtr-tiny）+ 装完拉起 docker 守护
[ -n "$_APT" ] && _CMDS="${_CMDS}, ${_APT} install -y ufw, ${_APT} install -y docker.io, ${_APT} install -y mtr-tiny"
[ -n "$_DNF" ] && _CMDS="${_CMDS}, ${_DNF} install -y ufw, ${_DNF} install -y docker, ${_DNF} install -y mtr"
[ -n "$_YUM" ] && _CMDS="${_CMDS}, ${_YUM} install -y ufw, ${_YUM} install -y docker, ${_YUM} install -y mtr"
[ -n "$_APK" ] && _CMDS="${_CMDS}, ${_APK} add ufw, ${_APK} add docker, ${_APK} add mtr"
[ -n "$_PACMAN" ] && _CMDS="${_CMDS}, ${_PACMAN} -S --noconfirm ufw, ${_PACMAN} -S --noconfirm docker, ${_PACMAN} -S --noconfirm mtr"
_CMDS="${_CMDS}, ${_SYSCTL} enable --now docker"
# Docker 面板：容器列表/启停重启（只读+容器级操作，不放开镜像/网络管理）
_DOCKER=$(command -v docker || true)
[ -n "$_DOCKER" ] && _CMDS="${_CMDS}, ${_DOCKER}"
# 网络操作（改 IP 回退 / 防火墙查看 / PBR 查看）：允许 stella sudo 执行这些网络配置/只读命令
_IP=$(command -v ip || true)
_NMCLI=$(command -v nmcli || true)
_NETPLAN=$(command -v netplan || true)
_UFW=$(command -v ufw || true)
_IPTABLES_SAVE=$(command -v iptables-save || true)
_IPTABLES=$(command -v iptables || true)
[ -n "$_IP" ] && _CMDS="${_CMDS}, ${_IP}"
[ -n "$_NMCLI" ] && _CMDS="${_CMDS}, ${_NMCLI}"
[ -n "$_NETPLAN" ] && _CMDS="${_CMDS}, ${_NETPLAN}"
[ -n "$_UFW" ] && _CMDS="${_CMDS}, ${_UFW}"
[ -n "$_IPTABLES_SAVE" ] && _CMDS="${_CMDS}, ${_IPTABLES_SAVE}"
[ -n "$_IPTABLES" ] && _CMDS="${_CMDS}, ${_IPTABLES}"
# 改 IP 连通性验证：sudo ping 绕 owner-mark（agent 被 PBR 打标走固定出口，直连探测摸不到被改接口的网关）
_PING=$(command -v ping || true)
[ -n "$_PING" ] && _CMDS="${_CMDS}, ${_PING}"
cat > /etc/sudoers.d/stella-uninstall << EOF
stella ALL=(root) NOPASSWD: ${_CMDS}
EOF
chmod 440 /etc/sudoers.d/stella-uninstall

# pip 安装：用系统包管理器（Ubuntu/Debian 的 python3 不带 ensurepip，用 ensurepip 必然失败）
_install_pip() {
  if command -v apt-get >/dev/null 2>&1; then
    apt-get install -y -qq python3-pip
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y -q python3-pip
  elif command -v yum >/dev/null 2>&1; then
    yum install -y -q python3-pip
  elif command -v apk >/dev/null 2>&1; then
    apk add --no-cache py3-pip
  elif python3 -m ensurepip --version >/dev/null 2>&1; then
    python3 -m ensurepip --upgrade
  else
    return 1
  fi
}

STAGE="pip"
# ── 3. 检测 pip ──
HAVE_PIP=0
if python3 -m pip --version >/dev/null 2>&1; then
  HAVE_PIP=1
  echo "    pip: 已就绪"
else
  echo "    [缺] pip（缺少则无法安装 httpx/psutil，agent 用 urllib 兜底仍可运行）"
  if [[ "$DEPS_MODE" == "auto" ]]; then
    _install_pip || true
  elif [[ "$DEPS_MODE" == "ask" ]]; then
    if ask_yn "    是否安装 pip？[Y/n]" "y"; then _install_pip || true; fi
  fi
  if python3 -m pip --version >/dev/null 2>&1; then
    HAVE_PIP=1
    echo "    pip 已装好"
  else
    echo "    [warn] pip 安装失败，httpx/psutil 无法安装（agent 将降级运行）"
  fi
fi

# Debian/Ubuntu externally-managed Python: use distro packages, never force pip.
_install_python_deps() {
  if [[ -n "$_APT" ]]; then
    local packages=() dep
    for dep in "${MISSING[@]}"; do packages+=("python3-$dep"); done
    apt-get install -y -qq "${packages[@]}"
  elif [[ "$HAVE_PIP" == "1" ]]; then
    python3 -m pip install --quiet "${MISSING[@]}"
  else
    return 1
  fi
}

STAGE="可选 Python 依赖"
# ── 4. 检测可选依赖 httpx / psutil ──
echo "==> 检查依赖..."
MISSING=()
python3 -c "import httpx" 2>/dev/null || MISSING+=("httpx")
python3 -c "import psutil" 2>/dev/null || MISSING+=("psutil")

if [[ ${#MISSING[@]} -eq 0 ]]; then
  echo "    httpx / psutil 已就绪"
elif [[ "$HAVE_PIP" != "1" && -z "$_APT" ]]; then
  echo "    [缺] ${MISSING[*]}，且无 pip，跳过安装（agent 将降级运行）"
elif [[ "$DEPS_MODE" == "skip" ]]; then
  echo "    [缺] ${MISSING[*]}，--no-deps 跳过安装（agent 将降级运行）"
elif [[ "$DEPS_MODE" == "auto" ]]; then
  _install_python_deps || echo "    [warn] 可选依赖安装失败，将降级运行"
else
  echo "    [缺] ${MISSING[*]}（缺失时 agent 降级运行，不影响核心上报）"
  if ask_yn "    是否安装缺失依赖？[Y/n]" "y"; then
    _install_python_deps || echo "    [warn] 可选依赖安装失败，将降级运行"
  else
    echo "    已跳过，agent 将降级运行"
  fi
fi

STAGE="可选打流组件"
# ── 4.5 打流组件（iperf3 / speedtest-go）──
echo "==> 检查打流组件..."
_install_pkg_iperf3() {
  if command -v apt-get >/dev/null 2>&1; then apt-get install -y -qq iperf3
  elif command -v dnf >/dev/null 2>&1; then dnf install -y -q iperf3
  elif command -v yum >/dev/null 2>&1; then yum install -y -q iperf3
  elif command -v apk >/dev/null 2>&1; then apk add --no-cache iperf3
  else echo "    [warn] 无法识别包管理器，跳过 iperf3"; return 1; fi
  command -v iperf3 >/dev/null 2>&1 && echo "    iperf3 已装好" || echo "    [warn] iperf3 安装失败（可在面板代装）"
}
_install_speedtest_go() {
  local _arch; _arch=$(uname -m)
  case "$_arch" in x86_64) _arch="x86_64";; aarch64) _arch="arm64";; armv7l) _arch="armv7";; armv6l) _arch="armv6";; i686) _arch="i386";; esac
  # 资产名带版本号（speedtest-go_<tag>_Linux_<arch>.tar.gz），先跟随 latest 重定向拿 tag
  local _tag; _tag=$(curl -sSL -o /dev/null -w "%{url_effective}" "https://github.com/showwin/speedtest-go/releases/latest" 2>/dev/null | sed 's#.*/##')
  [ -z "$_tag" ] && _tag="v1.7.11"
  local _url="https://github.com/showwin/speedtest-go/releases/download/${_tag}/speedtest-go_${_tag}_Linux_${_arch}.tar.gz"
  local _tmp; _tmp=$(mktemp -d)
  if curl -sSL -A "Mozilla/5.0" "$_url" -o "$_tmp/st.tar.gz" 2>/dev/null \
    && tar -xzf "$_tmp/st.tar.gz" -C "$_tmp" 2>/dev/null \
    && mv "$_tmp/speedtest-go" /usr/local/bin/speedtest-go 2>/dev/null; then
    chmod +x /usr/local/bin/speedtest-go
    echo "    speedtest-go 已装好"
  else
    echo "    [warn] speedtest-go 下载失败（可在面板代装）"
  fi
  rm -rf "$_tmp" 2>/dev/null
}
if command -v iperf3 >/dev/null 2>&1; then
  echo "    iperf3: 已就绪"
elif [[ "$DEPS_MODE" == "skip" ]]; then
  echo "    [缺] iperf3（--no-deps 跳过，可在面板点「安装」代装）"
elif [[ "$DEPS_MODE" == "auto" ]]; then
  _install_pkg_iperf3
elif ask_yn "    是否安装 iperf3（打流测速）？[Y/n]" "y"; then
  _install_pkg_iperf3
fi
if command -v speedtest-go >/dev/null 2>&1; then
  echo "    speedtest-go: 已就绪"
elif [[ "$DEPS_MODE" == "skip" ]]; then
  echo "    [缺] speedtest-go（--no-deps 跳过，可在面板点「安装」代装）"
elif [[ "$DEPS_MODE" == "auto" ]]; then
  _install_speedtest_go
elif ask_yn "    是否安装 speedtest-go（公网测速）？[Y/n]" "y"; then
  _install_speedtest_go
fi

# ── 5. 校验 token（任何未验证的凭证都不继续安装） ──
STAGE="校验 token"
echo "==> 校验 token..."
_TOKEN_HTTP=$(curl -sS --connect-timeout 10 --max-time 30 -o /dev/null -w "%{http_code}" \
  --get --data-urlencode "token=$TOKEN" "$STELLA_URL/agent/config" 2>/dev/null) || fail "无法连接中心校验 token"
case "$_TOKEN_HTTP" in
  200) echo "    token 校验通过" ;;
  401) fail "HTTP 401：token 无效或已失效，请从面板复制最新安装命令" ;;
  *) fail "中心未确认 token 有效，请检查中心连接后重试" ;;
esac

# ── 6. 下载并验证，原子替换；失败保留已有可运行文件 ──
STAGE="下载 agent"
echo "==> 下载 agent..."
mkdir -p "$INSTALL_DIR"
_AGENT_TMP=$(mktemp "$INSTALL_DIR/.stella_agent.XXXXXX")
curl -fsSL --connect-timeout 10 --max-time 120 "$STELLA_URL/agent/script" \
  -o "$_AGENT_TMP" 2>/dev/null || fail "主程序下载失败（HTTP 或网络错误）"
STAGE="验证 agent Python"
[[ -s "$_AGENT_TMP" ]] || fail "下载的主程序为空"
# Compile only: do not execute downloaded code or produce a pycache as root.
python3 -c 'import pathlib, sys; p = pathlib.Path(sys.argv[1]); compile(p.read_bytes(), str(p), "exec")' \
  "$_AGENT_TMP" 2>/dev/null || fail "下载内容不是有效的 Python（可能是 HTML 错误页）"
chmod 755 "$_AGENT_TMP"
chown stella:stella "$_AGENT_TMP"
mv -f -- "$_AGENT_TMP" "$INSTALL_DIR/stella_agent.py"
_AGENT_TMP=""
# 保留 agent 的自更新权限。
chown -R stella:stella "$INSTALL_DIR"

STAGE="systemd"
# ── 7. 写 systemd 单元（独立用户 + raw socket 权限跑探测） ──
echo "==> 配置 systemd 服务..."
cat > /etc/systemd/system/stella-agent.service << EOF
[Unit]
Description=Stella Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=stella
AmbientCapabilities=CAP_NET_RAW
ExecStart=/usr/bin/env python3 $INSTALL_DIR/stella_agent.py --url $STELLA_URL --token $TOKEN
Restart=always
RestartSec=5
Environment=STELLA_URL=$STELLA_URL
Environment=STELLA_TOKEN=$TOKEN

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable stella-agent
systemctl restart stella-agent

STAGE="PBR"
# ── 8. 可选 PBR：agent 流量直连公网出口（宿主有透明代理时加） ──
if [[ "$PBR" == "1" ]]; then
  if [[ -s "$INSTALL_DIR/pbr.sh" ]]; then
    bash "$INSTALL_DIR/pbr.sh"
  else
    echo "    [warn] 未找到 pbr.sh，跳过 PBR 配置"
  fi
fi

STAGE="检查服务启动"
sleep 2
systemctl is-active --quiet stella-agent || fail "服务未保持运行，请查看 journalctl -u stella-agent；安装未完成"
echo "==> 安装完成，服务已启动；是否在线请在 Stella 面板确认心跳。状态："
systemctl --no-pager status stella-agent -l | head -5 || true
