# 显式 `/` 浏览与现役 Linux 节点部署准备（未部署）

## 范围与权限

用户已明确“文件是所有目录 所有linux节点”。这里指当前 Stella 已纳管 Linux 节点，允许按需从 `/` 浏览；不增加机器、不自动递归扫描、不修改真实 policy / files.env、不新注册 PID1 unit、不启动或重启任何生产节点。

`STELLA_FILE_ROOTS` 缺失仍为 `{}`；仅明确配置 `{"system":{"path":"/","write":false}}` 时才存在根。保留原实例 UID/GID，不使用 root 运行 Worker、不增加 capability/sudo、不新增写授权。已有小范围写根必须保持独立，不能把原来的 `write:true` 传播到 `/`。中心仍须给当前已认证 owner、确切 node ID/root ID 对应的只读 grant；示例不是可自动应用的 policy。

请求中的路径仍是 root 相对路径：根目录列表 `path:""`；下钻 `path:"etc"`；不是 `path:"/"` 或 `path:"/etc"`。只有**本地 root 配置**接受绝对 `/`。空根、相对根、NULL、重复分隔符、`.`/`..` 均继续拒绝。每级 dirfd + O_NOFOLLOW；软链接不跟随，硬链接及特殊文件不可作为普通文本/下载/编辑。`/` 只是不再需要遍历根祖先，并未关闭安全检查。

`EACCES/EPERM` 返回 `permission_denied`，界面明确显示运行用户权限不足且未提权，其他路径拒绝仍为 `path_denied`。不能把“从 `/` 浏览”称为“所有文件均可读”；无法读取内容属于 OS 权限边界，不是网络离线。文本预览 256 KiB、流式传输 32 MiB、块 64 KiB、目录预算 2000、排序及中心分页均未修改。POSIX ACL 保真拒绝、CAS、未知 ACK/未知写锁定均保留；不新增删除、递归目录复制或跨设备移动。

## 只读核实的节点清单

来源：外部 `files-root-scope/fleet-metadata-readonly.json`。通过已有 PostgreSQL 容器本地 socket、已有 postgres 身份进行 `BEGIN READ ONLY; SELECT` 指定非凭据列，最后 `ROLLBACK`；没有读取 token/密码/凭据文件。观察时间以 JSON 为准（2026-10-23 UTC）。这只证明纳管元数据，不替代每机实例/权限/PID1验收。

| ID | 节点 | 平台/系统元数据 | 准备状态 |
|---|---|---|---|
| 19 | Stella | linux / Nyarch Linux | 范围确认，实例/运行环境前检待做 |
| 20 | HK | linux / Ubuntu 24.04.3 LTS | 最后心跳仍为 2026-10-14，待恢复；旧 status=online 不代表实际在线 |
| 21 | TYO-AWS | linux / Ubuntu 24.04.4 LTS | 范围确认，实例/运行环境前检待做 |
| 22 | LAX-RACK | linux / Ubuntu 24.04 LTS | 范围确认，实例/运行环境前检待做 |
| 55 | NAS | fnos / Debian GNU/Linux 12 (bookworm) | 实际 Linux 家族，纳入；前检待做 |
| 56 | Shanghai | linux / Ubuntu 24.04.2 LTS | 范围确认，实例/运行环境前检待做 |
| 57 | 5060 | windows / Windows 11 | 排除，本模块不支持 Windows |

共 6 个 Linux 范围节点（其中 5 个观察时心跳新鲜、HK 待恢复），1 个 Windows 排除。版本字符串不代表 Files Worker 已上线。`node_files_root_deployment.example.json` 为非执行性准备清单，`iid/uid/gid` 故意为 null，必须读回原身份再部署，不能用空值替换为 0。现有 source 的 main=0.6.18 仅完整性包工件，字节未变；生产节点主版本仍是其元数据所列版本，本轮未改变。

## 完整包与身份前置条件

本轮新产物：外部 `files-root-scope/build/stella-files-root-scope.tar`。

