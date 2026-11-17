import {defineConfig} from 'vite';
import vue from '@vitejs/plugin-vue';
import fs from 'node:fs';
import path from 'node:path';
// Loopback-only browser harness. No backend proxy and no live credentials.
const out=process.env.STELLA_DOC_OUTPUT!;
export default defineConfig({plugins:[vue(),{name:'documentation-built-fixture',configureServer(server){
 server.middlewares.use(async(req,res,next)=>{
  const p=new URL(req.url!,'http://fixture.invalid').pathname;
  const json=(value:unknown,status=200)=>{res.statusCode=status;res.setHeader('content-type','application/json');res.end(JSON.stringify(value));};
  if(p==='/auth/me'||p==='/auth/refresh')return json({detail:'fixture guest'},401);
  if(p==='/auth/status')return json({initialized:true,has_users:true,single_user:true,email_enabled:false});
  if(p==='/config/site-background')return json({value:''});
  if(p==='/website-templates')return json([]);
  if(p.startsWith('/__doc-fixture')){
   const view=p.split('/')[2]||'appearance';
   const views:Record<string,[string,string]>={appearance:['AppearanceSettings','设置 · 外观'],website:['WebsiteSettings','设置 · 导航与网站'],sso:['AuthProviderSettings','设置 · 认证与安全']};
   const [component,title]=views[view]||views.appearance!;
   const html=`<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"/></head><body><div id="fixture"></div><script type="module">import {createApp,h} from "vue";import Component from "/src/modules/settings/${component}.vue";import "/src/style.css";createApp({render:()=>h("main",{style:"max-width:1000px;margin:48px auto;padding:24px"},[h("h1",{style:"margin-bottom:20px"},"${title}"),h(Component)])}).mount("#fixture");</script></body></html>`;
   res.setHeader('content-type','text/html');return res.end(await server.transformIndexHtml(p,html));
  }
  if(p.startsWith('/static/')){const file=path.resolve('dist'+p);if(!file.startsWith(path.resolve('dist/static')+'/')||!fs.existsSync(file)){res.statusCode=404;return res.end();}res.setHeader('content-type',p.endsWith('.js')?'application/javascript':p.endsWith('.css')?'text/css':p.endsWith('.png')?'image/png':'font/woff2');return res.end(fs.readFileSync(file));}
  if(['/','/help','/settings','/notes'].includes(p)){res.setHeader('content-type','text/html');return res.end(fs.readFileSync('dist/index.html'));}
  if(/^\/(auth|operations|config|navigation|external-modules|workspaces|documents|notes-preferences|notifications)\b/.test(p))return json({detail:'undeclared isolated request'},418);
  next();
 });
}}],cacheDir:path.join(out,'vite-cache'),server:{host:'127.0.0.1',port:15591,strictPort:true,proxy:{}}});
