// Production dist only: no Vite, proxy, backend, or outbound HTTP.
import http from 'node:http';
import {readFileSync,existsSync,statSync} from 'node:fs';
import path from 'node:path';
const root=path.resolve('dist');
const port=Number(process.env.NOTES_REFRESH_PORT||15186);
const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2','.woff':'font/woff','.ttf':'font/ttf','.webp':'image/webp'};
const server=http.createServer((req,res)=>{
 const p=new URL(req.url,'http://localhost').pathname;
 const file=path.resolve(root,'.'+decodeURIComponent(p));
 if(!file.startsWith(root+path.sep)&&file!==root){res.writeHead(403);return res.end();}
 const exists=existsSync(file)&&statSync(file).isFile();
 const route=['/','/notes','/settings','/status','/drive','/gallery','/apps/fixture-external'].includes(p);
 if(req.method!=='GET'||(!exists&&!route)){res.writeHead(404,{'Content-Type':'application/json'});return res.end(JSON.stringify({detail:'No static fixture route'}));}
 const target=exists?file:path.join(root,'index.html');
 res.writeHead(200,{'Content-Type':mime[path.extname(target)]||'application/octet-stream'});res.end(readFileSync(target));
});
server.listen(port,'127.0.0.1',()=>console.log(`Production static dist on loopback ${server.address().port}; no proxy`));