- 外层 tar SHA256：`19551ee878a6aca6a9978d901195d1ec634f808d536804c0d525c8df3466fd25`
- 内层 canonical release：`05e1854f7d3e1476a997c82d8def28dbb2099b985e2544ccbe58da54e6d4b484`
- node_files.py SHA256：`00b1521ff5be4afbd25967fcb9e1bfb05f64afa302edc69fc955d39b9403b500`

两个 pin 均已重建、闭包核验且重复构建字节一致。不能沿用旧 `1a7008…` / `0384fe19…` 包；也不能仅按 main/module 版本字符串替换。helper 自身 SHA 在同目录 SHA256SUMS，生产仍须通过可信渠道先审核 helper，再交由既有受权管理员运行；不会给文件 Worker root 权限。

部署前必须：父主功能完成 Files API/schema/source ledger 集成及获准迁库；每机读取既有 instance binding/main unit/UID/GID，不创建身份；原 UID 实际探测 Python+httpx；确认唯一 embedded/companion 模式；管理员明确安排真实 PID1 canary及只读 grants；HK 先恢复心跳。当前全部未执行，不把 fixture systemd 的 READY/stop 代签为生产重启成功。安装命令及恢复未知停止的强守卫仍见 [NODE_FILES_LIFECYCLE.md](NODE_FILES_LIFECYCLE.md)。

## 真实验证与边界

外部证据目录：`/opt/hermes-workstation/docs/records/2026-10-23-stella-production-feedback/files-root-scope/`。

- RED→GREEN：显式 `/` policy 原先 `invalid_local_policy`；真实 mount/chroot 的 `/` 浏览原先 `invalid_root`；UID65534 的 EACCES 原先只报 `path_denied`；界面原先未映射权限错误。各阶段独立日志/XML/JSON保留。
- `unit-final2.xml`：60 passed。自有 scratch 绑定进私有 mount namespace 后 chroot 成 fixture `/`；先 drop groups/GID/UID65534，真实 list根/下钻/普通 etc 文件预览和有限下载；拒绝符号链接、硬链接、FIFO、越界路径、空普通文件路径、只读写入；另一个独立显式授权 scratch 根允许 create；权限拒绝与大小/目录预算负控均实际执行。没有遍历宿主敏感目录。
- `BACKEND-FINAL/tests.xml`：86 passed，含原 ACL/CAS/unknown-ACK/完整 lifecycle 停止恢复负控。额外真实独立降权 Worker 的 `/` policy 在原环境白名单后被认证 claim为只读，PG环境不泄漏、不导入 app，拒写 HTTP403，未向宿主 `/` 发文件请求，子进程停止。
- `DELIVERY-FINAL/tests.xml`：3 passed，真实下载完整包、独立安装 Worker/HTTP/PG读写对照。`BROWSER-FINAL/tests.xml`：2 passed，原真实浏览器/草稿生命周期套件。
- `ui-green.json`：4 passed，含权限文案及既有挂载/滚动契约；vue-tsc -b 与 Vite 生产构建实际通过。此处新权限文案测试使用显式模拟错误回执，不冒充 OS 权限浏览器 E2E；真实 OS拒绝由 mount/chroot测试覆盖。
- 首次混合运行 `ROOT-LIFECYCLE` 保留 3 个失败：跨套件共享 fixture 已被编辑的文本破坏 browser 预期，已有 unknown 写锁使后续 create返回409。未清 unknown业务记录、未改产品 guard；分别新建 nonce PG/fixture重跑原套件，以上 clean阶段全部通过。原 Authlib 弃用警告仍保留。

所有 PG container 采用 nonce owner label、network=none、显式 env 白名单并已删除读回。systemd管理是 fixture adapter，不是宿主 PID1；mount/chroot仅为测试隔离，不声称生产 dirfd 能抵抗同等权限敌对进程搬动祖先的竞态。没有生产安装、迁库、授权写入或节点重启。
