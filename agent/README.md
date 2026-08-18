# Stella Agent

被纳管服务器的采集上报 + 任务执行客户端。单文件 Python，跨 Linux / Windows / 飞牛OS。

## 职责

1. **采集**：网卡流量（默认出口网卡）、系统指标（CPU/内存/磁盘）
2. **上报**：5s 流量 + 60s 系统指标（上报即心跳）
3. **补传**：内存队列，上报失败时缓存，恢复后按时间顺序批量补传（上限 24h）
4. **任务**：5s 轮询待办任务（打流/MTR/命令），执行后回传结果
5. **网卡检测**：默认路由 → 出口网卡，上报网卡清单供中心配置

## 安装

### Linux（含飞牛OS）

```bash
curl -sSL http://<stella>/agent/script -o /tmp/stella_agent.py
sudo bash -c 'python3 /tmp/stella_agent.py --url http://<stella> --token <token>'
# 或 systemd 常驻：
curl -sSL http://<stella>/agent/install.sh | sudo bash -s -- --url http://<stella> --token <token>
```

### Windows

```powershell
# 管理员 PowerShell
iwr http://<stella>/agent/script -UseBasicParsing -OutFile C:\stella-agent.py
# 计划任务常驻：
iwr http://<stella>/agent/install.ps1 -UseBasicParsing | iex
```

## 依赖

- `psutil`（可选，缺失则系统指标/网卡清单降级）
- `httpx`（可选，缺失则用 urllib 兜底）

都缺失也能跑，只是功能降级——流量采集走 `/proc/net/dev` 兜底。

## 配置

| 参数 | 环境变量 | 说明 |
|---|---|---|
| `--url` | `STELLA_URL` | 中心地址，默认 `http://127.0.0.1:12031` |
| `--token` | `STELLA_TOKEN` | 节点鉴权 token（中心「添加节点」时生成） |

## 时间参数

| 项 | 值 |
|---|---|
| 流量上报 | 5s |
| 系统指标 | 60s |
| 任务轮询 | 5s |
| 配置拉取 | 60s |
| 补传队列上限 | 24h |
