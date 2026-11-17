# 节点文件模块交付契约（候选，不是生产接入）

**续交付：Linux独立伴随模式已经由 `node_files_lifecycle.py` 实现 install/update/status/stop/rollback 与unit生成。** 部署、依赖、pin、实际验收边界以 [NODE_FILES_LIFECYCLE.md](NODE_FILES_LIFECYCLE.md) 为准；旧单文件 updater仍不接管本模块，本页原分发契约继续有效。未自动部署/迁库/授根。

## 本变更

- `agent/node_files_delivery.py`：闭合整包 manifest（仅 `stella_agent.py`、`node_files.py`），逐文件实际版本/协议/平台/size/SHA256；HTTPS + Bearer、禁止重定向/代理、下载预算与必填的整包 canonical SHA pin；私有 generation + 单个原子 `current.json` 切换，导入预检及失败回退。
- `GET /agent/files/release`、`GET /agent/files/release/{canonical_sha256}/{name}`：复用真实 node token 鉴权，已移除节点拒绝；无授权路径/本地目录/token；`no-store`。源变化用 409 拒绝混包，源缺失/坏包用 503，未知工件 404。
- `node_files.py` 明确 `FILE_MODULE_VERSION=1.0.0`、`FILE_PROTOCOL=1`。本地 policy 仅允许 root ID → `{path,write?}`，默认空/只读；支持**显式配置** `path:"/"`，拒绝空/相对/遍历/重复分隔符/NULL路径、额外字段及非布尔 write。无 chmod/chown/sudo/删除新增能力。模块字节变化必须重建完整 manifest 与外层包，不能沿用旧 pin。
- `fetch/check/run` CLI 是可运行的**独立文件 Worker 伴随进程**；从已验证 generation 载入真实 FileWorker，不回退到 sys.path 中的 module，不导入 app/PG，不将 shell/命令执行当文件传输。不可与同节点 Agent 内置 `_file_tick` 同时启用（应选择唯一执行模式）。

## 平台与安全边界

真正文件能力目前仅 **Linux**（dirfd/O_NOFOLLOW/renameat2/POSIX ACL 拒绝策略）。Windows/其他平台不宣告 roots，伴随 Worker 启动拒绝；本轮没有做 NTFS/reparse-point/ACL 实现或 Windows 真机验收。不能给 Windows 节点授根来假装已有支持。

ReleaseStore 的全包目录是安装代码，不是用户数据根。Linux 必须当前实例 UID 拥有且无 group/world 写位；拒绝 symlink/hardlink/缺失或变更文件。Windows 安装目录需调用者预置私有 DACL，但这不意味着 Windows 文件 Worker 可用。目录锁不自动打破；崩溃留下锁时须停下并人工核归属。原 generation 留存，不自动清扫不明进程仍在使用的代码。不声称对同 UID 敌对进程形成 OS sandbox。Linux 执行 fsync；未声称 Windows 断电耐久性相同。

`transaction()` 的 rollback 包含真正子进程启动失败场景，但不提供断电后的跨进程自动回滚。**不能把 `os.exec*` 放在 context 内**，因为成功 exec 不执行 finally/锁释放。调用者在 context 内完成有界的子进程启动/就绪读回，退出后再做自己的 resident lifecycle；通用 updater 的崩溃恢复仍归其 owner。

## 可调用接口与人工部署准备（不是安装命令授权）

1. 从真实待发源码 `build_release(agent_source_dir)` 得到完整 manifest 和两工件，使用 `release_id(manifest)` 作不可变整包 pin。源版本变动要重新生成/审摘要，不能将本候选 pin 硬塞给另一条 Agent release。
2. 在已核准实例自己的私有代码子目录创建 `ReleaseStore(absolute_store)`。`download_release(origin, token, store, approved_sha)` 拉真实整包后验证并切换；不会动宿主已有 `stella_agent.py`、unit、任务计划、sudo 或根授权。
3. bootstrap helper 自身来自审核后的安装工件，单独固定其 SHA，不是由 manifest 指定任意下载 URL。CLI token 只读环境 `STELLA_TOKEN`，不放 argv/log。`fetch` 必须显式 `--release`。生产仅 HTTPS；`--allow-loopback` 是明确的隔离 HTTP 测试开关。
4. 文件伴随进程以原实例 UID + 仅 URL/token/明确本地 root policy 环境运行：`python -I -B <approved-bootstrap> run --store <private-store> --origin <exact-HTTPS-center>`。这里的占位符不是可直接执行的生产授权；无任何缺省根，`STELLA_FILE_ROOTS` 缺失即空。
5. 只有从实际下载的 module 完成认证 claim，中心 policy 与本地根 ID 同时匹配且 OS 权限足够，才会开放文件操作。**写入**必须两端都显式 `write:true`；读取不需要写授权。仅加中心 policy 不能授予 OS 路径。文件进程不需要 CAP_NET_RAW、sudo 或任意命令接口。
6. 文件 Worker **必需 httpx**（不同于旧 Agent 的标准库 fallback）；安装预检强制 import，缺依赖不切换。Linux 旧 installer 的 `--deps` 仅打印提示，并不实际安装依赖；新增独立lifecycle helper使用显式Python并降实例UID真实预检，依赖准备流程见新文档。没有临时改全局Python或共享venv。

