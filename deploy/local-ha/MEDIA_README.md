# 动态背景 / 头像 PostgreSQL 集成

## 范围与开关

- 默认仍使用本地文件。只有 `STELLA_BLOB_STORAGE=postgres` 启用 PG；本次不发布生产、不运行迁移或切换主库。
- PG 模式原图、原视频及优化衍生物使用 `BlobObject` / `BlobChunk`。背景索引为 `AppConfig.key=homebg_index`；头像当前 URL 与最近五个历史 URL 仍在 User。
- 依赖父集成的 blob 表迁移和 blob_store；上传按 256 KiB 分块，背景上限 80 MiB，头像 10 MiB。超限回滚，不产生可见的半对象。
- 背景索引使用同一个 SQLAlchemy Session 的行锁，blob 与索引一起提交。头像上传和历史选择锁 User 行；上传用 UUID 唯一文件名，超出五个的头像 blob 同事务删除。
- 背景上传列表保留归属过滤；系统/默认背景不可删除。文件 URL 保留此前公开访问语义，**不是私有附件接口**。

## URL 与本地文件边界

`main.py` 在 `/assets` StaticFiles 之前挂载 dynamic_assets router：

- `/assets/homebg/{filename}` GET / HEAD
- `/assets/avatars/{filename}` GET / HEAD

不能用 `/assets/{kind}/{filename}` 泛路由，否则其他二级打包资源会被错误拦截。
PG 模式这些 URL 的缺失对象返回 404，不能从旧上传目录找同名文件兜底。其他资源继续走原 StaticFiles。
可选 `STELLA_PACKAGED_ASSETS_ROOT` 只允许固定 `homebg/default-bg-kimono.jpeg` 的只读打包背景回退；不是通用迁移或索引导入功能。
本地文件模式仍读取原目录，路径越界与符号链接被拒绝。

## 编码与缓存

- PG 优化在临时目录中流式重建原件，用现有 ffmpeg/ffprobe 生成预览和质量版本，再将衍生物纳入上传事务。临时目录和 sidecar 不是权威状态。
- GIF 保留动画原件，生成静态预览；不可解码输入保留原件并返回明确 error 状态。
- 原件和衍生 URL 可 GET / HEAD / Range / If-None-Match。`STELLA_BLOB_CACHE` 是可丢弃的本地磁盘缓存；对象是否存在始终先读 PG，删除后即使缓存尚在也返回 404。
- 这是有界内存、临时磁盘编码和磁盘 FileResponse 缓存方案，不是零磁盘流式方案。缓存空间需运维限制/清理。
- PG 转码目前同步完成并持有背景索引事务锁，长视频会延长请求和序列化背景修改；本次没有宣称异步分布式编码队列、吞吐压测或跨主机故障恢复已验收。

## 隔离实测

工作树：`/opt/hermes-workstation/stella-ha-integration`；分支：`feature/local-ha-20260915`。
已核对应用测试配置为 `172.25.0.2:5432/stella_ha_integration`，现有 conftest 替换后实际测试库为 `stella_test_ha_integration`。
**现有 tests/conftest.py 会建表并在会话末 drop_all；禁止对生产配置运行，禁止多个 whole-app pytest 同时使用这一个测试库。**

```sh
# 必须先核对当前 worktree 配置与派生测试库，不打印密码。
/opt/Yunxi-workstation/Stella/.venv/bin/python -c "from app.config import settings; from sqlalchemy.engine import make_url; u=make_url(settings.database_url.replace('/stella','/stella_test')); assert (u.host,u.port,u.database)==('172.25.0.2',5432,'stella_test_ha_integration'); print(u.host,u.port,u.database)"
STELLA_BLOB_STORAGE=file STELLA_HA_MODE=off \
  /opt/Yunxi-workstation/Stella/.venv/bin/python -m pytest \
  tests/test_dynamic_assets_pg.py tests/test_homebg_media.py \
  tests/test_auth.py tests/test_background_cache.py -q
```

实测覆盖：

- PG 80 MiB / 10 MiB 限制、回滚、归属过滤、系统保护、上传/改名/删除；
- 真实 PNG 和 MP4 上传、ffmpeg 优化，原件/两级视频/两张预览读回；
- 新 DB session + 空缓存读取模拟第二个应用进程，完整字节、Range、HEAD、ETag 和删除全部衍生物；
- 六次头像上传 URL 唯一、保留五条、旧头像删除、历史切换；
- main 实际挂载的 PG/legacy 路由，其他 StaticFiles 资源不受拦截，PG 不误读旧本地文件；
- legacy 头像上传与历史、原背景媒体测试（含横竖视频、GIF、失败恢复）、认证与背景缓存回归。

第二进程场景使用独立 SQLAlchemy session 和独立缓存目录，**不是已启动两个真实节点**；没有生产 HTTP 请求、网络变更、Docker 操作或 push。
