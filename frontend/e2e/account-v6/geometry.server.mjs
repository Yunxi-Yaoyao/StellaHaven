// Production-built App only. No API proxy; unexpected API calls must be
// rejected by the closed Playwright fixtures rather than reach a live service.
import http from 'node:http';
import {readFileSync,existsSync,statSync} from 'node:fs';
import path from 'node:path';
const root=path.resolve(process.env.STELLA_ACCOUNT_DIST||'/root/.hermes/cache/scratch/account-polish-v6/dist');
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2'};
http.createServer((req,res)=>{
 const url=new URL(req.url,'http://127.0.0.1');
 if(req.method!=='GET'||(!['/','/settings','/notes','/favicon.ico','/favicon.svg','/avatar.png','/live2dcubismcore.min.js'].includes(url.pathname)&&!url.pathname.startsWith('/static/'))){res.writeHead(501).end();return;}
 const file=path.resolve(root,'.'+decodeURIComponent(url.pathname));
 if(file!==root&&!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}
 const target=existsSync(file)&&statSync(file).isFile()?file:path.join(root,'index.html');
 res.writeHead(200,{'Content-Type':types[path.extname(target)]||'application/octet-stream'});res.end(readFileSync(target));
}).listen(15487,'127.0.0.1',()=>console.log('account geometry static fixture ready'));
