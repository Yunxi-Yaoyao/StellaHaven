# Stella shell 按需加载：严格 TDD 与受控构建/浏览器对照

## 范围与结果

基线 `37aabbb`；工作分支 `perf/shell-lazy-20261006`。只修改 App、公开路由启动和命令面板接口；未修改 `frontend/src/modules/settings/*`、`stores/navigation`、Website 组件、API、生产配置、Live2D 模型/参数或 `main.ts`。

- 命令面板：轻量 shell 保留全局快捷键和 `stella:command-palette` 事件，首次意图才导入面板及其静态 QuickRecordDialog 依赖。保留 `.command-palette-root` 轻量集成标记，避免旧 E2E harness 误判未集成而重复挂载。
- 首次慢加载期间的 Escape、连续两次 Ctrl/Meta-K 可以撤销待打开状态；加载后由原组件监听器处理键盘/事件，wrapper 不重复处理。登出卸载监听器。
- 背景图库首次打开才导入，关闭后保留实例，避免清掉原有草稿/预览状态。原组件 immediate watcher 仍处理首次打开。
- 全局 SettingsPanel 原本只负责旧主页齿轮跳转：App 接管小型 watcher，集中设置页中的 embedded 外观表单原封不动。
- 仅选中的**公开路由代码**与 `/auth/me` 并发下载；渲染和重定向仍等待原认证 guard。未登录私人路由不预取，并保留 `/login?next=...`。

## TDD 证据

先运行失败测试，再修改对应代码，原始输出在本目录：

| 行为 | RED | GREEN |
|---|---|---|
| 未打开命令面板不导入 | `palette-red.log`：加载计数 1 而非 0 | `palette-green.log` |
| 未打开背景图库不导入 | `background-red.log`：加载计数 1 而非 0 | `background-green.log` |
| 齿轮跳转不导入外观表单 | `settings-red.log`：加载计数 1 而非 0 | `settings-green.log` |
| 公开路由与 auth 并发 | `router-red.log`：auth 未完成时 Home 导入计数 0 而非 1 | `router-green.log` |
| 保留全局集成标记 | `marker-red.log`：缺失标记 | `shell-final.log` |

最终专用单测 **8/8**。原有 Markdown/notes、背景播放器、server 状态、auth、performance、low-config、settings 测试加上新单测，合计 **90 个通过**；逐套计数见 `verification-summary.json`。不将原始 RED 的失败算作最终回归。

## 实际构建与导入图

两套使用相同 lockfile 和依赖内容，基线由 git archive 提取到 scratch，依赖最终复制为独立目录；独立 dist/构建缓存，最终构建顺序执行，无基线源码修补。两套 `npm run build`（含 vue-tsc）及带 manifest 的 Vite 构建均成功。`artifact-digests.json` 绑定实际源文件/manifest/JS 摘要，lockfile、Vite 配置、main.ts 摘要一致。

| 指标（字节） | before | after |
|---|---:|---:|
| entry 静态导入闭包 | 173,039 | 156,679 |
| 全构建 JS 总量 | 5,297,373 | 5,300,402 |
| 冷首屏实际请求 JS 解码量 | 194,572 | 174,131 |
| 冷首屏 JS 转移量（含浏览器估算响应头） | 80,511 | 72,203 |

冷首屏 JS 解码量减少 **20,441 字节 / 10.51%**。总构建 JS 增加 3,029 字节：这是切分/轻量 wrapper 的开销，不声称全包变小。

实际请求图：before 首屏包含 CommandPalette 与 QuickRecordDialog；BgManager/SettingsPanel 的首屏成本在 entry 内，不能按文件名漏算。after 首屏不请求 CommandPalette、QuickRecordDialog、BgManager 或 servers chunk；backgroundMedia 改为 Home/BgLayer 的必要共享 chunk。第一次打开面板实际新增请求仅 CommandPalette、QuickRecordDialog；打开外观设置后才请求 SettingsPage、Dropdown、servers、integrations，背景图库再请求 BgManager。完整 manifest 与资源列表见 `browser-results.json`，没有凭名字推断服务器 chunk 首屏下载。

## 正常缓存真实 Chromium 对照

