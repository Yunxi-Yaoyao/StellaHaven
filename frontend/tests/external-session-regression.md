# 外站页面同用户巡检清空回归

基线：`bb899d788289675f7580d9f0c379cad29886fc47`。

## 根因与最小修复

`ExternalModulePage.vue` 的 `watch(() => [auth.me?.id, auth.sessionGeneration, auth.sessionClosing], ...)` 每次重算都返回新数组。`fetchMe()` 每 30 秒替换同用户的 `auth.me` 对象，触发 getter；虽然三个标量不变，数组引用已变，清理回调仍无条件取消请求并清空 `url/website`。加载中连接被取消，完成后的 iframe 被卸载，缓存返回也无法恢复被清除的内容。

改为 Vue 多 source watcher，逐个比较 ID、sessionGeneration、sessionClosing，保留 `flush:'sync'` 和原清理逻辑。没有更改 auth、管理授权、URL/来源校验、页面文案或自动重连策略。

`ExternalModuleCache` 的同用户重算只重新过滤/更新 active entry 的 used 值；真实浏览器验证 DOM、输入和 LRU 淘汰未丢失，故没有修改。隐藏的在途加载仍取消，重新进入保持暂停；现有「重新连接」可恢复，但不会自动获取或重试管理权限。

## 浏览器 RED → GREEN

测试文件：`e2e/external-session.spec.ts`；配置：`playwright.external-session.config.ts`。

使用真实 Vue App / Router / Sidebar / auth store、bundled Chromium、独占 loopback Vite（复用 `vite.mock.config.ts`，无 proxy、不复用已有 server）。HTTP API、目标 iframe、WebSocket 均显式 mock；未知请求中止并令测试失败。当前 `/website-settings/check` 返回完整契约，不通过缺 fixture/404 制造故障。

在原 watcher 上运行：

```sh
NODE_ENV=development \
STELLA_SESSION_ARTIFACTS=/root/.hermes/cache/scratch/stella-external-session-20261007/red-final \
node node_modules/@playwright/test/cli.js test --config playwright.external-session.config.ts
```

实际结果：**14 tests，8 failed / 6 passed，exit 1**。失败均为应存在的 iframe/输入/额度标题被清除；每项 `unknownRequests=[]`、`pageErrors=[]`。此前先独立执行已加载场景，确认 RED 1 failed，再作最小修复并确认 GREEN 1 passed；扩展覆盖后在原 watcher 上复跑上述最终 RED。

恢复最小修复后，同命令仅替换 artifact 路径为 `green-final`：**14 passed，exit 0**。所有测试的未知请求与浏览器 pageerror 仍为空。

覆盖：

- 已加载页面：keep_alive=false / true，同 UID 对象替换仍保留相同 iframe 节点、输入；仅一次 launch、一次 frame 请求。
- 加载中：分别暂停 metadata GET、地址 check、launch POST、iframe 响应；fetchMe 不取消、不重发。
- 侧栏「笔记 → 额度」进入，**真实等待 31,007ms**，App 30 秒巡检实际调用 `/auth/me`；额度卡片/输入保留，再「笔记 → 额度」仍保留。未用 fake clock 或手动 fetchMe 替代此项巡检。
- 换用户、同 UID 显式新登录、同 tick 退出/登录，均销毁旧 active/hidden iframe；旧输入不复活。
- 慢 logout 响应前立即清空，并阻断在途配置请求的迟到 launch。
- 隐藏在途缓存页返回后，仅明确点击才重连；无自动管理授权。受保护 launch 的 403 只弹现有授权框，取消后不重试、不提交密码。
- 同用户多次巡检保留 hidden iframe 与原 LRU 顺序。

持久证据目录（不提交大体积 trace）：
`/opt/hermes-workstation/docs/2026-10-07-Stella-access-fix/frontend-session/`

- `summary.json`：程序化枚举测试、结果、请求记录摘要、真实等待时长。
- `red-final/browser-results.json`、`red-final.log`、失败 trace/截图。
- `green-final/browser-results.json`、`green-final/browser-artifacts/*/quota-after-watchdog.png`。

## 其他验证

- 全部 **10 个 Vitest config**：65 次执行；按文件/fullName 去重 **62 个测试全部通过**（BackupHealthPanel 在两配置重复 3 项）。JSON 和日志在上述证据目录 `unit/`。
- `node node_modules/vue-tsc/bin/vue-tsc.js -b`：exit 0。
- 新增测试/配置单独类型检查：`node node_modules/typescript/bin/tsc --ignoreConfig --noEmit --skipLibCheck --types node --target es2022 --module nodenext --moduleResolution nodenext e2e/external-session.spec.ts playwright.external-session.config.ts`：exit 0。
- `node node_modules/vite/bin/vite.js build --outDir /root/.hermes/cache/scratch/stella-external-session-20261007/build`：exit 0；保留 chunk 大小和混用动态/静态 import 警告，未扩大修复范围。
- node_modules 使用逐包 symlink 的独立 overlay，不共享 `.vite/.cache/.tmp/.vite-temp`；没有覆写基线 worktree 的依赖缓存或 dist。

未执行生产/远程请求、部署、后台变更或带生产/LAN地址的历史 E2E。本结果是前端隔离回归证据，不替代父任务的最终整合部署验收。
