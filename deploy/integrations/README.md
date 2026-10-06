# Stella 集成入口：生成、验证与人工批准发布

本目录只生成候选配置并可执行 `nginx -t`，没有 reload/install/DNS/FRP 操作。现场证据见 `/opt/hermes-workstation/docs/2026-10-06-Stella-upgrade/infra/`。

## 已核对的入口，不另建共享隧道

- `app-<32位小写hex模块ID>.xiya.live`。后端 `IntegrationsHostMiddleware` 按真实 Host 分流，未登记模块不能落回主站 SPA。
- DNS 主站、Immich、随机 app-ID 及 `*.xiya.live` 当前均指 HK `149.104.15.68`；Cloudflare 是权威 DNS。已有单层 `*.xiya.live` 证书覆盖这些 app-ID，不覆盖 `ID.app.xiya.live`。
- HK nginx → `127.0.0.1:12031` FRPS → 现有 `stella-web` 组 → 两成员各本机 `127.0.0.1:25131`。成员唯一名 `stella-runtime-nyarch` 与 `stella-runtime-nas`，同组/remote12031，均以 HTTP `/ready-primary` 检查主资格。
- 本次只读探针 Nyarch=200、NAS=503，符合当前单主承流。配置/探针不是故障切换演练；不宣称本次验证双主/停机恢复。
- Tokyo 有 `*.xiya.live` 证书与 FRPS12031，但当前 `frpc@tyo` 的 Stella 为 legacy local12031、无上述 HA gate；**不可直接切 DNS 到 Tokyo 然后宣称沿用 HA**。

## 一次性部署清单（未执行）

1. 先发布且验证两个 HA runtime 中的 Host middleware，位于 SPA fallback/auth 中间件外层；Cookie host-only、Origin/CSRF、审批上游及 target pin、HTTP/WS 协议测试由后端接入实现保证。本 nginx 不替代它们。
2. 在 HK 的私有 staging 目录生成：
   ```sh
   python3 deploy/integrations/prepare.py \
     --cert /etc/ssl/xiya.live/fullchain.pem \
     --key /etc/ssl/xiya.live/privkey.pem \
     --output /root/stella-integrations-stage --validate
   ```
   输出目录须全新；拒绝覆盖已有候选。脚本仅生成两个配置文件并 `nginx -t`，不动现有配置。
3. 检查没有更高优先级 exact/wildcard server_name 抢占 app-ID；确认两个 HA runtime 后端代码和主资格探针一致。新配置只加一个 `app-*.xiya.live` regex vhost，不改主站或 Immich vhost。
4. 得到发布批准后，保存任何既有同名配置的私有备份，再安装 `stella-integrations.conf` 到 `/etc/nginx/conf.d/stella-integrations.conf`，运行完整 `nginx -t`；通过后才人工 reload。**本任务未执行此步骤。** 不重启 `frpc@hk`、`frpc@tyo` 或 FRPS；不另建 LB group。
5. 回读完整运行配置并请求一个真实登记模块（Host保真、票据POST、未授权401/404、HTTP/WS/Range/redirect/Set-Cookie/stream/CSP）；确认主站与旧 Immich 域名不受影响。新增模块复用此入口，不逐个改 DNS/reload。
6. 回滚仅撤回这个新 conf（存在旧文件则恢复旧版本），完整 `nginx -t` 后人工 reload；不改数据库 schema、DNS、已有 FRP group，也不对应用做 schema 降级。

## NGINX 合约

- `Host $http_host` 保留请求 Host，不能改为 stella.xiya.live 或固定 upstream 名。
- WS 升级条件映射，不对普通请求无条件 `Connection upgrade`；HTTP1.1。
- 请求/响应 buffering off，Range/If-Range 保留，redirect off，Set-Cookie/CSP 不擅自剥除或重写。
- 新 vhost 默认 access/error log 写 `/dev/null`，避免 nginx error log 默认泄露带 query 的完整请求。若以后启用 access log，只用给定不含 query/referrer/Cookie 的 `stella_integrations_safe` 格式，并设置有界轮转；不要启用默认原始 error log。
- `client_max_body_size 256m` 是此候选显式限制，大文件超过限制返回413，未承诺无限上传；流读取600s后无数据会超时。

## 本次真实验证

候选完整 config 在 HK 通过匿名 memfd 传给 `nginx -t -c /proc/self/fd/<fd>`，复用真实证书/私钥，退出0；不生成远端文件、不 reload、不发业务流量。直接 `/dev/stdin` 测试失败是 nginx 二次读取 stdin 已耗尽，不是候选语法问题，最终改 memfd 验证成功。
