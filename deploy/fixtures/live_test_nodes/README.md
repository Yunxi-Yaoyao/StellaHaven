# 常驻、自有、隔离的可操作测试节点

当前稳定入口：`https://stella-dev.p.xiya.live/status?view=nodes`。真实节点记录 **2/3**；只代表容器网络空间，不代表宿主机或公网多地区节点。

## 可以实际输入的目标

- Ping / ICMP MTR：`192.168.160.3`（节点 A → 节点 B）；反向为 `192.168.160.2`。
- TCP / TCP MTR：`192.168.160.3:8080`，受控 HTTP/TCP 服务。
- 故障 TCP 样本：`192.168.160.3:8081`，明确关闭的容器端口。TCP 失败不是丢包率。
- 只允许上述两个数字 IP 和 TCP 8080/8081；域名、公网/宿主地址、HTTP URL、任意远程命令/安装/打流/WG/防火墙/Docker管理均拒绝，不写假成功数据。
- 自动探测最小 60 秒、超时最多 2 秒；MTR 最多 10 包、4 跳、128 字节、包间隔 1–2 秒。候选参数名是 **max_hops**，不是无效的 max_ttl。

## 常驻运行和恢复

已启用 `stella-live-test-nodes.service`。它只管理本 fixture Compose 和自己的透明 TLS relay；容器 `restart: unless-stopped`，只读根、无任何宿主挂载/host network/privileged/docker socket，仅 `NET_RAW`。隔离 internal 网络为 `192.168.160.0/28`。Relay 只收两 fixture IP 且只转发准确 `stella-dev.p.xiya.live` TLS SNI，CA/证书验证不关闭。不开公网探测或共享防火墙/路由。

实际运行根：`/opt/hermes-workstation/docs/Stella-追加修正-20261019/live-test-nodes/`。系统单元引用这个独立持久路径，不依赖任何临时 worktree 的生命周期。正常节点 token 由 supervisor 从原 root-only 私密文件，经 stdin 写入容器私有 `/run` tmpfs，worker 读入内存后删除文件。未轮换 token，未改生产凭据。

本目录是可审查源码模板。`prepare_bundle.py` 从仓库候选 Agent 和本机真实 mtr/ping/动态加载器生成不含凭据的 bundle；生成二进制不进 Git。基础镜像是现有本地 Python 镜像 `stella-live-fixture-base:70729b46c69b`，没有安装网络依赖。受授权重建命令：

```sh
python3 deploy/fixtures/live_test_nodes/prepare_bundle.py
docker build --pull=false --network=none -t stella-live-test-nodes:20261019 deploy/fixtures/live_test_nodes
# 现有持久 supervisor 会在 up -d /容器重启后重新交付相同节点身份。
```

不会自动执行 `compose down`、删除节点/监控或销毁 fixture。不要运行旧 final-acceptance 的清理逻辑，不要调用宿主 `host/install` / uninstall。

## 自动节点监控策略（供父集成）

- `GET /nodes/monitoring-policy`：登录可读，无隐式写入。
- `PUT /nodes/monitoring-policy`：管理权限，完整字段 `{revision, enabled, source_node_id, host_node_id, interval}`；CAS 过期返回 409，间隔 60–3600。
- `PATCH /nodes/monitoring-policy/targets/{node_id}`：管理权限，`{suppressed: true|false}`；暂停只停止自动监控下发，不删历史，不影响手动监控。
- `NodeMonitoringPolicySettings.vue` 是独立组件，父在服务器设置区域 import/接线；本 lane 不编辑 SettingsPage/集成/预览树。
- 默认开启但无源，故安全等待；只有显式源在线且真实上报 `components.monitoring.ready/types=['ping', ...]` 后，创建节点/源心跳才自动幂等创建独立 managed Ping 项。不猜名称、回环或 NAT IP，不源自监控，不接管已有手动监控。
- fixture 源声明 `scope: container` 和精确允许目标；已知容器源不能绑定为真实宿主节点。真实宿主角色须管理员明确绑定已经纳管的真实节点；角色绑定不会安装/卸载/替换 Agent。现有本机服务存在时，安装入口返回409，防止预览接管生产 Agent。
- 改源/新间隔只影响后续新建监控，不改变已有监控源或历史口径。删除的 managed ID 留作墓碑，不被心跳复活；显示名变化不影响角色/记录。
- AppConfig `node_monitor_policy_v1` 持久化，无 DDL。PostgreSQL advisory transaction lock 跨 worker 序列化创建/策略写入；新节点与自动监控在同一事务中提交。

## 受测范围

`verify_policy_pg.py` 只在已核 sysid `7698041980212371498`、端口25436的测试 PostgreSQL 中创建临时 `stella_policy_*` 数据库，跑跨连接并发/墓碑、SQLite/HTTP定向测试后只删除该临时数据库。绝不删除常驻 fixture 或预览数据。

真实 API/MTR、重启身份和数据连续性、TLS SNI拒绝及生产不变证据见 `docs/Stella-追加修正-20261019/live-test-nodes/`。策略还需父合入并接线到常驻预览后复验；不可把独立用例通过当作线上已部署。
