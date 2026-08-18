import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  build: {
    // 构建产物（JS/CSS/字体）输出到 dist/static，URL 前缀 /static，
    // 与业务全局资源（data/assets → /assets：主页背景/挂件/头像）分离，
    // 否则两者抢同一个 /assets 前缀，构建产物 404 导致生产白屏。
    assetsDir: "static",
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      // 开发期 API 和 WS 都代理到 Stella 后端（xfwd 转发真实 IP，登录记录要用）
      "/documents": { target: "http://127.0.0.1:12031", xfwd: true },
      "/workspaces": { target: "http://127.0.0.1:12031", xfwd: true },
      "/users": { target: "http://127.0.0.1:12031", xfwd: true },
      "/tags": { target: "http://127.0.0.1:12031", xfwd: true },
      "/doc-tags": { target: "http://127.0.0.1:12031", xfwd: true },
      "/document-links": { target: "http://127.0.0.1:12031", xfwd: true },
      "/document-versions": { target: "http://127.0.0.1:12031", xfwd: true },
      "/attachments": { target: "http://127.0.0.1:12031", xfwd: true },
      "/homebg": { target: "http://127.0.0.1:12031", xfwd: true },
      "/auth": { target: "http://127.0.0.1:12031", xfwd: true },
      "/admin": { target: "http://127.0.0.1:12031", xfwd: true },
      "/nodes": { target: "http://127.0.0.1:12031", xfwd: true },
      "/monitors": { target: "http://127.0.0.1:12031", xfwd: true },
      "/iperf-tasks": { target: "http://127.0.0.1:12031", xfwd: true },
      "/mtr-tasks": { target: "http://127.0.0.1:12031", xfwd: true },
      "/commands": { target: "http://127.0.0.1:12031", xfwd: true },
      "/agent": { target: "http://127.0.0.1:12031", xfwd: true },
      "/config": { target: "http://127.0.0.1:12031", xfwd: true },
      "/drive": {
        target: "http://127.0.0.1:12031",
        xfwd: true,
        // 前端路由 /drive（无子路径）走 vite 的 SPA fallback，只有 /drive/xxx（API）才转发后端
        bypass: (req) => (req.url === "/drive" ? "/index.html" : null),
      },
      "/assets": "http://127.0.0.1:12031",
      "/ws": { target: "ws://127.0.0.1:12031", ws: true },
    },
  },
});
