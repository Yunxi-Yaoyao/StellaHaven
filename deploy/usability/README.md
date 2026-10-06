# Stella 入口公开静态分发（准备包，非已部署）

本目录只含部署工具/隔离测试，基线 `37aabbb94de1a51d3514186ccc1afe2ee2ff52ab`。不改 main/frontend、数据库、DNS、FRP、应用容器、systemd，也不新增代理。

## 现场与边界

只读发现：HK nginx 1.24.0，主配置 `/etc/nginx/nginx.conf`；Stella 独立入口实际为 `/etc/nginx/conf.d/stella.xiya.live.conf`（普通 root:root 0644 文件，不是 symlink）。HTTPS `location /` → `127.0.0.1:12031` FRPS → 主端 `25131`，业务 HA gate 保留。其他域和 `app-*.xiya.live` 集成入口配置不改。

原缓存已正常：业务 `/assets` 的 7 天 immutable 头不是本次修复对象；这次只把**精确构建镜像的 `frontend/dist/static` 哈希产物**放在 HK 本地，省去首次/未命中缓存时的 FRP 往返。

- URL 仍是 `/static/<Vite-hash-name>`。不重写 HTML/JS/CSS；HTML、`/source`、API、auth、WS、附件、`/assets`、集成资源等仍走原主端反代。
- 每个允许文件生成一个 exact `location =` + immutable 版本目录 alias，不做任意扩展名正则捕获。未列出的 `/static/` 返回 404，无 SPA fallback；`.map`、非哈希文件不分发。
- `releases/<manifest-sha>/public/static/` 保留多版，配置为版本并集。相同 URL 不同内容直接拒绝，并清除该次新建的冲突版本；不自动 GC。首次上线前须先为当前镜像建立分发；否则无法凭空保留旧标签页的旧资源。后续发布保留当前及新版本。
- 不读/复制 `/app/data`、私有附件或挂载资源；stage 中 `source-index.html`、完整 SHA manifest 是私有校验材料，不在 served tree 中。
- 保留原 TLS、proxy headers、WS upgrade、超时与主端资格门；仅公开已内置构建产物无需重新回 FRP 做业务授权。

## Manifest/路径护栏

必须给完整 immutable registry digest、完整本地 image ID、完整 revision。CLI 拒绝 tag；只接受本仓库 registry。OCI revision label 存在时必须一致，缺失时 revision 是操作者明确批准的镜像—源码绑定，不能宣称已从镜像独立推导。

完整 dist 文件 SHA256+size 的规范 manifest（不含自引用 version 字段）SHA 决定版本；manifest 文件本身 SHA 另见 EVIDENCE.json。只有哈希命名的 `static/` 编译资源进入 public 子集。HTML 的直接 static 引用必须属于子集。验证所有 public 文件 SHA、长度、精确文件集，拒绝 symlink、路径穿越、额外文件、非当前 UID 所有或 group/world writable 的目录链。生产以 root 本地执行。

最终目录 rename、配置与 receipt 原子替换，文件/目录 fsync。root-only 状态目录 0700，备份 0600（umask 077 等效隔离），保存完整 `nginx -T`、旧 vhost、candidate、manifest。nginx 开机正常读取持久路径，不依赖 scratch/tmp、额外 service 或 dangling `current` symlink。SIGKILL/断电不等于自动回退：有持久备份供操作者恢复，不声称 watchdog 或跨应用发布原子性。

## 脱敏时序观测

只在 Stella 主域两个 server 中切换 `access_log` 格式，仍用现有 `/var/log/nginx/stella-safe-access.log`，不修改其他域共享格式。JSON `escape=json` 字段：

`time, origin ($scheme://$host), method, path ($uri), status, bytes, request_time, upstream_connect_time, upstream_header_time, upstream_response_time`。

不记录 `$request`、`$request_uri`、`$args`、query、Cookie、Authorization、Referer 或其他请求头；继续 `error_log /dev/null crit`，避免错误日志的原始请求串泄密。已有日志不会删除/重写，旧安全文本行与新 JSON 行需由读者区分。无上游 timing 可为 `""` 或 `"-"`；多上游值也是字符串。时序不是 tracing，不能凭它宣称 SQL/链路往返次数。

JS/CSS gzip 同时包含 `application/javascript` 与 `text/javascript`（本机新版 mime.types 后者，HK 旧版可前者）。`X-Stella-Static-SHA256` 只暴露公开资源内容哈希，用于识别实际 edge 响应，避免 `nginx -T` 或主端同 bytes 被误判为 reload 已生效。

## 本地验证（不触碰生产）

```sh
python3 -m unittest discover -s deploy/usability/tests -v
python3 deploy/usability/deploysafe.py verify-stage /absolute/trusted/stage
python3 deploy/usability/rehearse_stage.py \
  --stage /absolute/trusted/stage \
  --snapshot /absolute/trusted/hk-stella-before.conf \
  --out /absolute/trusted/new-scratch-evidence
```

测试自建 loopback fixture primary，进程结束时只终止自己的 nginx，TLS 自签证书由测试信任，非真实用户登录/业务验收。单测覆盖路径、文件哈希、私有文件排除、冲突、并发锁/配置更新护栏、验证失败回退。真实 nginx/TLS 覆盖 HTML/source 回源、JS/CSS headers/body SHA/gzip、旧版 retain、404/private、WS 101、业务 primary 503 与 public static 200、其他域/集成域不捕获、query 脱敏和 timing JSON、真实 reload/手动回退。

