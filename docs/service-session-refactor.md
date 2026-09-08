# Stella 外部服务与会话整顿（2026-09-08）

## 范围及当前状态

第一批开发实现完成，未提交/未推送/未部署生产。此前背景三档质量 WIP 同在工作树，不能被覆盖。生产仅已修本机 agent 上报入口，并新增只绑定 WireGuard 内网的 OpenList 转发。

## 已实现

### 外部服务连接

- 移除网盘/图库的 Docker 环境挡板和安装/启停/更新API；OpenList、Immich原实例/数据不变。
- 连接配置存在 AppConfig（external_drive_connection / external_gallery_connection），管理员可修改/测试；浏览器URL、可选上游URL、OpenList是否同源反代、手动登录或管理员专用Token、Immich既有OIDC、备用域名入口。普通用户不返回管理员Token，GET配置仅has_token，密码字段留空保留。
- Token模式缺凭据拒绝保存；测试区分认证拒绝、路径不存在、超时、响应类型错误；HTTP通不等于iframe认证已通过。
- OpenList反代不转发Stella cookies、Bearer鉴权、X-Forwarded头，保留流式、Range和重定向处理；保留原主题注入。原OpenList的base_path=/drive/openlist；其他path服务建议直接浏览器入口，不伪称子路径重写普遍支持。
- 真实开发配置上游 http://10.66.0.2:12544/drive/openlist；host systemd-socket-proxyd转发至127.0.0.1:5244，仅WG绑定，无Docker socket进Pod。
- 原服务Token仅初始化迁入时使用宿主CLI读取，应用运行时不再依赖docker exec。

### 会话

- 无数据库迁移：remember=true创建后绝对30天；否则last_seen闲置30分钟。access/refresh和WebSocket入口统一检查，到期不复活；refresh不续活动时间。
- 未记住的两种Cookie都是会话级；记住的cookie最长不超过服务端剩余有效期。
- 显式 /auth/activity：浏览器可见时可信输入事件触发（每分钟最多一次），后台巡检不续命；CLI需在真实操作时调用并在finally logout。旧CLI不调用者30分钟后到期，这是明确兼容边界。
- 同一有效cookie重新登录只撤销该会话，不按IP/UA合并其他设备；logout可用access sid兜底，前端失败不假装退出。
- 有效会话按页20条，历史默认折叠且分页；文案当前会话/最近活动，不冒充当前在线。邀请与用户列表保留。
- 历史记录不删、不批量踢。仅撤销本轮一次502遗留的精确测试会话b025ba81-b45a-4d30-99b9-9d24d9a16ec3，并回读true；其他验证均logout200及随后401。

### 服务器工具第一批

- 主机stella-agent凭据核对属于生产node19，积压待执行任务0后，将URL从开发12031改为https://stella.xiya.live并重启；生产最新心跳已恢复online。
- 保留版本安装事实，离线/心跳超过120秒灰化，任务按钮不再只按installed判断；监控无新样本/源离线显示unknown。
- Docker页区分缓存/时间、可执行节点及真实409错误；组件安装按本次task id等待，有截止和卸载取消。
- 各任务回传/进度统一校验token、节点归属、iperf角色、任务当前状态、允许终态，拒绝其他节点覆盖结果。WebSocket补文档/工作区归属和会话过期检查。
- 生产只读Docker扫描task28已实际201→done，42容器，error=None，验证会话已退出。

## 验证证据

- 后端 tests/ + tests_isolated/：188 passed、14 subtests（独立测试数据库stella_test_dev和私有SQLite，生产笔记未写）。老测试按真实任务领取顺序更新，非法文档WS改为握手拒绝预期。
- 前端认证5tests、服务器状态2tests；新完整页面连接字段/历史折叠2tests；原笔记/背景相关测试继续通过，vue-tsc及Vite build通过。
- 实际5173 OpenList iframe显示原目录，连接配置所有字段/原Token验证通过；Immich健康200、登录页可加载、OIDC跳转发起。

## 未完成/阻塞

1. **Immich 公网完整UI未通过**：多次浏览器追踪确认/_app/immutable多个JS返回502，HK nginx对应connection reset；frpc@hk报connection write timeout并重新登录。不是Docker检测或缺连接字段。此隧道同时承载其他服务，未擅自重启/改传输参数；需要独立公网链路修复授权。UI提供新窗口入口但不能保证同域公网502可用。
2. Prometheus只读适配器与真实试点已落盘（docs/prometheus-pilot.md），未切换Stella生产/开发图表数据源。实际采样15秒不等于原网卡5秒；需5秒试点与流量/95口径对账再切，旧采集未停。
3. 统一轮询只完成组件安装/Docker及共享状态；其他工具的长任务队列、心跳线程解耦与统一持久结果需要后续批次，未修改agent脚本版本。不能声称“所有工具已统一”。
4. 本批代码、背景三档仍未push；生产新会话策略/外部服务UI须部署后再验。开发后端已获授权重启。


