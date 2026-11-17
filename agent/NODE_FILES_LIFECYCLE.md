# Linux 文件伴随 Worker：显式安装与更新

## 执行模式与范围

此候选在 `e9f13b9` 基础上提供 **Linux 独立 systemd companion**，不修改 `agent/stella_agent.py`、Linux/Windows 通用 installer、旧 `/agent/script` updater、monitor router 或 main。旧单脚本自动升级仍只升级 main；本组件使用独立、显式批准完整包的 `install/update`。这是已实现的专门授权安装 helper，不是等待通用 owner 接线的 stub；也不是已部署的 fleet 功能。

- 新入口：`agent/node_files_lifecycle.py`。既有 Linux installer 创建并认证实例后，管理员独立选择是否运行本 helper；不运行就没有新服务/目录/roots。
- 只接管已绑定的 `/opt/stella-agents/<iid>`、`/etc/stella-agents/<iid>/instance.json` 与该实例 UID `sta<iid>`；校验既有 main unit、root-owned 私有 `agent.env`、实例/center/node 绑定，不创建账号、不增加 sudo、不改 main unit。
- `stella-files-<iid>.service` 的 ExecStart 使用批准 Python + privateConfig 内 root-owned helper；**不运行 generation 里的 main Agent**，不违反 main 固定安装路径约束。完整包仍钉住真实 main/module 字节，main 仅作完整性工件保留。
- 不向 main 安装相邻 `node_files.py`，拒绝已有 embedded module 或 main `STELLA_FILE_ROOTS`，避免双执行。Worker 每 tick 检查实例身份仍存在且未变化、main 脚本仍存在、未启用 embedded module；失效退出，既有 pending/unknown 写不重新执行。
- 其他平台明确 unsupported；Windows 不安装服务、不报告 roots，也没有 NTFS/ACL 验收。

## 完整产物与 pin

`build` 生成确定性 USTAR，闭合集合为 `package.json`、`manifest.json`、`stella_agent.py`、`node_files.py`、`node_files_delivery.py`、`node_files_lifecycle.py`。`manifest.json` 保持原 main/module version、protocol、platform、size、SHA 契约；`package.json` 另钉住 bootstrap/lifecycle 的每个字节，避免自摘要循环。安装必须同时提供 **tar SHA256 与 canonical release SHA256**。拒绝重复成员、目录、链接、额外成员、缺文件、混包或内容修改，不使用 extractall。

```sh
# 构建只读源码工件，不安装或授权。产物目录由本次任务独占。
python3 -I -B agent/node_files_lifecycle.py build --source agent --package /ABSOLUTE/OWNED/stella-files.tar
```

停止失败修复候选的最终产物及摘要见外部证据 `node-files-completion/lifecycle-stop-fix/build/receipt.json`；旧 `lifecycle/build/receipt.json` 仅是历史包，不含此次停止安全修复。`SHA256SUMS` 同时覆盖独立交付的两个 helper。**必须先从可信交付渠道审核并核验 helper 自身及其相邻 delivery helper 的 SHA**，再以 root 执行；不能先执行不可信 tar 内的 bootstrap 来“验证它自己”。构建与 readback 不修改现有 release 公告。

## 依赖：真实预检，不借用旧 --deps 承诺

本 Worker 必需 Python 3.10+、`httpx`；此次在 Python3.13/3.14 + httpx0.28.1 实际运行。main 的标准库 fallback 不适用。每次激活前，helper **降为实例 UID** 运行明确 `--python` 的 `import httpx`，随后同解释器实际导入 staged main/module，再启动服务。缺依赖或该 UID 无法执行解释器时，不切换 unit/generation。绝不以 root 执行实例提供的 Python，也不隐式修改全局 Python。

部署者可先在另一个 root-owned、无凭据、该 UID 可执行的实例专用 venv 中安装已审核依赖，例如：

```sh
# 模板，不是本轮生产执行记录；先替换 iid、审核解释器/轮子来源。
python3 -m venv /opt/stella-file-runtimes/<iid>/venv
/opt/stella-file-runtimes/<iid>/venv/bin/python -m pip install 'httpx==0.28.1'
# 离线场景用已审核 wheelhouse + --no-index --find-links；缺 ensurepip 则先安装发行版 venv 包。
```

