// Isolated static product-build server. No backend, proxy, or production connection.
import http from 'node:http';
import {readFileSync,existsSync,statSync} from 'node:fs';
import path from 'node:path';
const root=path.resolve('dist');
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.woff2':'font/woff2'};
http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost');const file=path.resolve(root,'.'+decodeURIComponent(url.pathname));
 if(!file.startsWith(root+path.sep)&&file!==root){res.writeHead(403);res.end();return;}
 const target=existsSync(file)&&statSync(file).isFile()?file:path.join(root,'index.html');
 res.writeHead(200,{'Content-Type':types[path.extname(target)]||'application/octet-stream'});res.end(readFileSync(target));
}).listen(15274,'127.0.0.1',()=>console.log('Isolated product build: 127.0.0.1:15274 (no proxy)'));
