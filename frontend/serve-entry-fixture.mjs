// Read-only UI replay of REAL-LINUX.json. Not a live Agent/production fixture.
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import {readFile} from 'node:fs/promises';
const receipt=JSON.parse(await readFile(process.env.ENTRY_EVIDENCE,'utf8'));
const node=receipt.node_projection;
const entries=receipt.channel.icmp.map(s=>({entry_id:s.entry_id,origin:s.entry_id==='public'?receipt.channel.report.origin:'https://'+s.hostname,hostname:s.hostname,version:s.version}));
const server=await createServer({configFile:false,envDir:false,plugins:[vue()],appType:'custom',cacheDir:process.cwd()+'/.cache/entry-browser',optimizeDeps:{noDiscovery:true,include:['vue','vue-router']},server:{host:'127.0.0.1',port:0}});
server.middlewares.use(async(req,res,next)=>{
 if(req.url==='/nodes/entry-monitoring'||req.url==='/nodes/'){res.setHeader('Content-Type','application/json');res.end(JSON.stringify(req.url==='/nodes/'?[node]:entries));return;}
 if(req.url==='/'){
 const html=`<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><p style="font:14px sans-serif;color:#999">候选 UI · 已完成的 Linux 实测回放，不是实时网络健康</p><div id="app"></div><script type="module">
 import {createApp} from 'vue';
 import {createRouter,createMemoryHistory} from 'vue-router';
 import '/src/style.css';
 import {auth,security,securityChecked} from '/src/modules/home/auth.ts';
 import Panel from '/src/modules/settings/NodeMonitoringPolicySettings.vue';
 auth.me={id:'owned-fixture'};securityChecked.value=true;Object.assign(security,{enabled:true,configured:true,elevated:true,expires_at:null});
 const router=createRouter({history:createMemoryHistory(),routes:[{name:'status-node',path:'/status/:id',component:{template:'<div>node detail link</div>'}},{path:'/status',component:{template:'<div>history link</div>'}}]});
 createApp(Panel).use(router).mount('#app');
 </script><style>body{margin:24px auto;padding:0 16px;max-width:900px}html,body{background:var(--bg-base)}</style></body></html>`;
 res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/',html));return;
 } next();
});
await server.listen();console.log('ENTRY_FIXTURE_PORT='+server.httpServer.address().port);
for (const signal of ['SIGINT','SIGTERM'])process.on(signal,async()=>{await server.close();process.exit(0);});