Chromium **140.0.7339.186**，1440×960、DPR=1、zh-CN、Asia/Shanghai、Live2D/粒子固定关闭（代码未改）。每版本 5 个新 context 做 cold，再用相同 context reload 做 warm；版本顺序交替，共 **20 次导航**。初始页是 `/`。内容 ready = 主页标题可见且侧栏显示已验证 synthetic owner，networkidle 后另采完整资源表与稳定 DOM。

**严格本地 HTTP fixture**：loopback 同源，无后端导入、无 proxy、无生产请求、无真实登录或数据库；API 固定 120ms、静态固定 40ms，未知 API/写方法 fail closed（只允许 synthetic activity）。静态 gzip + immutable，HTML no-cache、API no-store；真实本地 WS handshake。不使用 `context.route` 或 CDP Fetch，不把禁缓存功能测试当暖缓存。

| 5 样本中位数 | before | after |
|---|---:|---:|
| cold 内容 ready | 513.4 ms | 492.4 ms |
| warm 内容 ready | 296.8 ms | 294.1 ms |
| warm JS 转移量 | 0 | 0 |
| warm JS 缓存命中 / 请求数 | 11/11 | 10/10 |

本地内容 ready 有运行间噪声，暖缓存差距很小，**不能据此宣称稳定生产延迟收益**。不与父任务提供的公网 cold=3461ms / warm=994ms / SPA=828ms 直接相减。这轮能确定的是非必要初始 JS 减少和公开页面的串行下载解除。

实际 Performance 时序：before HomePage 请求均在 auth responseEnd 后开始；after 每次均提前约 122–124ms，与 auth 重叠。20 次 `/` 导航中每次 `/auth/me`、`/navigation` 均只有 1 请求，未增加重复 bootstrap 请求。

## 功能与视觉验收

实际构建运行验证通过：首次快捷键；加载中 Escape；Ctrl toggle；Meta-K；外部打开事件；远端 metadata 搜索；方向键+Enter；快捷记录打开/输入/取消；主页齿轮跳转；背景图库打开/关闭/再次打开。没有浏览器 pageerror/console error、未知 fixture 请求或跨源请求。快捷记录保存/API 写入与真实后端、生产路由等不在本轮验收范围。

- 稳定 DOM：sidebar 宽 232；main x=232、宽 1208；daybreak y=0、宽 1208，无 padding/layout 改动。
- 视觉截图：`before-home.png`、`after-home.png`、`after-palette.png`、`after-background.png`。面板完整在 viewport 内。
- 像素对照只覆盖两个静态区域：侧栏导航 116,928 像素、标题 29,890 像素，均 **0 / 0 改变**；不宣称动态唱片、进度条或整屏逐像素相同。

## 已知边界

- 原有 build 的 notes API ineffective dynamic import / >500KB chunk 警告仍在；背景单测的 router injection warning 在基线也复现，见 `baseline-background.log`。没有为消警告改动用户功能。
- Node 23 的 type stripping 实验警告及 npm 的既有依赖安全提示没有在本轮扩大修改范围处理。
- App 与 NavigationSettings 的直接 navigation-section 启动可能同时调用 `loadNavigation`，这是静态调用图风险，非本轮 `/` 实测重复。该 shared loader 属于其他 child，未擅改 API/navigation；若需要合并请求须由该 owner 处理。
- 未部署、未 push、未操作 Studio 会话/任务、网络/HA/数据库或 Live2D 角色参数。

## 复现

先在独立基线目录提取 `37aabbb`，安装相同 lockfile 的依赖（或独立复制完整 node_modules，不共享构建缓存）；两套分别在 frontend 执行：

```sh
npm run build
npm exec -- vite build --manifest --outDir /root/.hermes/cache/scratch/stella-shell-perf-before-dist --emptyOutDir
# after tree 相同命令，outDir 改为 stella-shell-perf-after-dist
NODE_ENV=test ./node_modules/.bin/vitest run --config vitest.shell.config.mjs
node tests/shell-perf-browser.mjs \
  /root/.hermes/cache/scratch/stella-shell-perf-before-dist \
  /root/.hermes/cache/scratch/stella-shell-perf-after-dist \
  ../docs/perf
```

不要启动默认 Vite dev/preview 的生产 proxy，也不要将 fixture 数字当生产实测。