## 后续收尾（2026-09-08 19:55）

- 用户确认 Immich 直连正常，撤销“必须修FRP才能继续”的判断，本轮没有改FRP。新登录态的iframe实际能到Immich登录页，但自动OIDC发现间歇fetch failed/500，未验证全新登录到照片墙；不能据此宣称现有用户图库不可用。手动模式现在明确使用/auth/login?autoLaunch=0，避免设置写manual却仍强制autoLaunch。没有改Immich自身设置。
- 新 taskWait.ts 统一有限任务等待：Docker操作/扫描/日志/inspect、组件安装、firewall/PBR、MTR及命令等待；总期限/单请求期限/有限错误重试/卸载或切节点abort，保留done/failed/cancelled区别。长期图表和iperf进度推送未改成此轮询。
- agent源码0.6.4：tasks与probes各单飞后台线程，主循环继续采样。无无限任务排队；自动更新只在两条lane空闲时运行，避免新引入的更新中断长任务；iperf异常回包保留server/client角色，适配后端归属校验。线程退出有限等待，并不能强制取消现有子进程/保证崩溃回包不丢。源码未部署到/opt/stella-agent，生产仍0.6.3。
- Prometheus管理员对账API：GET/PUT /config/prometheus；GET /nodes/:id/metrics-comparison。显式节点job/instance映射，不收任意PromQL。节点详情“操作→指标对账”有配置/对比面板，保存保留其他节点映射，不切换旧图表、不停旧采集。当前开发配置enabled=false，必须映射真实节点才启用；实际15s vs原5s仍须单独试点调整和对账。
- 最终后端226passed+20subtests；前端19条页面E2E通过，服务器wait/state/对账5tests通过，认证5tests通过，vue-tsc及Vite build通过。开发服务重启并readback /config/prometheus、drive/status、gallery/status均200，脚本logout200随后me401。
- 本批背景质量、会话、外部服务、工具/agent新源码仍未push或部署生产；只有此前明确批准的agent URL修正和WG内网OpenList桥已运行。生产用户界面不能假定已更新。


## 20:20 用户纠正后的简化与 OAuth 根因修复

- OpenList固定经Stella后端代理，仅需`service_url`（后端可达完整OpenList地址）、登录方式与Token。去掉浏览器入口/use_proxy开关/新窗口按钮；iframe固定同源/drive/openlist路径由应用生成。旧已存Connection内部结构兼容读取，GET新UI只返回service_url/auth_mode/has_token。
- 保存按钮名改“保存并应用”，测试仅验证输入不保存。Token默认只显示已配置状态、留空不修改；管理员显式POST /drive/connection/token可查看，响应no-store且非管理员403。
- 重连空白根因：frameReady=false但相同src未触发load，opacity永久0。现在更换iframe key强制新加载；失败保留旧iframe并显示真实错误，加载超时有提示。
- 图库说明不常驻，只在连接异常error时出现。跨源iframe内部错误受同源策略限制，不能声称父页已识别所有内部OAuth失败。
- **真实OAuth根因已查明并修复**：Immich实时issuer是https://stella.yunxi.life（旧IP149.28.93.206连接超时），不是之前误以为的xiya入口。精确openid-client复现UND_ERR_CONNECT_TIMEOUT；容器内xiya发现+JWKS+client验证均成功。
- 用户批准后通过Immich官方PUT /api/system-config只改oauth.issuerUrl→https://stella.xiya.live，GET递归diff确认只此字段变化。旧配置含secret备份/root/.hermes/private/immich-system-config-before-20260908.json（600）。FRP/DNS/容器重启未操作，原client ID/secret/账号绑定不变。
- 全新浏览器、主站同站iframe测试（只拦截惰性HTML壳，所有认证/Immich请求真实）已自动进入https://immich.xiya.live/photos，原时间线/17.1GiB数据可见、JS异常0；Immich logout200、Stella logout200。LAN IP5173嵌入公网域属于跨站，cookie规则与同域生产不同，不应冒充相同SSO环境。
- 网盘真实目录+重连可见通过；定向后端10tests、前端6E2E、类型检查及build通过。本轮Stella代码依旧只在dev，未push；Immichissuer修正立即生效。
