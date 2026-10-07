# 受控公开指纹资产分发

只给**已审核、确定公开的构建资产**增加精确 Nginx 映射。应用仍是普通 website record；不恢复 OpenList 专用后端，也不改主站认证、单次票据、DNS pin、Origin、CSP 或主资格检查。

```text
已知的公开 JS/CSS/font/image → 指纹清单 + 原始字节 → 离线 bundle
上次完整 stage + 新 bundle → 保留版本并集 → staged Nginx include
浏览器 → HK Nginx 精确公开 URI（gzip、immutable）
       → 其他 URI：原鉴权 upstream → FRP → Stella → 原网站
```

`public_assets.py` 仅使用 Python 3.11+ 标准库。`build/stage/verify/verify-stage` 完全离线。可选 `capture` 只读取指定的 **127.0.0.1 TCP 端口**，不读凭据、不解析目标 DNS、不发送 Cookie/Authorization、不跟随跳转、不抓 HTML、不递归发现依赖。没有安装、SSH、reload、DB 或生产变更入口。

## 安全与缓存边界

- 输入必须是显式 `public: true` 的清单，包含 module ID、精确隔离 HTTPS origin、以 `/assets/` 或 `/static/` 结尾的前缀、逐文件 SHA256/size。origin 的 `app-<module_id>` 必须一致。
- 只接受前缀下的指纹**文件名**，不接受目录递归、URL、query、编码路径、HTML、JSON、map、私钥/凭据文件。JS/CSS 拒绝 HTML 响应；文本扫描拒绝明显私钥/内嵌令牌，二进制校验扩展名魔数。**扫描不是秘密检测证明**，不能用它把未知目录自动批准为公开；源仍须由操作者确认属于公开发行包。
- 源/包/暂存读取拒绝符号链接、硬链接、特殊文件、其他用户所有权及组/全局可写的父链。所有输出必须是新目录。单文件上限 8 MiB，单包 64 MiB/1024 文件；保留并集最多 16 版本/256 MiB/4096 URL，超限拒绝，不自动删除旧版本。
- 正文和 gzip 都带 hash/size；gzip 是 level 6、mtime 0。同一构建环境确定性输出；验证允许不同 Python/zlib 的合法 gzip 表示，但限制解压输出，拒绝炸弹、截断、尾随数据和拼接成员。
- 每条 `location =` 限定原始 request URI、HTTPS、精确 Host（含批准的非默认端口）、GET/HEAD、固定 alias、`disable_symlinks on`。错 host/module、query、路径归一化变体及缺失已列文件返回不缓存的 404；没有目录级匿名 location。
- **未知路径完全留给原鉴权 upstream**，不保证一定 404；它的 HTML/API/下载策略不变。`.gz` 路径、manifest、ROLLBACK 文件本身没有公开映射。
- 公开响应有正确 MIME、nosniff、`Cache-Control: public, max-age=31536000, immutable`、ETag、Vary 和预压缩 gzip。HEAD/Range/304 保留；不为错误响应加 immutable。不新加 CORS、Cookie 或动态缓存。
- 新 stage 自动合并所指定 `previous` stage 的所有版本，拒绝同一 URL 改字节。升级时必须填写 `previous`；`null` **仅用于操作者确认未部署过该模块的第一次发布**。没有文件 GC。
- hash 是完整性和审核锚点，不是签名/授权证明。由审核者独立固定输入、bundle、stage 的完整 hash；不能从收到的未信任包自读 hash 后就当作批准。

## 来源格式与构建

所有本地路径使用绝对路径，目录/文件由当前用户或 root 所有且不可被其他用户写入。不要在 `/tmp` 等全局可写父目录构建；使用 `$TMPDIR` 或受控证据目录。

### 1. 准备明确路径集合或本地发行包

`examples/openlist-observed-paths.json` 是本轮原审计实际观察到的 40 个路径，不是 OpenList 全部可能懒加载资产。列表须排序、去重，只能包含相同前缀的精确路径。未观察到的页面/新版本仍回原 upstream，不能擅自从 JS 中递归抓取。

可选公开本地提取（网络读取，需确认端口来源）：

```sh
python3 deploy/experience-static/public_assets.py capture \
  --port 5244 --module-id "$MODULE" --origin "$ORIGIN" \
  --asset-prefix /drive/openlist/assets/ \
  --paths "$PATHS_JSON" --paths-sha256 "$REVIEWED_PATHS_SHA256" \
  --out "$NEW_CAPTURE_DIR"
```

