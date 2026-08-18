# deploy/ — 生产环境配置记录副本

这里存放 **Stella 集成依赖的外部服务配置**，是生产环境实际配置的版本化记录。

⚠️ **这不是自动部署**——这里的文件不会被任何 CI/脚本推送到服务器。改配置的标准流程：

1. 先改这里的副本
2. scp 同步到目标服务器
3. 目标服务器上验证（nginx: `nginx -t && systemctl reload nginx`）
4. `git commit` 记录变更

## 目录

### `nginx/immich.xiya.live.conf`

- **部署位置**：HK 服务器（149.104.15.68）`/etc/nginx/sites-enabled/immich.xiya.live`
- **作用**：Immich 图库的公网反代（frp 隧道 → Nyarch `127.0.0.1:12020`）
- **Stella 定制点**：
  - `proxy_set_header Accept-Encoding ""` — 禁用压缩，让 sub_filter 能改 HTML
  - `sub_filter` 注入 `<style>` — 把 Immich logo（`img[alt="Immich logo"]`）替换为 Stella 头像（`https://stella.xiya.live/avatar.png`），圆形裁切。一处规则同时覆盖导航栏、侧栏底部、登录页三处 logo
- **回退**：HK 同目录下有 `.bak-YYYYMMDD` 备份；改回备份 + reload 即可
- **注意**：老婆换 Stella 头像后，更新 sub_filter 里的 URL
- 配置入库时间：2026-08-19（logo 注入上线的同一晚）
