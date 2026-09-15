# Local HA：隔离契约与只读验证（尚不能发布）

**这是 disabled-by-default 的非生产部署契约，不是已验收 HA 集群。**
现阶段可执行：离线单元测试、真实 `docker compose config`、对操作员已建好的隔离双节点执行 SSH 只读验证。
不能执行：生产迁移、数据库初始化/复制、etcd 成员修改、应用真实发布、主从切换或自动故障转移。
`release.run` 的更新/回滚测试使用 FakeTransport；SSHTransport 的写操作明确拒绝，不得将 mock 成功当成真实发布成功。

## 动态媒体 PG 集成

背景/头像路由、事务边界、缓存限制与隔离回归命令见 [MEDIA_README.md](MEDIA_README.md)。这不改变本文件的生产发布与主从切换禁令。

## CI 安全边界

- branch/MR 执行 test 与 build；镜像只打完整 `$CI_COMMIT_SHA` 标签（不是短 SHA）。真正部署契约必须使用 `repository@sha256:...`，SHA 标签并非 registry 强制不可变策略。
- `latest` 仅 protected master 且 `STELLA_DEPLOY_TARGET` 为默认 `k3s` 时更新。
- 旧 `deploy-k3s` 仅 protected master，target 未设置/空/`k3s`，保留旧 master 自动行为；未知 target 和 `local-ha` 都不部署。额外 shell guard 防误执行；production resource group 串行。
- **不提供 local-ha apply job**；local-ha 尚未接受 fencing，不能靠设置 CI 布尔变量绕过。
- `local-ha-contract` 自动运行下述测试，Compose config 不访问 Docker daemon、不启动容器。
- feature 分支 `local-ha-live-readonly` 是 manual/optional，GitLab 未点击显示 manual/skipped，**不是通过验证**。点击后缺 inventory、SSH 配置或 digest 会失败，不能输出伪成功。
- 非生产验证凭据只应拥有隔离主机只读权限；生产 KUBECONFIG/密钥须在 GitLab 设置为 protected、environment-scoped。YAML rules 无法隔离带生产 Docker socket 的不可信 runner；使用隔离 runner 才是主机级隔离。
- 禁止把 `.env`、私钥、真实密码、资源或 PGDATA 提交到仓库。CI Postgres 使用公开的测试专用密码，不复用生产密码。

## 本地验证（不启动服务）

需要 Python 3.13、PyYAML、Docker CLI + Compose。运行目录为仓库根：

```sh
python -m unittest discover -s deploy/local-ha/tests -v
```

测试使用 `.invalid` 地址和临时目录。模板测试实际执行 `docker compose ... config --format json`；不执行 `up`、pull、迁移或对真实节点发请求。

手动渲染时传入实际已验证的镜像 digest 与三个独立 etcd HTTPS endpoint：

```sh
python deploy/local-ha/render.py --output /tmp/local-ha-render \
  --node nyarch --node-ip 10.66.0.2 \
  --app-image "$APP_DIGEST" --pg-image "$PG_DIGEST" \
  --etcd-hosts "$ETCD_1" "$ETCD_2" "$ETCD_3"
docker compose --env-file /tmp/local-ha-render/compose.env \
  -f deploy/local-ha/compose.yaml config --quiet
```

渲染不覆盖现有文件。三个字符串不同不代表真实 quorum。模板默认 `LOCAL_HA_ENABLE_DATABASE=no` / `LOCAL_HA_ENABLE_APP=no`；不要改开关并直接 `up`。

## 隔离运行契约与启动前缺项