## 交给通用 Agent owner 的精确接点（本分支没有改共享文件）

- **旧单文件 updater 仍只下载 `/agent/script`，不会自动请求新 manifest。** 此分支没有修改 `agent/stella_agent.py`、`install.sh`、`install.ps1`、`monitor.py`、公告或 fleet，故不能宣称通用更新链已接好。
- 已有 `agent_router` 被主站挂载时，新两 GET 自动位于 `/agent/files` 下，无需新增 main mount。但主功能全树的 operation/sourcegate/文档快照必须由集成 owner 显式登记，不能沿用 repair0622 的账本。
- 已选择伴随 Worker 模式：专门授权 `node_files_lifecycle.py` helper 已接入确切实例锁/UID/privateConfig凭据/完整包双pin与独立systemd lifecycle；通用installer默认不装，需管理员对既有实例明确选择执行，不开新root权限。主实例卸载前先stop伴随服务；不假称旧卸载helper已改造。
- 若坚持内置 `_file_tick` 模式，通用 updater/installer 必须一并安装与回退 module，启动时校验 bundle 与 resident script 的实际 SHA，不能仅复制主脚本；当前 optional import 的静默缺模块分支不是成功能力报告。本 helper 提供 staging/校验/原子指针与回退原语，但该共享 hook 尚未替换。
- **不要直接将 generation 中的 `stella_agent.py` 当新 ExecStart**：现行 `_installation_binding` 固定 Linux `/opt/stella-agents/<iid>/stella_agent.py`，Windows 绑定同目录 instance.json；迁移启动路径会违反归属检查。若通用 owner 要改布局，必须单独设计/测试身份与回滚，而不是绕检查。
- 仅一条运行路径的认证 FileAgent claim 才算就绪；代码安装/版本字符串相同不算。生产当前不含 files schema，仍需按父主功能发布/迁移 gate 集成后再授权 canary。

## 已确认的节点/目录范围，未扩大的写权限

用户明确“文件是所有目录 所有linux节点”：部署准备范围是**当前 Stella 已纳管的 Linux 节点，从 `/` 按需浏览**，不是新增机器、全盘递归扫描或绕过 OS 权限。fnOS 需以实际 Linux 元数据核实；Windows 排除。清单、来源时间与阻塞见 [NODE_FILES_ROOT_SCOPE.md](NODE_FILES_ROOT_SCOPE.md) 及非执行性 `node_files_root_deployment.example.json`。

这没有新增写授权：新 `system` 根示例为 `{path:"/",write:false}`，中心同样只读；保留各实例既有 UID、既有独立写授权，不能将任何 `write:true` 从旧小根扩散到 `/`。未配置仍 `{}`。本轮没有改真实中心 policy / files.env，也没有安装、启动或重启节点服务。

中心 owner 使用已认证的本人，不另扩大到其他用户。`/` 只是 dirfd 起点，不等于所有内容可读：仍逐级 nofollow，拒绝软/硬链接及特殊文件作为普通文本/下载/编辑；EACCES/EPERM 返回 `permission_denied` 并展示运行用户权限不足，不伪称网络断开，不自动提权。预算与 ACL/CAS/unknown-ACK 安全策略保留。

## 本轮实际验收范围

`tests_node_files_delivery/run_owned.py --phase <new-unused-name> ...` 创建专属 label 的 `network=none` PG18，清 inherited env，从独占 scratch cwd 跑真实 TCP/FastAPI/PG、完整 HTTP 工件下载、实际安装后的独立 Python Worker 子进程；清理后 inspect 容器不存在。使用现有只读 Python3.13 venv，不装依赖。未做生产访问、生产部署、舰队升级、根授权、Windows 真机、前端重建或全历史恢复。
