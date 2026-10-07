# 体验变更与发布门槛

## 所有权与执行顺序

1. **单 owner**：先固定原路径、首屏/背景/速度预算，隔离 worktree、浏览器和数据源；同一文件只由一个 owner 改动。先基线 RED，再修复。工作树不等于数据库隔离。
2. **独立 review**：先规格、后质量，审精确候选 SHA。不得以实现者成功摘要替代独立审查；两轮仍失败则升级根因，不运行无限 healer。
3. **独立 QA**：使用 `4aa2f4f` 引入的真实 App/Sidebar/router/store 与实际 AST 导出跨 origin 模板测试。测试 owner 不改产品，不调整像素阈值，不删除断言/skip/接受 flaky。API 延迟和失败是显式夹具，不访问生产数据库。
4. **可执行 gate**：在合并后的同一精确 commit 上执行 `cd frontend && npm run test:experience`。拒绝未提交的被测源码/夹具、遗漏用例、意外新增、重复用例、skip、xfail、retry/flaky、失败及缺少证据。CI `experience-gate` 不允许失败；`build-images.needs` 显式依赖它。
5. **受控 deploy**：只有独立审查、QA、构建和生产前置检查都通过，主 owner 才使用现有发布工具先 standby app 后 active app。保存精确备份与回滚入口；不重启/切换 PG。不新建平台，不改账号/凭据边界。
6. **production readback**：主 owner 读取生产精确版本与数据摘要，用普通会话走原日常入口，再核查真实性能与背景合成。缺项/失败/BLOCKED 一律不宣布完成；需要时回滚。健康接口或 HTTP 200 不是用户路径验收。

## 单命令和证据

此门禁提交依赖独立 QA 提交 **4aa2f4f3934b043ae1747865abebce23d31227a1**。先合入独立 QA，再合入本门禁；不复制或分叉独立 18 项的断言。

本机需 Node（项目版本）、npm 依赖、Python 3 + Pillow、ffmpeg、Chromium。CI 显式安装这些依赖，`npm ci --include=dev` 不使用用户的共享 node_modules。若使用已有浏览器可设置 `STELLA_CHROMIUM=/path/to/chromium`。

```sh
cd frontend
npm run test:experience
```

默认证据在 `frontend/node_modules/.cache/experience/`（git 忽略）：`results.json`、`receipt.json`、trace、录像、截图与像素/过程探针。可用 `STELLA_QA_OUTPUT` 设绝对独立输出目录。脚本清除旧 JSON 后运行，不接受 `--grep` 等选择参数。直接 Playwright 筛选也会因回执缺核心用例被拒绝。

`playwright.experience.config.ts` 只是独立配置的门禁包装：不变更原超时、像素预算、页面/模板或浏览器过程。不得从一份局部绿色回执拼出完整成功。

回执绑定实际 git HEAD，而不是可随意设置的“被测版本”环境变量；同时记录 harness commit、受检文件脏状态、实际所有结果与 trace SHA256。换成另一个候选 commit 后必须重跑。源与 harness 不同的基线实验可以留 RED 证据，但不会得到放行回执。CI 的 `CI_COMMIT_SHA` 与被测源码不同会立即拒绝。

```sh
python3 deploy/experience-gates/check_receipt.py \
  --receipt frontend/node_modules/.cache/experience/receipt.json \
  --commit <完整40位候选SHA> --kind synthetic-process
```

本工具检查回执结构与要求；回执不是密码学签名，也不能替代独立审查对证据来源的核实。

## 生产性能：不得以 CI 合成测试替代

同 Nyarch 独立后台浏览器、普通登录、normal cache、无 route mocks、每情境完整 5 个样本。录制/截图诊断与测速分开。

| 情境 | 中位预算 | 最大预算 |
|---|---:|---:|
| 冷直达目标目录可见 | 8s | 12s |
| 暖刷新 | 5s | 8s |
| 已保活网盘 SPA 返回 | 1s | 2s |

由主 owner 执行生产门槛；CI 仅证明过程，不证明以上延迟。checker 从毫秒原始样本重新计算中位/max，拒绝缺样本、NaN、0/负值、超预算和错误环境。不可涨预算、挑样本或用测试超时作为性能预算。

生产回执 `kind=production-readback` 使用同 schema，`commit`/`harness_commit` 都为完整目标 SHA，`dirty=false`、`status=passed`、`errors=[]`。`checks` 必须包含 `contract.json` 的全部 production-readback ID，每项 `status=passed, expected=passed, attempts=1, errors=[]`，且 `evidence` 指向实际审查/截图/数据版本回读证据。环境必须精确为：

```json
{"host":"Nyarch","cache":"normal","route_mocks":false,"ordinary_session":true,"diagnostic_recording":false}
```

`performance` 要有 `cold`、`warm_reload`、`retained_return` 三个数组，各为完整 5 个正数毫秒实测值。不要把示例/单元测试数据填写为真实回执。

```sh
python3 deploy/experience-gates/check_receipt.py \
  --receipt <主owner的实际生产回执.json> \
  --commit <完整40位部署SHA> --kind production-readback
```

生产回执目前由主 owner 在发布/回读流程调用；该文档与 checker 不声称已修改或执行 production_release，不声称生产已放行。已有背景像素 FAIL 必须保持阻断。
