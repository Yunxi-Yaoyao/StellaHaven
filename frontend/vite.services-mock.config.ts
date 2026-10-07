import {defineConfig} from 'vite';
import vue from '@vitejs/plugin-vue';
import {resolve} from 'node:path';
// Lane-owned synthetic HTTP pages, never a proxy to real services.
export default defineConfig({plugins:[vue(),{name:'owned-service-fixtures',configureServer(server){
 server.middlewares.use((req,res,next)=>{
  const site=req.url==='/drive/openlist/'?'OpenList':req.url==='/gallery/connect'?'Immich':null;
  if(!site)return next();
  res.setHeader('Content-Type','text/html; charset=utf-8');
  res.end(`<!doctype html><html lang="zh"><head><title>Owned ${site} fixture</title><style>body{margin:0;padding:28px;background:#14171f;color:#d9e2f0;font:16px system-ui}small{color:#9babc2}input{display:block;margin-top:12px;padding:12px;background:#263044;color:white;border:1px solid #687b9a;border-radius:8px}section{padding:20px;background:#202936;border-radius:12px;margin-top:20px}a{color:#b3d4f1}</style></head><body><small>隔离 HTTP 测试站点 · 非生产内容</small><h1>Owned ${site} fixture</h1><section><p>示例文件 / 照片，不含用户数据</p><label>保留输入<input aria-label="服务内输入"></label><p>OpenList 使用笔记.md</p><a href="#reference">GitHub 示例文档链接</a></section></body></html>`);
 });
}}],cacheDir:resolve(process.env.TMPDIR||'node_modules/.cache','stella-service-vite'),server:{host:'127.0.0.1',port:15173,strictPort:true,proxy:{}},build:{assetsDir:'static'}});
