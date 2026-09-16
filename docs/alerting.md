# Stella 告警系统（2026-09-16 上线）

## 定位

选择性添加的告警：用户对某个节点 / 监控项 / WG 链路单独加规则，不做全局默认告警。
触发后走两个通道：**站内铃铛（WebSocket 实时 + 落库）** 和 **邮件（复用 Stella SMTP 配置）**。

## 数据模型（migration c8d9e0f1a2b3）

| 表 | 角色 | 要点 |
|---|---|---|
| `alert_rules` | 规则 | `kind`（node_offline / monitor_down / wg_link）+ `target`，同目标同类唯一；`debounce`（默认连续 2 次）、`repeat_minutes`（默认 30）、`email` 开关、`enabled` |
| `alert_states` | 当前状态 | **槽位覆写**，一规则一行：ok/firing + 连续异常计数 + 最近变化/通知时间 |
| `alert_events` | 历史流水 | fired / resolved 各一行；重复提醒不写流水 |
| `notifications` | 铃铛内容 | 标题/正文/级别/跳转链接/已读位；`rule_id` 可空（规则删除后通知保留） |

## 状态机

```text
ok ──连续 debounce 次异常──▶ firing ──一次正常──▶ ok
                   firing 期间：每 repeat_minutes 站内重复提醒一次（不发邮件、不写事件）
中性态（不触发也不恢复）：unknown 探测 / pending 节点 / 链路或目标暂时缺失
目标被删除且正在告警：静默复位为 ok，不发「已恢复」通知
```

## 惰性判断（无独立轮询进程）

评估挂在已有数据落库路径上：

| 规则类型 | 评估触发点 | 触发条件 |
|---|---|---|
| node_offline | agent 心跳上报（`handle_report`，约 5s 一批） | `node_status == offline`（心跳超 120s） |
| monitor_down | 探测结果入库（`record_check`） | `monitor.status == down` |
| wg_link | 地图快照保存（agent 60s 上报） | 链路 `health == failed`（红）；degraded（橙）/unknown（灰）不触发 |

注意边界：所有 agent 都失联时没有评估机会（此时任何通知也发不出去，属固有边界）。

## 派发

- **站内**：`notifications` 落库 → `notify_ws`（`/ws/notifications`，cookie 鉴权，asyncio.Queue 模式）广播 → 前端铃铛角标实时 +1；WS 断线时前端 30s 轮询未读数兜底。
- **邮件**：后台线程发（不阻塞上报路径）；复用 `admin_email` 的 SMTP 配置；收件人 = 第一个有邮箱的管理员；配置未启用或发送失败静默降级（站内已落库）。重复提醒只站内，不轰炸邮箱。

## 前端

- 侧栏底行铃铛（`NotificationBell.vue`）：未读角标、下拉面板、点击跳转目标页并标记已读、全部已读。
- 服务器模块新增「告警」视图（`/status?view=alerts`）：规则列表（状态点/启用/邮件/删除二次确认）、添加面板（三类目标下拉自动排除已加过的）、最近事件。
- 文案沿用猫尾风格（……喵~），视觉沿用 Outline 深色体系（CSS 变量 + Feather 线性图标）。

## 上线顺序（schema 变更的特殊性）

发布守卫要求「镜像 heads == inventory schema_revision == DB alembic_version == STELLA_EXPECTED_SCHEMA」四者一致，且 CD 不跑迁移。所以 schema 变更的发布顺序固定为：

1. 生产主库手动 `alembic upgrade head`（本迁移只新增 4 张表，不动存量数据）；
2. 更新 GitLab 变量 `STELLA_EXPECTED_SCHEMA` 与 inventory 内 `schema_revision` 为新版本号；
3. push master，走 Auto-Deploy。