输出 `source/`、`source.json`、无秘密的 `capture.json`。只接受 200、有界 Content-Length、扩展名对应 MIME、无 Set-Cookie/attachment/private/no-store 的响应；每次读取有 socket 超时和总期限。**先审核 candidate manifest，再构建**。也可直接从离线公开发行包提供相同文件名的平面目录，无需 capture。

`source.json` 的真实例子见 `examples/openlist-observed-source.json`。字段结构：

```text
schema = stella-public-assets-source-v1
module_id = 32 位原始小写 hex 模块 ID
origin = https://app-<module_id>.<已批准域名>
asset_prefix = /drive/openlist/assets/
public = true
files = {"准确指纹文件名.js": {"sha256": "完整64位hash", "size": 整数字节数}}
```

```sh
python3 deploy/experience-static/public_assets.py build \
  --spec "$SOURCE_JSON" --spec-sha256 "$REVIEWED_SOURCE_SHA256" \
  --source "$PUBLIC_SOURCE_DIR" --out "$NEW_BUNDLE_DIR"
python3 deploy/experience-static/public_assets.py verify \
  --bundle "$NEW_BUNDLE_DIR" --version "$REVIEWED_BUNDLE_VERSION" \
  --module-id "$MODULE" --origin "$ORIGIN"
```

不会读取或打包 source 目录内未列文件。没有 HTML/source-index 私有副本进入发布包。

### 2. 离线暂存 Nginx 和保留并集

`plan.json` 必须恰好包含：

```text
schema = stella-public-assets-plan-v1
module_id, origin = 同清单
# target_root 只用于生成远端 alias，本阶段绝不写该目录，最后一段必须为 module_id
target_root = /var/www/stella-public-modules/<module_id>
bundles = [{"path": "新bundle绝对路径", "version": "审核过的完整bundle版本"}]
previous = null  # 仅首次；升级填写下述对象
# previous = {"path": "上次完整stage绝对路径", "version": "审核过的完整stage版本"}
```

```sh
python3 deploy/experience-static/public_assets.py stage \
  --plan "$PLAN_JSON" --plan-sha256 "$REVIEWED_PLAN_SHA256" --out "$NEW_STAGE_DIR"
python3 deploy/experience-static/public_assets.py verify-stage \
  --bundle "$NEW_STAGE_DIR" --version "$REVIEWED_STAGE_VERSION" \
  --module-id "$MODULE" --origin "$ORIGIN"
```

输出 `releases/<bundle-version>/`、`locations.conf`、`stage.json`、`ROLLBACK.md`。verify-stage 不只比较 snippet hash，还从已验证清单重生成并逐字对比 Nginx 配置。stage 不依赖特定 upstream 地址，也不生成完整 vhost，不会覆盖现有 TLS/代理策略。

## 真实隔离 Nginx 门禁

```sh
python3 -m unittest discover -s deploy/experience-static/tests -v

# 使用待发真实公开字节；认证/主资格 upstream 仍明确是测试夹具
STELLA_STATIC_BUNDLE="$NEW_BUNDLE_DIR" \
STELLA_STATIC_VERSION="$REVIEWED_BUNDLE_VERSION" \
STELLA_STATIC_EVIDENCE="$NEW_EVIDENCE_JSON" \
python3 -m unittest discover -s deploy/experience-static/tests -p test_real_nginx.py -v
```

依赖 `nginx`（需 http_ssl_module/http_gzip_static_module）、`openssl`。缺失不 skip，门禁失败。测试生成一次性本地证书，独立 PID/配置/temp 目录、随机 loopback 监听，只终止自己启动的进程。若 root 运行则 scratch worker 为 root，仅为访问受控 `$TMPDIR`；生产仍用现有非特权 worker，发布目录需 0755/0644。

覆盖真实 TLS gzip/解压 SHA、所有资产 304 零正文、HEAD/Range、错 Host/端口/HTTP、query/编码/traversal/double slash、未知/私有 URI 回原鉴权、动态主资格 503、缺失/符号链接失败；合成资产模式还通过真实 Nginx 验证新旧版本同时可读。测试没有导入应用或连接数据库。

## 生产交接：仅由主代理审核后执行

