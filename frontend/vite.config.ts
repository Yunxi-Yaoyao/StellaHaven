import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      // 开发期 API 和 WS 都代理到 Stella 后端
      "/documents": "http://127.0.0.1:12031",
      "/workspaces": "http://127.0.0.1:12031",
      "/users": "http://127.0.0.1:12031",
      "/tags": "http://127.0.0.1:12031",
      "/doc-tags": "http://127.0.0.1:12031",
      "/document-links": "http://127.0.0.1:12031",
      "/document-versions": "http://127.0.0.1:12031",
      "/ws": { target: "ws://127.0.0.1:12031", ws: true },
    },
  },
});