- 独立 project `stella-local-ha-{nyarch,nas}`、独立根 `/srv/stella-local-ha/<node>`、独立 DCS scope `stella-local-ha-v1`；不得挂 k3s/生产 PGDATA、共享 NFS 数据库卷。
- 同机 PG `127.0.0.1:24532`，Patroni `127.0.0.1:24808`，应用 `127.0.0.1:24131`；启用 host networking 前由操作员核对端口、卷、名称冲突及防火墙。数据库/Patroni listen 是 `0.0.0.0`，必须限制访问。
- PG18 数据必须由另行批准的种子流程提供，要求 `PG_VERSION=18` 与 `.local-ha-independent` 内容为上述 scope；marker 只检查操作员声明，不证明存储隔离。
- 应用启用 `STELLA_HA_MODE=primary-only`、`STELLA_PATRONI_URL`，两节点同一外部签名密钥（至少32字符）绑定 `/data/secret_key`。HA 模式拒绝缺钥，不自动生成。不在该 Compose 设置另一个 `STELLA_SECRET_KEY` 以免覆盖挂载密钥。
- secrets 目录要求 app-password、pg-super-password、pg-repl-password、patroni-api-password、etcd-ca.crt、etcd-client.crt、etcd-client.key；signing-key 单独绑定应用。使用受限权限、离线分发；这里不生成生产密钥。
- resources 为只读 `/app/data`，必须有 manifest.json：`{"files":{"relative/path":{"size":123,"sha256":"<hex>"}}}`。启动做 full hash；周期探测仅存在/尺寸检查。独立可写 cache 挂 `/app/data/cache`。两节点 bundle 与 signing-key 指纹一致才可计划。
- Patroni nofailover=true、watchdog=off，无 bootstrap，没有实现安全自动升主；这些标志**不等价于 fencing**。
- `/live` 是进程存活；`/ready-primary` 仅同机 Patroni /primary=200 且 SQL writable primary 放行。备用 app healthcheck 为 unhealthy 是预期的写就绪结果，不代表可以提升它。

## 已建隔离主机的真实只读验证

操作员先把 node.py、release.py 放在 `/opt/stella-local-ha/`，其依赖的运行容器须已由独立验收流程建立。此操作不由 CI 自动执行。
节点 `/etc/stella-local-ha/node.json`（root 管理，路径不要指向生产）：

```json
{"scope":"stella-local-ha-v1","environment":"nonproduction","node":"nas","env_file":"/etc/stella-local-ha/compose.env","compose_file":"/opt/stella-local-ha/compose.yaml"}
```

CI file variable `LOCAL_HA_INVENTORY` 内容：

```json
{"scope":"stella-local-ha-v1","environment":"nonproduction","current_primary":"nyarch","hosts":{"nyarch":"ha-test-nyarch","nas":"ha-test-nas"}}
```

`LOCAL_HA_SSH_CONFIG` 是 OpenSSH 配置 file variable，提供上述别名、非生产用户名、IdentityFile 和已核验的 UserKnownHostsFile；不使用自动 ssh-keyscan 信任或 StrictHostKeyChecking=no。`LOCAL_HA_APP_IMAGE` 提供 registry 中真实 digest。

```sh
python deploy/local-ha/validate_live.py --inventory "$LOCAL_HA_INVENTORY" \
  --ssh-config "$LOCAL_HA_SSH_CONFIG" --image "$LOCAL_HA_APP_IMAGE"
```

node.py 只执行 compose ps、docker inspect 与容器内 readiness；核验 project、node identity、digest，再读 SQL 与 HTTP。返回 `read-only-validated` 仅表示此次观测成立，同时明确 `deployment_authorized=false`、`fencing_status=not-accepted`、`apply_status=blocked`。SSH timeout/角色漂移/双主/零主/资源不齐/密钥不一致均拒绝。

## 发布与迁移待验收清单

真实发布必须先有受信 inventory、即时 current-primary 双重核对、独立 fencing 可用性实测、节点端 release 锁和不可绕过的权限边界。当前一律禁止 host writes 和 switchover，不接受人为 `fenced=true` 作为证据。
数据库迁移必须在唯一可写主库、跨进程 advisory lock 下执行一次；旧/新应用混跑需已审核的向后兼容 schema。`compatible=True` 只是一项 release planner 前置声明，不能替代迁移锁测试。不可逆 schema 不自动回滚。
待父任务验证应用侧迁移锁、共享 OIDC 状态、资源同步、真实 image、独立 etcd quorum、硬件 fencing 与切换演练后，另开审批实现 apply。此 README 不声明这些已通过。