本工具**不部署**。现网信息须由主代理重新回读：`nginx -V/-T`、`/etc/nginx/conf.d/stella-integrations.conf`、目标 module/origin、当前静态 stage 和完整原 vhost SHA。验证远端有 gzip_static，并确认仅此 integration server 使用这份 include。**禁止把此 include 插入共享 regex server**：即使只有第一份 include，也会抢走其他模块同路径的请求并404。必须新增只匹配目标 module 的精确 Host TLS server，原共享 regex server 保持原样；后续同路径实例继续走其原鉴权上游。

主代理在 HK 的受控目录接收**完整** stage 和此工具，先 `verify-stage`；不能把 `locations.conf` 单独当作可信 payload。部署操作顺序：

1. 持有单独部署锁，确认 vhost SHA 仍等于批准基线，备份 vhost/旧 snippet 的精确字节和权限到 root-only transaction 目录。
2. 只新增 `target_root/releases/<version>`。已有版本先用 `verify` 核对，**不覆盖、不 delete、不 rsync --delete、不软链接 current**；新版本先复制到同文件系统暂存，再验证、rename。目录 0755、文件 0644，父链 root 所有且无组/全局写权限。
3. 将经过验证的 snippet 安装到独立 include 路径。复制回读审核的 TLS integration server 策略，建立仅目标 `app-<id>` 精确 server_name 的新 vhost，再在此精确 server 内添加下面一行。原共享 regex server 不动。核对原 `location /`、FRP、TLS/CSP/Origin/日志策略、regex捕获变量依赖及location级add_header继承；不把include放共享server或http顶层。

```nginx
include /etc/nginx/stella-public-125398b55f1847c7a9ebb70cc651baee.locations.conf;
```

供主代理使用的**主机本地**命令骨架（变量必须来自审核值，未在本任务执行）：

```sh
# 已验证的 $STAGE；$V 为完整 bundle version；$TARGET 为 stage.json 的 target_root
set -eu
# 在已持有的部署锁内执行；任何失败中止，由主代理按回滚计划处理
install -d -m 0755 "$TARGET/releases"
# 仅当目标版本确实不存在；若已存在，改为 verify，不覆盖
test ! -e "$TARGET/releases/$V"
test ! -L "$TARGET/releases/$V"
test ! -e "$TARGET/releases/.staged-$V"
test ! -L "$TARGET/releases/.staged-$V"
cp -a "$STAGE/releases/$V" "$TARGET/releases/.staged-$V"
python3 "$TOOL" verify --bundle "$TARGET/releases/.staged-$V" \
  --version "$V" --module-id "$MODULE" --origin "$ORIGIN"
mv -T "$TARGET/releases/.staged-$V" "$TARGET/releases/$V"
# 所有 retained version 均按上面方式新增或验证后才可以更新 snippet
install -m 0644 "$STAGE/locations.conf" "$SNIPPET.next"
mv -T "$SNIPPET.next" "$SNIPPET"
# 原 vhost 备份后，原子安装审核过的只增加 include 的 candidate
nginx -t
nginx -s reload
```

`nginx -t` 失败不 reload，立即恢复旧配置。reload 后必须读取精确文件、`nginx -T`，并等待旧 worker 切换后验证静态 SHA 标记 + gzip/cache + 解压后 SHA，不能只凭命令成功。

```sh
curl --noproxy '*' --resolve "$HOST:443:127.0.0.1" \
  --fail --silent --show-error --compressed --max-time 15 \
  --dump-header "$TX/asset.headers" --output "$TX/asset.body" \
  "https://$HOST/drive/openlist/assets/components--D9HLKs-.js"
sha256sum "$TX/asset.body"
# 同样核验完整 manifest，每个文件一次；HEAD / If-None-Match / 缺失路径 / 错 Host 独立检查。
```

随后从日常入口核验普通登录、动态 HTML/API/下载、原主资格守卫和浏览器 normal-cache 五样本门槛。**实验室的 gzip/304 证据不等于生产冷首开/暖返回预算已通过。**

失败时按 `ROLLBACK.md` 恢复精确 vhost/snippet，`nginx -t`、reload、读回与 HTTP 复验；保留全部 release 文件。旧 HTML/已开标签仍可能取旧 lazy chunks，因此常规修正应保持并集，不回退成只含单版本的白名单。若因安全原因必须彻底移除静态 bypass，恢复原鉴权路径，但不能保证 upstream 还保有旧版本文件。
