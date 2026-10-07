# Stella 已公开背景的有界边缘缓存（待审，未部署）

只在现有 HK nginx 中增加两个 include，不启动服务、不加隧道、不改 FRP、app、前端或画质选择。仍代理 `http://127.0.0.1:12031`；没有静态复制、alias、目录下载或新公开 URL。

## 范围与缓存合同

- `http.conf`：独立 `stella_homebg` zone（1 MiB 元数据），`max_size=128m`、`inactive=24h`（避免单用户闲置一分钟后每次又传整段视频）、临时文件使用同一缓存目录。**128 MiB 是 nginx cache-manager 异步淘汰目标，不是文件系统硬配额**；在途下载可暂时超限。需要绝对硬上限时须另审文件系统配额，不能把本方案声称成硬配额。
- `location.conf`：仅放**精确 `server_name stella.xiya.live` 的现有 TLS server**。不能放共享 regex/wildcard server。仅原 `/assets/homebg/media-<24hex>-(compressed1|compressed2|poster|thumbnail).<媒体后缀>` 压缩衍生/封面、GET/HEAD、上游完整200可入缓存；大体积原画不进入此location，继续原Range/If-Range透传；304 只复核已有完整实体。非媒体 MIME、非 200、Authorization、查询参数、编码路径、双点路径、嵌套路径不入缓存。其他域名、网盘、HTML、API、图库、头像、鉴权接口不在缓存范围。
- 源站该路由原本匿名公开，见 `app/routers/dynamic_assets.py:22-44`。这不是将私人资源“变公开”；文件仍由原 URL 和原源站裁决。不要把路径规则扩展到其他资产类别。
- 不忽略任何响应头；nginx 原生 `private` / `no-store` / `Set-Cookie` 禁止存储。Cookie 请求头本身不主动删除，也不作为公开路由的鉴权机制；Authorization 请求明确绕过缓存。此路径今后若改为鉴权/按 Cookie 个性化，必须先停用缓存并重新审查。
- **`proxy_cache_valid 200 1s` 只是无显式源 TTL 时的缺省。** 用户提供的实际源站匿名 HEAD 已返回 `Cache-Control: public, max-age=604800, immutable`，这是**原有 7 天 HTTP 缓存语义**，不是本 include 新加的。保留该语义、ETag、源 Cache-Control/Expires/X-Accel-Expires 原生优先级，不加/重写客户端缓存头，不使用 `proxy_ignore_headers`。
- 到**实际 TTL**过期后 ETag 向源复核；304 不再穿过 FRP 传完整大正文，200 更新字节，404/500 不提供过期旧体（没有配置错误兜底 stale）。**不能说生产 1 秒后必回源或删除即时全局生效**。无显式 TTL 合成源的 1s 也有 nginx 整秒计时粒度、在途响应和浏览器缓存窗口。源响应策略若新增 stale-if-error/stale-while-revalidate 必须另审 nginx 原生扩展行为。
- 上游移除 Range/If-Range，固定 identity 表示；客户端 HEAD、Range、If-Range、If-None-Match 由 nginx 保持 HTTP 语义。冷 HEAD/小 Range 会获取完整 GET 以填充缓存，首次请求仍有大正文成本。短缓存降低重复回源传输，不保证冷启动大响应或公网 API 的性能已经改善。
- 不新增 `add_header`，避免覆盖继承安全头；不接触现有安全日志。转发头模板来自仓库既有 Stella vhost fixture（`deploy/usability/tests/test_deploysafe.py`），**不是已核验的生产配置副本**。

## 本机隔离验收

仅 Python 标准库 + 已安装 nginx；不 import Stella、不读 DB、不访问生产、不发 nginx reload。随机 loopback 端口和合成上游、scratch 缓存；root 启动时 worker 选择已存在的 `http` 或 `www-data` 非特权账户，缓存目录 0700。用 `/proc/self/cwd/` 避免为了 worker 遍历 `/root` 而修改宿主权限。脚本停止自己启动的 nginx 后归档配置/安全访问日志/合成源请求记录并移除 scratch。

```sh
python3 deploy/background-cache/test_real_nginx.py --baseline --evidence /root/.hermes/cache/scratch/bg-red
# 预期失败：两次完整 200，而不是 200 + 304
python3 deploy/background-cache/test_real_nginx.py --evidence /root/.hermes/cache/scratch/bg-green
# 可用 --test test_name 只运行某个测试方法
```

测试证据目录：
`/opt/hermes-workstation/docs/2026-10-08-Stella-experience-fix/background-cache/`

结果计数见 `TEST-RESULTS.json`；`final/result.json`、`final/origin-events.json`、`final/access.log` 是真实执行输出。RED 记录保留而不重命名成通过；`header-transition` 是旧“所有响应强制 1s”假设的反证，后来按用户给定源站证据修正为尊重显式 TTL。合成测试不等于生产认证、TLS、真实 HK 版本或浏览器性能验收。

## 安装片段（给主代理审核；本任务不执行）

1. 只读核对 HK `nginx -T` 的精确主站 vhost、现有 `/assets/homebg/` 是否已有 location、原 `location /` 的 Host/proto/XFF/real-IP、安全过滤、访问日志、继承 add_header、TLS、proxy_ignore_headers、stale 策略。不得直接照抄测试 fixture 覆盖生产策略。若与模板不一致，停止并按原策略最小适配后重新跑隔离测试。不能丢失原 location 级安全头/访问控制。
2. 保存 root-only 原配置备份及 SHA。确认真实 worker 用户/组、缓存磁盘空间，无符号链接目录；目录不位于任何可下载 document root。不更改既有服务账户。
3. 待主代理另行批准后，人工变量取自已核验的 worker（不要直接执行未赋值变量）：

```sh
install -d -m 0700 -o "$NGINX_WORKER_USER" -g "$NGINX_WORKER_GROUP" /var/cache/nginx/stella-homebg
install -d -m 0755 /etc/nginx/stella-background-cache
install -m 0644 deploy/background-cache/http.conf /etc/nginx/stella-background-cache/http.conf
install -m 0644 deploy/background-cache/location.conf /etc/nginx/stella-background-cache/location.conf
```

```nginx
# 现有 http {} 内，一次：
include /etc/nginx/stella-background-cache/http.conf;

# 仅现有精确 stella.xiya.live TLS server {} 内，一次：
include /etc/nginx/stella-background-cache/location.conf;
# 原 location /、所有其他 locations、TLS、安全策略均保持。
```

4. `nginx -t` 成功后仅 reload 现有 nginx（不 restart FRP）。回读准确配置和原站 health/ETag/body/Range，并核对其他 host 同路径与私人接口没有进入该 zone。需要授权后才运行生产探针，真实效果/缓存命中和 API 时延由主代理验收，不能用本地测试代替。

## 撤回片段

从精确主站 vhost 移除新增 `location.conf` include；从 `http {}` 移除新增 `http.conf` include（同时做，避免引用不存在的 zone）；原 `location /` 自动接回原 URL。先 `nginx -t`，再 reload 现有 nginx，并回读配置、原 URL 和其他模块健康。若校验失败，恢复备份而不是继续 reload。待旧 worker 退出后再清理**专属** `/var/cache/nginx/stella-homebg` 和两个新增 include，绝不能删除共享 cache。边缘撤回不能清掉浏览器依照源站原有 7 天策略保存的副本。
