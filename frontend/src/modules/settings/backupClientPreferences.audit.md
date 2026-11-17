# 账号可移植偏好：已接 HTTP 的受限边界

## 行为

`App.vue` 挂载时启动 `clientPreferenceSync.ts`，只在已登录且未 suspended/sessionClosing 的会话中工作。账号偏好保存不是创建备份；自动备份仍默认关闭，进入页面/登录/保存偏好均不调用 POST backup。

- 首次 GET `revision=0` 且本机归属为空/同一账号：读取真实 home/appearance store 与已审计布局，PUT 后再 GET 确认。不是把缺失 localStorage 当成默认主页。`stella_client_preferences_owner` 是仅本机归属元数据，绝不发送/打包。
- 已有服务器记录：仅在没有待确认本机编辑、且本次读取期间没有新输入时应用；同账号重登录前未确认的输入与读取期间的新输入均保留为冲突。跨账号的空记录使用服务器默认值，不把上个账号的本机偏好播种给新账号。
- 平时真实 store 变化与控件上的精确 signal 做 400ms 合并；没有周期性偏好抓取、Storage monkeypatch 或遍历 origin。相同账号的 auth profile watchdog 刷新不会触发偏好重读。布局 signal 可携带那个控件的单个枚举值，因此设备存储写入失败时也不会错把旧值称为已同步。
- 一个活动请求链：PUT 后 GET；写期间的新输入在成功确认后合并下一次保存。401/403/网络失败停止自动上传，显示持续失败与重试。重试先 GET 对账，不盲重发不确定 PUT。
- 409 只 GET 一次，保留本机输入，明确选择「保留本机偏好」或「使用服务器偏好」，不自动重放。owner/generation/requestEpoch/suspended/closing/卸载均中断旧请求并隔离迟到结果。
- 手动 backup 先等待此设备偏好确认；失败不发 backup POST，重试偏好不会重做备份。定时任务只能读取最近一次已确认的服务端快照，不能读取未同步/离线设备的浏览器。
- 用户确认 settings restore 后暂停上传，直到匹配任务成功/失败/中断的状态回读，再 GET 偏好。新的本机输入不被覆盖；恢复回读失败可仅重试 GET。纯 helper 整体验证、逐项写入/回读，失败尝试整个子集回滚。
- home store 和 appearance（CSS tokens）、背景质量实时应用；其余布局明确提示保存工作后自行刷新，不强制刷新，不导入/改写 notes store、正文或草稿。其他服务端设置页面仍遵循原有读取/刷新生命周期，不能把此提示理解成所有模块配置都已实时重载。

## 精确 HTTP 契约

GET/PUT `/operations/backups/client-preferences` 都使用 `current_user`（单一固定 owner 的既有鉴权），不需要管理提升；主站严格 Host/Origin/CSRF middleware 不变。仅这项纯账号偏好 PUT 放宽，备份创建、下载、校验、删除和恢复仍需 `admin_user`。owner 永远来自会话，不接受请求选择。

GET 和 PUT 成功：`{revision,appearance,customAppearance?,home,ui}`；PUT：`{expected_revision,appearance,customAppearance?,home,ui}`。appearance 为 A/B/custom；custom 时必须提供 `{version:1,base:'A'|'B',overrides:{有限语义token:'#RRGGBB'}}`。只有一份保留的自定义，选择 A/B 不删除它。旧 A/B 请求省略 customAppearance 时，服务端保留既有自定义；null 可显式清除。根/嵌套字段 extra-forbid、严格类型。`ui` 省略时为默认布局（兼容前一候选客户端）；本实现发送全部字段。现有 app_config JSON 扩展，无 DDL。

调色输入只更新实时 preview，完成本次选择后发布 committed appearancePreference，由既有控制器合并上传；点对象、切模式、同色值不上传。取消恢复事务起点，撤销/单项重置/恢复基底均可用。`stella_appearance_edit_mode` 是本机 UI 模式，不进账号或备份；`stella_appearance_unconfirmed` 是本机未确认标记，同样不进备份，只有匹配的账号 GET 回读才清除。失败后的整页刷新保留输入为显式冲突，不无条件用云端旧配色覆盖。不同 owner 取消旧 owner preview；同 owner 更新不覆盖正调草稿。