当前已建立的可验证旧镜像 stage（不是待发布新镜像）：

- `/root/.hermes/cache/scratch/stella-edge-20261006/current-stage/`
- 当前镜像 digest `4c08d85e9cfca39ba91c46a4147a38a73b84dbfc70a2c60a55eb39d35fe5a3f2`
- 版本 `102f2ca805aff392f605acf29e6bd8df5d2418b4857dfb309c99bb61552bf31c`
- dist 325 文件；public 263 文件，全部真实 HTTP 200/body SHA/缓存头匹配；公开 bytes 6873145。
- 实测证据 `/root/.hermes/cache/scratch/stella-edge-20261006/current-rehearsal-hk/result.json`。
- 同样使用本机 nginx 1.30.5 和**只读复制的 HK 实际 nginx 1.24.0 二进制**进行隔离验证；未在 HK 写入测试配置/启动测试进程。
- HK full config 私有只读快照：`.../hk-nginx-full.txt`；vhost 快照：`.../hk-stella-before.conf`。
- reviewed vhost SHA256 `03eb728d308c9ba14c8948a021a14e002f093f1031bdf7a44cd7f852fb520d84`；执行 apply 前重新只读确认，不能盲用旧 hash。

Scratch 可能闲置 24 小时被清理；操作者应把 stage/证据归档到批准的持久本地目录。没有新镜像时只证明现有镜像可用，不虚构新版 stage。

## 父执行者发布步骤（本子任务未执行）

1. 当前镜像 stage 可 `--read-only-container stella-app-shadow-nyarch` 提取：要求 exact image ID、ReadonlyRootfs=true，没有任何覆盖 dist 的 mount，且 docker diff 无 dist overlay 改动；只有 inspect/diff/cp，不 create/start/exec/rm。默认 extract 使用本地临时 carrier **create/rm，但绝不 start/pull**，显式选择该命令意味着批准本地 ephemeral carrier 操作。
2. 新镜像构建完成后，从**确切 Docker 镜像 dist**提取，不允许拿另一次 npm build 的 dist 顶替：

   ```sh
   python3 deploy/usability/deploysafe.py extract \
     --image 'gitlab-registry.xiya.live/yaoyao/stellahaven@sha256:<full-approved-digest>' \
     --revision '<full-approved-commit>' --out /absolute/trusted/new-stage
   ```

   输出的 `manifest.json` 和 `source-index.html` 留在 0700 stage；仅 public 子集进入 `/var/www/stella-public-static/releases/`。若只批准只读，添加经过验证的 `--read-only-container`，禁止默认 carrier 路径。
3. 独立测试新 stage 后，父执行者获得生产写入批准再 SCP 工具/完整 stage 到 HK 上批准的 root-owned 0700 staging 路径。hash/文件集回读。不得复制自己的 nginx 测试证书、scratch config 或 HK 私钥。
4. **发布前 apply 新 stage 时指定 `--primary-stage /approved/path/current-stage`**：先核验/保留当前和新两版资源，HTML health 仍要求当前镜像 index SHA，新资源 health 要求新 stage SHA/edge marker；主端 HTML 一字不改。全部通过后父执行者才按原 CD/HA 发布新应用镜像，再只读回读新 HTML SHA 与 all static identity。这样不必先换应用再补静态别名，避免新页面请求落入旧 `/static/` 白名单。若应用已经发布，省略 `--primary-stage` 则 HTML 必须匹配新 stage。仍不宣称跨应用/edge 原子发布；不修改稳定 CD 或主备规则。
5. HK 本地生产写入命令（本子任务禁止执行）：

   ```sh
   python3 /approved/path/deploysafe.py apply /approved/path/new-stage \
     --primary-stage /approved/path/current-stage \
     --expected-vhost-sha256 '<fresh-reviewed-64-hex>' --approve-production-write
   ```

   只允许固定 Stella vhost/公开目录/私有状态目录。先基线 `nginx -t/-T`、备份；公开版本落盘→单 vhost 原子替换→`nginx -t` 成功才 reload→精确文件/`-T` 回读→原 Host/SNI/证书验证的 `curl --resolve ...:127.0.0.1` GET HTML/live/all public 哈希和缓存/edge marker。reload 非同步，首资产稳定窗口+有界重试防旧 worker。任何失败自动还原旧 config，再 test/reload/readback/live；无法确认则 receipt 明确 `rollback-needs-operator`。
6. 手动回退使用成功回执给出的固定 transaction 路径：

   ```sh
   python3 /approved/path/deploysafe.py rollback \
     /var/lib/stella-edge-deploy/<exact-32-hex-transaction> --approve-production-write
   ```

   回退须匹配当前 candidate 或已恢复的 previous config；遇到后续改动拒绝覆盖。恢复配置/TLS/反代，public 版本保留；主端自然提供自身 HTML/source/static。**edge 回退不是应用镜像回退**，应用回退仍用原 CD receipt。如果 previous 配置已有旧版 `/static/` 白名单且应用已升级，先回退应用再回退 edge，避免删掉新版 active 页面所需别名。尚未发布应用的预分发可直接回退 edge。多次回退按倒序处理。

观察到当前 Nyarch stable app `restart=no`，未修改；这是既有可靠性风险，交由父执行者单独评估，不能夹带本次变更。