不要把 `UV_PROJECT_ENVIRONMENT` / `VIRTUAL_ENV` 指向共享运行环境；不要用旧 installer `--deps` 的提示输出替代此流程。可使用已有、权限允许的解释器，但依赖环境的安装/补丁管理仍须独立明确批准。

## 实际 lifecycle 命令

以下是生产操作**模板**，此次只在自有 fixture 执行对应真实逻辑；不代表已获节点部署授权。helper 和相邻 delivery helper 放在 root-owned、非 group/world 可写路径，先核 SHA。所有凭据从既有 privateConfig 读取，绝不作为 argv 参数。

```sh
python3 -I -B /APPROVED/node_files_lifecycle.py install --instance <iid> --package /APPROVED/stella-files.tar --package-sha256 <tar-SHA> --release <canonical-release-SHA> --python /opt/stella-file-runtimes/<iid>/venv/bin/python
python3 -I -B /APPROVED/node_files_lifecycle.py status --instance <iid>
# 新完整包必须重新审核两个 pin；不会自动追 latest 或版本公告。
python3 -I -B /APPROVED/node_files_lifecycle.py update --instance <iid> --package /APPROVED/next.tar --package-sha256 <next-tar-SHA> --release <next-release-SHA> --python /opt/stella-file-runtimes/<iid>/venv/bin/python
python3 -I -B /APPROVED/node_files_lifecycle.py rollback --instance <iid>
python3 -I -B /APPROVED/node_files_lifecycle.py stop --instance <iid>
```

- root installer 沿用 config 父目录 `.<iid>.lock` 与 main `.update.lock`；后者首次创建即保留实例 UID 归属，不使 main updater失去锁文件权限。Worker 另持专属 `.worker.lock`，防同实例双 companion。
- root-owned helper code 位于 privateConfig `files-runtime/<tarSHA>`；代码完整写入临时目录、fsync 后才原子 rename。实例 UID 不能替换 root 将来执行/管理的路径。`umask077` 下仍明确设置可遍历的0755 runtime目录与0644无凭据代码文件。
- generation/current 位于实例私有 `code/files/releases`，由**实例 UID 子进程**创建、校验、切换与恢复。所有 root-owned unit/state/credential 写只发生在 root-owned config/unit 祖先之下。
- `Type=notify`：Worker先真实 GET `/agent/identity` 核 center/node，再完成一次真实 `/agent/files/claim`，才发送 `READY=1` 与对应 release 的 STATUS。只有 process spawn/is-active 或版本字符串不算就绪。中心缺 files API/schema时启动失败/超时并恢复旧完整包；不是把当前无 files 的 repair0622 当目标中心。
- unit 不含 sudo/CAP_NET_RAW；`NoNewPrivileges=yes`、空 CapabilityBoundingSet、UMask0077。EnvironmentFile 复用 root600 agent.env；仅允许服务管理器把凭据传给相同实例 UID，文件 Worker不直接读取该文件，也无PG/其他服务环境。
- 状态读回 full manifest/module integrity、当前 pointer、unit SHA 和 systemd状态。`authenticated_ready` 仅代表此存活进程已完成启动认证，**不是中心持续在线探针**。坏模块状态不显示完整性成功，重启拒绝 fallback。
- 相同完整包/解释器/active-ready 重复安装不重启；stop 会 disable+stop，要求命令返回零且读回 inactive/MainPID=0。只有已保存的前一完整包可 rollback；失败启动先确认候选已停，才恢复旧 pointer/unit/state 和原 enabled/active 状态，再真实启动旧 ExecStart并读回。
- stop 非零、超时、读回未知/仍active/MainPID非零时，不删除或恢复 pointer/unit/state；root600 `files-state.json` 持久保存 `recovery_unknown`、candidate完整双pin/runtime/unit摘要、原binding/完整state/unit/pointer/管理面状态。状态明确 `recovery_unknown:true`、`roots_granted:null`、不ready；install/update/rollback不得自动重启该不确定实例。必须用审核后的修复版管理helper再次显式 `stop`：核绑定、root-owned unit字节摘要与管理器FragmentPath后，仅停止该unit，不对未知数字PID发送信号。确认停止后恢复原元数据并保持disabled/inactive，**不重启旧业务、不重新入队unknown写**；随后是否重新安装是独立管理员决定。恢复中其他步骤失败仍保留记录，需人工核清，不伪造成功。
- 无state但仍有unit/active/非零或未知MainPID/FragmentPath时，status和stop明确拒绝orphan/foreign/unknown，不返回 `installed:false, roots_granted:false`，更不自动接管或杀进程。unit字节或管理器FragmentPath不匹配时，恢复stop也拒绝，保留现场。
- 全局 main 卸载前先运行本 helper `stop`；本轮没有篡改旧 root uninstall helper。即使实例身份被删除，运行中 companion 也在下一 tick 前退出；如操作期间已有写获准，仍须沿现有 unknown/reconciliation 契约处理，不宣称撤销已开始的操作。遗留停用 unit/runtime的删除由明确维护动作处理，不自动扫未知目录。
- 这不是断电原子跨 systemd/多个文件的事务：SIGKILL/断电中途可能留下指针/unit/state不一致或原 ReleaseStore锁目录；不要自动打破锁。确认无旧进程后，用已审核完整包重装恢复；无法核清时保持停用。未实现 host级断电恢复 journal。

