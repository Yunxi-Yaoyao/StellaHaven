// Owned static build only; never proxies API traffic.
import http from 'node:http';
import {readFileSync,existsSync,statSync} from 'node:fs';
import path from 'node:path';
const root=path.resolve(process.env.STELLA_ACCOUNT_DIST||'/root/.hermes/cache/scratch/account-v6/dist');
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2'};
http.createServer((req,res)=>{const file=path.resolve(root,'.'+decodeURIComponent(new URL(req.url,'http://127.0.0.1').pathname));if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}const target=existsSync(file)&&statSync(file).isFile()?file:path.join(root,'index.html');res.writeHead(200,{'Content-Type':types[path.extname(target)]||'application/octet-stream'});res.end(readFileSync(target));}).listen(15386,'127.0.0.1',()=>console.log('account-v6 static fixture ready'));
