import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
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
      "/assets": "http://127.0.0.1:12031",
      "/ws": { target: "ws://127.0.0.1:12031", ws: true },
    },
  },
});
