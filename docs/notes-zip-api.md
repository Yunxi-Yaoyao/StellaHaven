# Notes ZIP structured import API

两端固定 multipart API（使用现有登录认证）：

- `POST /documents/import/zip/preview`: `file` ZIP、`workspace_id`、可选 `parent_id`、可选 `encoding`（默认 `auto`，支持 `utf8` / `utf-8` / `utf-8-sig` / `bom` / `gb18030`）。只读、检查工作区和目标父页面写权限。
- `POST /documents/import/zip`: 同上，额外必填 `import_id`（UUID；客户端为一次导入生成，网络重试保持不变）。

预览响应：
```json
{"entries":[{"path":"Guide","title":"Guide","kind":"directory","parent_path":null},{"path":"Guide/a.md","title":"a","kind":"document","parent_path":"Guide"}],"warnings":[],"counts":{"documents":2,"attachments":0}}
```
`documents` 计数包含目录页面。目录的 `README.md` 提供目录正文，不额外建立 README 子页面；根 README 是普通文档。附件也在 entries 中，kind=attachment。

提交响应：
```json
{"documents":[{"id":"UUID","title":"Guide","path":"Guide","parent_id":null}],"attachments":0,"warnings":[],"reused":false}
```
重复提交返回原始映射且 `reused=true`。幂等键绑定用户、工作区、原 ZIP 内容 hash、目标父页面；同一键更换这些参数或编码返回 409，不会覆盖已有文档。全部页面作为当前用户的私有 published 文档创建，同级标题冲突加数字后缀。

相对 Markdown 行内链接、引用定义和 wiki 路径以源文件路径精确解析，不做全局标题近似匹配；围栏和行内代码不改写。附件进入现有附件存储及文档附件关系。页面 URL 固定为 `/notes?doc=<UUID>`（核验旧编辑器只按标题处理 wikilink，没有现成 ID query 导航；前端需读取 `doc` query 并按 ID 打开，不能回退标题匹配）。未找到相对目标保留原链接并产生 warning。

安全：拒绝绝对路径、路径穿越、符号链接、加密文件、不支持压缩、重复规范路径以及超过压缩大小/解压大小/条数/压缩比限额的 ZIP。非法内容 400，资源归属不符和找不到目标均 404（复用现有安全规则，不泄露资源存在性），过大 413，幂等参数冲突 409。数据库整体提交；失败回滚并仅清理本次新建的附件文件。

## 实现细节与边界

- 压缩包最多 32 MiB，解压总量 128 MiB，单文件 25 MiB，显式/隐式条目各最多 2000，单项压缩比不超过 200。仅 stored/deflate；空包以及只有根层附件而没有任何 Markdown/目录的包拒绝。
- `.md` / `.markdown` / `.txt` 均导入为文档；TXT 与平铺导入一致，转义 Markdown/HTML 并保留硬换行，不解析其中的链接。正文换行统一为 LF，拒绝 NUL。
- `encoding` 控制正文；`auto` / `bom` 优先识别 UTF-16 LE/BE BOM，`auto` 其余先 UTF-8（可带 BOM）后 GB18030。文件名按 ZIP 标准 UTF-8 标志/CP437 解码，非标准旧 ZIP 的 GBK 文件名不自动猜测。
- receipt 保存在已有 `app_config` 表的 SHA-256 命名空间键中，无需迁移；包含用户范围的 import_id 对应 scope + 原始返回映射。PostgreSQL 事务 advisory lock 串行化重试及同工作区 ZIP 标题分配。正常文档删除不会删除 receipt。
- 原路径保留在页面 `file_path` / 附件 `filename` 中；磁盘仍是现有 UUID 文件名，绝不按 ZIP 路径解压到磁盘。
- 一个附件被不同页面引用时，按页面建立独立附件副本，兼容原系统“一附件仅一个 doc_id、保存时清理无引用附件”的生命周期；响应 `attachments` 是 ZIP 中附件源路径数量，不是物理副本数量。无引用附件自动挂到目录正文（根附件挂首个新页面），添加下载链接避免后续保存被清理。
- 目录页面为可编辑普通页面（`is_folder=false`）；README 正文归目录；不解析 frontmatter 为权限或状态。
- 共享目的地址扫描器支持平衡括号、转义括号、行内空格路径、尖括号路径、引用定义及 wiki 路径；保护 fenced / 缩进代码和精确长度的跨行 backtick spans。不是完整 CommonMark AST，复杂列表容器语法仍不保证全面支持。
- 预览和提交均报告未找到的相对路径；保存 `/notes?doc=UUID` 链接时同步精确 ref 反链，仅注册同工作区、未删除、非自身目标；外部工作区 UUID 留在正文但不会注册关系或泄露目标信息，移除链接会删除关系。
- 路径最多 32 层、UTF-8 总长 1024 字节、单路径分量 255 字节；在构建目录链前检查，超限 413。
- 文件系统与 PostgreSQL 无分布式事务；捕获的异常会回滚并清理新文件，进程被 kill 或主机崩溃可能留下孤儿 UUID 文件，尚无后台回收器。

测试：`tests/test_notes_zip.py`、`tests/test_notes_zip_integration.py`、`tests/test_notes_zip_parser.py` 覆盖 ZIP API/解析与保存反链；真实 API 使用隔离 PostgreSQL，附件目录 monkeypatch 到 pytest tmp_path；没有生产调用、部署或 schema 修改。

## 平铺导入丢响应重试

普通 `POST /documents/` 可选 `X-Import-Key` 头：必须与请求 `file_path` 完全相同、以 `/imports/` 开头且最多 1024 字符。按用户 + 工作区 + 路径加 PostgreSQL 事务 advisory lock，先查同工作区同路径，有则返回原文档（201），不覆盖用户后续编辑或恢复软删除。没有此头时保持普通创建语义。回归：`tests/test_flat_import_retry.py`。
