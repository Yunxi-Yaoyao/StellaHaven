#!/bin/bash
# Stella Agent 安装脚本（Linux / 飞牛OS）
# 用法：curl -sSL <此脚本URL> | sudo bash -s -- --url http://<stella> --token <token> [--pbr] [--deps | --no-deps]
set -e

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
echo "    中心: $STELLA_URL"

# 交互式询问（从 /dev/tty 读，避免 curl|bash 时 stdin 被管道占用；无 TTY 则用默认值）
ask_yn() {
  local prompt="$1" default="$2" ans=""
  if [[ -c /dev/tty ]]; then
    read -r -p "$prompt " ans < /dev/tty || ans=""
  fi
  case "$ans" in
    [Yy]|[Yy][Ee][Ss]) return 0 ;;
    [Nn]|[Nn][Oo]) return 1 ;;
    *) [[ "$default" == "y" ]] && return 0 || return 1 ;;
  esac
}

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

# ── 2. 独立系统用户（PBR 按 UID 识别 + 最小权限） ──
if ! id -u stella >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin stella 2>/dev/null || \
    useradd -r -M -s /usr/sbin/nologin stella
  echo "    已创建独立用户 stella"
fi

# sudoers：允许 stella 卸载自己 + 代装 iperf3（NOPASSWD 白名单，路径按当前系统动态取）
_SYSCTL=$(command -v systemctl)
_RM=$(command -v rm)
_APT=$(command -v apt-get)
_DNF=$(command -v dnf)
_YUM=$(command -v yum)
_APK=$(command -v apk)
_PACMAN=$(command -v pacman)
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
_DOCKER=$(command -v docker)
[ -n "$_DOCKER" ] && _CMDS="${_CMDS}, ${_DOCKER}"
# 网络操作（改 IP 回退 / 防火墙查看 / PBR 查看）：允许 stella sudo 执行这些网络配置/只读命令
_IP=$(command -v ip)
_NMCLI=$(command -v nmcli)
_NETPLAN=$(command -v netplan)
_UFW=$(command -v ufw)
_IPTABLES_SAVE=$(command -v iptables-save)
_IPTABLES=$(command -v iptables)
[ -n "$_IP" ] && _CMDS="${_CMDS}, ${_IP}"
[ -n "$_NMCLI" ] && _CMDS="${_CMDS}, ${_NMCLI}"
[ -n "$_NETPLAN" ] && _CMDS="${_CMDS}, ${_NETPLAN}"
[ -n "$_UFW" ] && _CMDS="${_CMDS}, ${_UFW}"
[ -n "$_IPTABLES_SAVE" ] && _CMDS="${_CMDS}, ${_IPTABLES_SAVE}"
[ -n "$_IPTABLES" ] && _CMDS="${_CMDS}, ${_IPTABLES}"
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
    ask_yn "    是否安装 pip？[Y/n]" "y" && _install_pip
  fi
  if python3 -m pip --version >/dev/null 2>&1; then
    HAVE_PIP=1
    echo "    pip 已装好"
  else
    echo "    [warn] pip 安装失败，httpx/psutil 无法安装（agent 将降级运行）"
  fi
fi

# ── 4. 检测可选依赖 httpx / psutil ──
echo "==> 检查依赖..."
MISSING=()
python3 -c "import httpx" 2>/dev/null || MISSING+=("httpx")
python3 -c "import psutil" 2>/dev/null || MISSING+=("psutil")

if [[ ${#MISSING[@]} -eq 0 ]]; then
  echo "    httpx / psutil 已就绪"
elif [[ "$HAVE_PIP" != "1" ]]; then
  echo "    [缺] ${MISSING[*]}，且无 pip，跳过安装（agent 将降级运行）"
elif [[ "$DEPS_MODE" == "skip" ]]; then
  echo "    [缺] ${MISSING[*]}，--no-deps 跳过安装（agent 将降级运行）"
elif [[ "$DEPS_MODE" == "auto" ]]; then
  python3 -m pip install --quiet "${MISSING[@]}" || echo "    [warn] pip 安装失败，将降级运行"
else
  echo "    [缺] ${MISSING[*]}（缺失时 agent 降级运行，不影响核心上报）"
  if ask_yn "    是否安装缺失依赖？[Y/n]" "y"; then
    python3 -m pip install --quiet "${MISSING[@]}" || echo "    [warn] pip 安装失败，将降级运行"
  else
    echo "    已跳过，agent 将降级运行"
  fi
fi

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

# ── 5. 下载 agent 主程序 ──
echo "==> 下载 agent..."
mkdir -p "$INSTALL_DIR"
if command -v curl >/dev/null 2>&1; then
  curl -sSL "$STELLA_URL/agent/script" -o "$INSTALL_DIR/stella_agent.py" 2>/dev/null || true
elif command -v wget >/dev/null 2>&1; then
  wget -q "$STELLA_URL/agent/script" -O "$INSTALL_DIR/stella_agent.py" 2>/dev/null || true
fi

if [[ ! -s "$INSTALL_DIR/stella_agent.py" ]]; then
  echo "    [warn] 中心未提供 /agent/script，请手动放置 stella_agent.py 到 $INSTALL_DIR/"
fi
chmod +x "$INSTALL_DIR/stella_agent.py" 2>/dev/null || true
# 目录属主交给 stella（agent 以 stella 用户跑，自更新需要写权限覆盖脚本）
chown -R stella:stella "$INSTALL_DIR" 2>/dev/null || true

# ── 6. 校验 token（提前发现 token 错误，避免装完一直离线） ──
echo "==> 校验 token..."
_TOKEN_HTTP=$(curl -sSL -o /dev/null -w "%{http_code}" "$STELLA_URL/agent/config?token=$TOKEN" 2>/dev/null || echo "000")
case "$_TOKEN_HTTP" in
  200)
    echo "    token 校验通过"
    ;;
  401)
    echo "⚠️  token 校验失败（HTTP 401）—— token 无效或已失效！" >&2
    echo "    请回到 Stella 服务器页，重新打开该节点的 agent 弹窗复制最新安装命令。" >&2
    echo "    否则 agent 装上后无法上报，会一直显示「离线」。" >&2
    if [[ "$DEPS_MODE" != "auto" ]]; then
      ask_yn "    是否仍要继续安装？（token 错误会导致离线）[y/N]" "n" || { echo "    已取消安装"; exit 1; }
    fi
    ;;
  *)
    echo "    [warn] token 校验请求失败（HTTP $_TOKEN_HTTP，中心可能不可达），跳过校验"
    ;;
esac

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

# ── 8. 可选 PBR：agent 流量直连公网出口（宿主有透明代理时加） ──
if [[ "$PBR" == "1" ]]; then
  if [[ -s "$INSTALL_DIR/pbr.sh" ]]; then
    bash "$INSTALL_DIR/pbr.sh"
  else
    echo "    [warn] 未找到 pbr.sh，跳过 PBR 配置"
  fi
fi

echo "==> 安装完成。状态："
systemctl --no-pager status stella-agent -l | head -5 || true