## 默认权限与父集成边界

首次 `files.env` 只有 `STELLA_FILE_ROOTS={}`。不默认 `/`、home、整盘、挂载目录；write省略即只读。现在支持明确配置 `STELLA_FILE_ROOTS={"system":{"path":"/","write":false}}`；这是供部署者审核的 JSON 值，写入 systemd EnvironmentFile 时需按既有双引号转义规则编码，不是本轮执行命令。Worker 原有环境白名单保留该值，清除 PG/代理/其他服务环境，不改变实例 UID。此 helper 不提供授根命令，也不修改中心policy。真实授权后的生命周期仍由管理员显式 stop、调整 root600 files.env、install/update重启；中心 owner/node/root-ID grant 与本地绝对root两端均满足才开放；写还需两端显式 `write:true`。本轮没有执行上述生产动作。

最新范围已明确为当前纳管全部 Linux 节点、从 `/` 按需浏览；没有新的写授权、root UID、capability 或递归扫描许可。示例和逐节点前置检查见 [NODE_FILES_ROOT_SCOPE.md](NODE_FILES_ROOT_SCOPE.md)。所有实际根目录文件操作仅在自有 mount+chroot synthetic `/` 中以 UID65534 运行；额外真实独立 Worker 只做显式 `/` 的认证/claim/read-only拒写，不向宿主 `/` 发任何文件请求。

无本轮新增 HTTP API。父需把 e9f13b9 的 `/agent/files/release` 与 `/agent/files/release/{identity}/{name}` 及原 files 路由按主功能源码谱系统一登记 source/operation/document ledger；本分支不代签。main capability/schema没有改为“伴随已接”：真实能力仍来自 FileAgent protocol1 roots/seen。建议父若展示执行模式，另显式设计 DTO `execution_mode=linux-companion` + 已认证 `release/module_sha256`，未知/旧 main应保持未知，不能由main版本号推导。迁库、完整主树集成和生产 canary仍是独立 gate，不是“只等用户授根”。

## 验收边界

owned runner 创建 nonce PG18/network-none，env白名单，真实HTTP与独立 ExecStart Worker；systemd管理命令使用**fixture adapter**，不是宿主 PID1。额外 private mount namespace仅将自有scratch映射 `/mnt`，真实以UID65534 drop groups/gid/uid完成stage/worker/notify，证明凭据root600对Worker不可读。没有创建宿主账号、真实unit或触碰生产Stella。不得将这份证据改称真实systemd重启、Windows或fleet验收。历史浏览器闭环未重做；一次误纳入浏览器套件因本树缺前端依赖失败保留在lifecycle历史证据中，不能算UI通过。
