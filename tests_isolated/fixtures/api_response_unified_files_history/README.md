# v19 root 文件自动化：候选历史证据

**PENDING_INDEPENDENT_REVIEW_NOT_APPROVED；未发布、未部署、待 aggregate 独立审查与父线最终签收。**

- 初始父基线：`fa44f76715beb1f117149311f625de4d15dfda16`。
- 当前产品基线：`fbfad972a70674c61089e3a5d19e1671d4d30b4e`（继承父线已独审的 installer P1 修复；本 API 提交不改 installer/Agent/center 业务）。
- literal 前驱源码来源：`725d2e73bfb35df7e3290cd6fc74d62799da7426`；旧 API/auth loader 原件来自初始父基线。
- 候选合同：`app/api_response_v19_unified_files_review.json`，SHA-256 `8beb2030ad77a5773bc43d2195337cdec9f7dc3ce0861a630383821bee2317a9`。
- 本目录 manifest SHA-256：`c7e32f04cf1c477b699b683a453296760c62651e2c80dfd2034192edba8d9b7d`。每份 gzip 解压后还验证 size、SHA-256 与 Git blob SHA-1；Git 不可用时也不回退当前文件冒充旧证据。

旧 v17/v18 及其他冻结 JSON 保持逐字不变。v19 保留 114 个旧 source records，追加 144 个 successor/supporting records（含 30 个显式 helper/DTO 源键）；按完整 before_operation/before_sources 和 handler preconditions 替换 106 个已有 HTTP operation 的 source union，再新增 `GET /agent/files/config`。另为文件 family 显式绑定原有 Node/User/AuthSession/agent_token 四条源记录；FileAgent/FileJob whole-module、read_state、session/lease/unknown-ACK 旧边均保留。

旧 optional-files `.18` Agent/canary/package 消费者显式读 literal 历史字节，不再假设 live Agent 仍是旧版本；当前 `.19` 公开源码和 file-release manifest/artifact 另用真实 handler/body 检查。新 config 为严格 enabled/disabled DTO union，只有该精确 method/path/callable/dependency signature 的 OpenAPI 文档改为 Bearer-only；旧 Agent query 兼容不变。

`source_approval=true` 只兼容既有 loader 的数据格式，不是作者自签独审通过；候选状态及 `release_approval=false` 不因此改变。P1 installer 的单项独审不等于本 aggregate 合同获批。

完整实跑日志、默认/strict CLI、原断言/collector 保留对账、独立 nonce / no-PG 边界和父线可验证材料位于：
`/opt/hermes-workstation/docs/records/2026-10-24-stella-agent-unified/api-contract/REPORT.md`。
