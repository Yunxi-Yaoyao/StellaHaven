# 笔记所见即所得与文件导入

## 状态

2026-09-08：开发代码与本地构建完成，未提交、未推送、未部署生产。开发后端服务未重启，因此新增 finalize 路由尚未加载到原有运行中的 dev 进程；正式联调/上线需要加载新后端。

## 实现

- 默认阅览不变；编辑状态可切换所见即所得 / Markdown，编辑偏好保存在 localStorage。
- 所见即所得：Milkdown/Crepe 7.22.1；源码：现有 CodeMirror 6。富文本组件按需加载，不随打开笔记首屏加载。
- 单一 Markdown 正文，继续使用原有草稿槽、乐观锁 PUT 和显式保存边界。切换编辑显示不产生无意义保存；返回阅览会保存，保存失败保留编辑现场。
- 富文本支持基础格式、列表/待办、表格、代码、图片粘贴、标题导航。Mermaid 在富文本中编辑代码，在阅览中渲染图。
- 未修改时原文逐字保留；编辑后复用未修改的顶层块源码。改变的块允许 Markdown 规范化，块间空行/末尾空白不承诺字节不变。
- frontmatter、原生 HTML、不支持的扩展作为惰性原文块显示，编辑它们需切源码。不是完整 HTML 富文本编辑器。Wiki 文本保留，源码模式保留原有双链候选；富文本可输入 [[标题]]，暂未接同款候选菜单。
- HTML 显示净化与 Mermaid SVG 净化分离；严格 Mermaid 模式使用 SVG 文字，避免 HTML 标签容器被净化丢掉。

## 导入行为

- 按钮多选文件与页面捕获拖拽共用导入弹窗。md/txt 一文件一笔记，标题取文件名，同名追加序号，正文内标题不移除，不覆盖旧笔记。
- 列表空白落根级；树节点落其子级；编辑区域弹出明确目标，默认根级，绝不替换当前正文。
- 纯其他文件在编辑区域继续走原有附件；混合 md/txt 与其他文件时，导入弹窗列明不支持项，不偷偷上传。
- UTF-8 严格解码及 UTF-16 BOM；乱码可手选 GB18030；拒绝 NUL。TXT 转义 Markdown/HTML，保留换行语义。
- 每批最多 50 文件、20 MiB；单文件 5 MiB。文件夹/ZIP 导入不支持；Markdown 相对图片保留引用并提示补资源。
- 显式私有/published/工作区/父级；导入开始锁定目标。失败项单独重试，成功项不重复创建；双链同步失败独立重试。
- POST /documents/import/finalize：{workspace_id, document_ids}，逐项验证归属且先全量验证再写双链；不改正文或更新时间。创建接口补父页面同工作区校验与创建时双链同步。

## 验证记录

- `npm test`：HTML/SVG 安全测试 2 passed；Node 富文本/导入测试输出 17 passed（包含父级测试组计数）。富文本测试使用真实 Chromium + Vue + Crepe。
- `npm run test:e2e -- --reporter=line --timeout=20000`：13 passed。真实浏览器渲染实际前端代码，API 使用显式测试夹具拦截，不代表线上数据库联调。
- `npm run build`：vue-tsc + Vite 成功；保留大型 chunk 和静态/动态 import 提示。RichEditor chunk gzip 约 301 kB，按编辑时加载。
- 后端：实际 FastAPI TestClient + PostgreSQL `stella_test_dev`，文档/正文/树/双链/版本/草稿及新增导入共 49 passed，现有 Authlib 弃用警告 1 条。运行前核实数据库为空、可写 primary 且无其他活跃测试；生产/开发正文库未写入。
- 截图为隔离验收账号的测试夹具页面；不是用户生产笔记。桌面自动化已验，用户真机/手机视觉仍需终审。

## 运行与部署边界

- 前端测试需要项目依赖、现代 Node，以及 `/usr/sbin/google-chrome-stable`；完整页面 E2E 需要开发前端 5173 已启动。
- 后端测试按现有 conftest 使用独立测试数据库；不得指向生产数据库。Pod IP 是临时的，运行前重新核查可写 primary。
- 未执行服务重启、git push 或生产部署。部署时前后端必须一起更新。

## 5173 实际反馈修复（2026-09-08 15:30）

- LAN HTTP 的 crypto.randomUUID 不可用导致 ImportDialog setup 崩溃，选文件与拖拽无反馈。改为 localId（getRandomValues，非安全上下文可用；无 crypto 时序号兜底），同修附件占位符。
- 导入按钮 dragenter/dragover 高亮与松手提示；弹窗显示读取和按文件完成数进度、当前文件、目标检查/双链同步/列表刷新阶段。不是虚构字节上传进度。
- STELLA_TEST_URL=http://192.168.1.5:5173 浏览器针对测试 8 passed；包括按钮 OS 文件拖拽、网络等待期间进度可见。
- 用户实机日志证实新建/详情 500 来自 ReadOnlySqlTransaction：旧 pg-rw 把实际副本也标为 primary。用户批准仅开发修复：.env POSTGRES_HOST 临时改 10.42.2.37、POSTGRES_PORT=5432，DB 仍 stella_dev。旧配置备份 /root/.hermes/workspace/stella-dev-db-before-20260908.env；重启 stella-backend 后核对 pg_is_in_recovery=false、finalize 路由已加载。
- 修复后实际用户请求已返回创建201、finalize200、详情200。未改共享 pg-rw 或生产部署；共享入口标签需另行修复，Pod IP 临时直连不具备自动故障切换，Pod 重建后需更新；该本地 .env 不应提交进代码仓库。
- 前端新建使用 POST 返回值立即入列表，不被后续刷新失败阻断。列表和详情请求用序号丢弃迟到返回，读取失败提示。4 条针对回归通过。

## 模块切换优化（2026-09-08）

- App 的 KeepAlive 只缓存 NotesPage（max=1），key 绑定 auth.me.id；切入/切出 notes 不使用先退后进的过渡，其他模块仍走原动画。
- 初次呈现先绘制笔记布局，bootstrap 只等待工作区与文档列表，标签/工作区名称/最近活动独立填充；导航 hover/focus 预加载笔记 chunk。
- 返回保留组件、当前文档、编辑模式与滚动快照；后台刷新列表/正文不清屏，正文返回时再次检查本地是否已编辑。
- deactivated 保存并关闭 socket、定时器、快捷键/resize 监听；activated 幂等恢复。断开前清 onclose，防止卸载后无限重连。
- 切换账号清 KeepAlive 与 notes store 内容/面包屑缓存；旧异步响应以 session epoch/请求序号拒绝写回。
- LAN HTTP 页面测试全部 17 passed；新增场景将后台文档请求延迟 1600ms，仍在75ms恢复同一个编辑器及非零滚动位置（测试机单次测量，不是用户设备性能保证）；标签/最近活动延迟2200ms不阻塞首次正文。账号清理实测通过。
- keepalive/loading针对测试7 passed；TypeScript+Vite build通过。只改前端，5173热加载生效，无后台/数据库额外变更。
