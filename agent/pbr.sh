#!/bin/bash
# Stella Agent PBR：按 UID 识别 agent 流量，最高优先级直连公网出口（绕过透明代理）
# 用法：sudo bash pbr.sh [--mark 0xE11A] [--pref 50]
# 注意：mark/pref 需避开宿主透明代理现有分配（如 nyarch 的 Xray mark=1→表100）
set -e

MARK="0xE11A"   # stella 专属 mark（默认，可覆盖）
PREF="50"       # ip rule 优先级（越小越高，需压过 tun 分流规则）
USER_NAME="stella"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mark) MARK="$2"; shift 2 ;;
    --pref) PREF="$2"; shift 2 ;;
    *) shift ;;
  esac
done

if ! command -v iptables >/dev/null 2>&1 && ! command -v nft >/dev/null 2>&1; then
  echo "错误：需要 iptables 或 nft" >&2
  exit 1
fi

# 1. 打 mark：按源 UID 识别 agent 全部流量（含子进程 ping/iperf3/mtr）
if command -v iptables >/dev/null 2>&1; then
  if ! iptables -t mangle -C OUTPUT -m owner --uid-owner "$USER_NAME" -j MARK --set-mark "$MARK" 2>/dev/null; then
    iptables -t mangle -A OUTPUT -m owner --uid-owner "$USER_NAME" -j MARK --set-mark "$MARK"
    echo "==> iptables: UID=$USER_NAME → mark=$MARK"
  fi
fi

# 2. ip rule：最高优先级走 main 表（物理网卡真实出口，绕过 tun）
if ! ip rule show | grep -q "fwmark $MARK"; then
  ip rule add fwmark "$MARK" lookup main pref "$PREF"
  echo "==> ip rule: fwmark=$MARK → main, pref=$PREF"
fi

echo "==> PBR 配置完成。agent 探测/打流/MTR 将直连公网出口。"