```json
{
  "revision": 1,
  "appearance": "A",
  "home": {
    "theme": "daybreak", "particles": "stars", "bgImage": "",
    "bgCrop": {"cx": 0.5, "cy": 0.5, "w": 1, "h": 1},
    "siteTitle": "StellaHaven", "signature": "", "meetDate": "2026-05-31",
    "live2d": true, "avatar": "/avatar.png"
  },
  "ui": {
    "backgroundQuality": "compressed1", "sidebarFold": false, "serversFold": false,
    "toolsOpen": false, "worldMapCollapsed": false, "monitorMode": "chart",
    "noteEditMode": "rich", "listFold": false, "driveBackground": "solid"
  }
}
```

`backupClientPreferences.ts` 的 `{version:1,values:{…}}` 只是内部窄存储投影，**不是 HTTP DTO**。`clientPreferenceContract.ts` 精确双向映射并拒绝未知键/错误类型；不能把 localStorage dump 交给 API。

## 20 键审计

| 来源 | 精确键 → DTO 字段 | 允许值 |
|---|---|---|
| appearance store | `stella_appearance` → appearance | A/B/custom |
| appearance store | `stella_custom_appearance` → customAppearance | null 或 version/base/overrides 严格 JSON；28 个有限语义 token，仅六位不透明 hex；拒绝未知字段、CSS/JS/URL |
| home store | `stella_home_theme` → home.theme | daybreak/nightfall/classic |
| home store | `stella_home_particles` → home.particles | stars/motes/sakura/off |
| home store | `stella_home_bg` → home.bgImage | 空或 `/assets/homebg/` 下单文件名；≤220，无 `..`/转义/query/远程 URL |
| home store | `stella_home_bgcrop` → home.bgCrop | 仅 cx/cy/w/h 四个有限数；中心 [0,1]、宽高 (0,1] |
| home store | `stella_site_title` → home.siteTitle | ≤120，无 C0/C1 控制字符 |
| home store | `stella_signature` → home.signature | ≤512，无 C0/C1 控制字符；这是签名而非笔记正文 |
| home store | `stella_meet_date` → home.meetDate | 真实 YYYY-MM-DD |
| home store | `stella_live2d` → home.live2d | on/off ↔ boolean |
| home store | `stella_avatar` → home.avatar | 空、`/avatar.png` 或 `/assets/avatars/` 下单文件名；≤220，无 `..` |
| backgroundMedia | `stella_home_bg_quality` → ui.backgroundQuality | original/compressed1/compressed2 |
| App | `stella_sidebar_fold` → ui.sidebarFold | 0/1 ↔ boolean |
| ServersSideBar | `stella_servers_fold` → ui.serversFold | 0/1 ↔ boolean |
| ServersSideBar | `stella_tools_open` → ui.toolsOpen | 0/1 ↔ boolean |
| ServerWorldMap | `stella_server_world_map_collapsed` → ui.worldMapCollapsed | 0/1 ↔ boolean |
| OverviewView | `stella_mon_mode` → ui.monitorMode | chart/simple |
| DocEditor | `stella_note_edit_mode` → ui.noteEditMode | rich/markdown，仅模式 |
| NotesPage | `stella_list_fold` → ui.listFold | 0/1 ↔ boolean |
| drive controls | `stella_drive_bg_mode` → ui.driveBackground | solid/image；保留原有 legacy 双写语义，不复制 legacy key |

背景/头像引用通过校验不等于资源字节已进入 ZIP；服务端仍验证配置资源引用/字节。远程 URL、无效值会显示同步失败，不能偷偷删去该字段而称完整成功。

## 不采集与限界

- 不采集 token/cookie、浏览器/设备标识、IP 缓存、bootstrap、凭据、notes 正文/草稿/历史/目录 ID、模板正文、网页源码或运行态、receipt、mood 内容；既有服务端 notes preferences 不重复同步。
- 不遍历 localStorage，不清 origin，内部对象值总长度≤8192。应用时只操作允许键，不删除缺省键。
- 浏览器关闭前尚未确认的输入、离线设备、其他账号/设备的未同步偏好不属于已确认备份；没有后台跨设备浏览器抓取能力。
- 同一浏览器被另一账号改写本机归属后停止上传并提示重新读取；不猜测归属/不偷换其他账号数据。
- 原生下载、settings 完整性投影、默认目录后端状态和最终 inventory 由父集成；本提交不覆盖其并行修复，不 push/deploy。

## 验证

见仓库 `docs/backup-center/preferences-sync.md` 与 `evidence/preferences-sync/`。有严格垂直 RED→GREEN、真实 owned PG18 + FastAPI HTTP + Vue DOM/store 联测；普通 browser 视觉 fixture 仍明确不是生产或 PG 恢复证据。
