# 备份中心前端候选验收

## 范围与状态

入口 `/settings?section=backups`，设置原生独立「备份与恢复」页。只有 `settings` / `all`；不新增保留参数、单篇树、手动豁免或外部复制。固定两份成功 ZIP 的清理完全由后端决定，前端不乐观删除旧档。

已实现冻结 `/operations/backups` 的 GET / PATCH config / POST backup / download / verify / restore / DELETE 调用。`settings` 恢复与删除均有精确文件名二次 modal；`all` 只展示真实 HTTP409 `maintenance_required` 中的离线指引，绝不在网页执行命令或宣称全站恢复完成。

**这是前端候选，不是生产交付。** 真实后端 ZIP 内容、PG 恢复、资源字节、计时器/HA/权限与大档下载仍由父集成后联测。浏览器验收使用真实 Vue SettingsPage + Vue Router + 当前 CSS/主题及 loopback HTTP fixture；不连接生产，不把 fixture 的成功状态当后端恢复证明。

## 已验证

- 默认读取只有 GET，不创建或开启备份；两个手动按钮只发对应 scope，互斥防重入，不暗中开启计划。
- 目录明确为服务器路径，显式应用；每日/每周、星期 Monday=0、时间、IANA 时区，带 `expected_revision`。失败保留输入，新输入不被迟到 PATCH/readback 覆盖。
- 写入 ACK 后读回再确认；读回失败与不确定写入只允许 GET 恢复。409 冲突须先成功读取，再明确重新应用或使用服务器值。
- 列表记录、时间/大小、按需 SHA-256、校验与恢复证据区分；202 作业按原 job ID 回读，旧任务成功不能冒充新恢复完成。仅 queued/running 轮询。
- AbortSignal + 独立取消 race + JSON/下载预检30s期限；ZIP长传输使用HEAD管理鉴权预检后交由浏览器原生GET流式下载，不在JS拼接Blob、不套30秒整包上限；UI仅提示已交由浏览器，不冒称下载完成。卸载/KeepAlive/管理锁/会话代次清理，迟到成功与错误均受ownership fence。
- 401 重新登录提示；403 管理解锁入口可用，解锁后只读、不自动重放写入。目录不可用真实展示节点和原因，仍可应用修正目录。
- modal Tab/Shift+Tab/Escape、关闭归还焦点；离线指引出现后焦点移入 pre，Escape 仍可用。
- A/B 全局主题、真实 393×852 模拟手机视口、桌面与 200% zoom，无水平溢出；真实点击/键盘/tap 与文件下载事件。未做真机验收。
- 新增 `backupClientPreferences.ts` 的精确 allowlist、严格验证、只读采集、子集恢复/逐键读回/失败回滚；详见 `backupClientPreferences.audit.md`。**尚未接入 HTTP / 所有设备同步**，UI 明确提示本机偏好尚未纳入当前备份。
- 保留原设置功能；仅从性能页移除被新备份页替代的只读健康挂载，旧 `BackupHealthPanel` 和旧 API/测试文件未改。

## 执行证据

绝对证据根：`/root/.hermes/cache/scratch/stella-backup-center-frontend-20261017/`。父任务应在 scratch 清理前归档所需日志/截图。

- 15 份 `*-RED.log` 与对应 GREEN 日志，按默认→计划→手动→校验→恢复/删除→下载/403→transport→竞态→tab/lifecycle→失败恢复→记录→本机偏好读取→本机偏好恢复→job/focus→401 的垂直切片落地；保留未通过的首轮日志。
- 新增 4 份 Vitest 文件共 58 项：组件 30、transport 3、原生设置集成 3、偏好 22。
- `vitest-all-final.log`：91 文件 / **893 tests passed**。包含原设置、认证、SMTP、网站、导航、笔记、状态等回归。`shell/appearance.test.ts` 输出一条 Vue Router 空路径 warning，未改其他 owner 的测试。
- `build-final.log`：`vue-tsc -b && vite build` 实际 production 构建通过。输出到证据根 `dist/`；保留 notes 动态 import 与 chunk-size warnings，未调整预算掩盖。
- `full-suite.log` 保留最初 `npm run test:full` 的 node 阶段两项失败：auto-directory 的 2500ms 冷启动超时、静态服务器在工作树 `dist` 不存在时断连。未改测试断言/超时。原 native 测试串行重跑 `native-serial-except-static.log` **73/73 通过**；静态服务器/测试精确源码校验一致，在 scratch 指向本次实际 production dist，`static-dist-recheck.log` **1/1 通过**。不得把原命令首轮写成全绿。
- `browser-report.json`：真实浏览器版本、commit、dirty 状态、源码 SHA-256、全部 HTTP 请求、下载 ZIP hash、截图绝对路径。预期故障 403/409/422 单独记录；其他 runtime errors 必须为空。

主要真实截图（报告列全量）：

- `desktop-A-default-off.png`
- `desktop-B-default-off.png`
- `desktop-A-weekly-plan.png`
- `desktop-A-directory-error.png`
- `desktop-A-settings-restore-modal.png`
- `desktop-A-maintenance-cli.png`
- `mobile-393-A-default-off.png`
- `mobile-393-A-viewport.png`
- `mobile-393-A-restore-modal.png`
- `desktop-B-200percent.png`

## 可重复命令

cwd 为当前候选 `frontend/`。固定 Node23，并清理继承的 NODE_ENV（不要将 test 模式传入 production build），不安装或修改共享依赖。

```sh
export PATH=/root/.local/share/fnm/node-versions/v23.11.1/installation/bin:$PATH
env -u NODE_ENV node node_modules/vitest/vitest.mjs run --config vitest.settings.config.mjs
env -u NODE_ENV node node_modules/vitest/vitest.mjs run --config vitest.full.config.mjs
env -u NODE_ENV npm run build -- --outDir /root/.hermes/cache/scratch/stella-backup-center-frontend-20261017/dist --emptyOutDir

env -u NODE_ENV \
 HOME=/root/.hermes/cache/scratch/bc-home TMPDIR=/root/.hermes/cache/scratch/bc \
 BACKUP_EVIDENCE_DIR=/root/.hermes/cache/scratch/stella-backup-center-frontend-20261017 \
 BACKUP_CHROME=/opt/google/chrome/chrome \
 node src/modules/settings/backupCenter.browser.mjs
```

短 scratch HOME/TMPDIR 需先建好；长 TMPDIR 导致 Chromium singleton Unix socket 路径超限的首轮 SIGTRAP 记录已保留。没有改系统浏览器、共享依赖、后端、部署、inventory、Studio 或生产会话。
