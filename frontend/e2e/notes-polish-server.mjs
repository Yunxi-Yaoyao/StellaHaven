// Both modes serve the real App, without any backend/proxy connection.
import {createServer} from 'vite';
import vue from '@vitejs/plugin-vue';
import http from 'node:http';
import {readFileSync,existsSync,statSync} from 'node:fs';
import path from 'node:path';
if(process.env.STELLA_NOTES_PRODUCT_BUILD==='1'){
 const root=path.resolve('dist');
 const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.woff2':'font/woff2','.woff':'font/woff','.ttf':'font/ttf'};
 http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost'),file=path.resolve(root,'.'+decodeURIComponent(url.pathname));
  if(!file.startsWith(root+path.sep)&&file!==root){res.writeHead(403);res.end();return;}
  const target=existsSync(file)&&statSync(file).isFile()?file:path.join(root,'index.html');
  res.writeHead(200,{'Content-Type':types[path.extname(target)]||'application/octet-stream'});res.end(readFileSync(target));
 }).listen(15185,'127.0.0.1',()=>console.log('Isolated notes/global product build: 15185, no proxy'));
}else{
 const server=await createServer({configFile:false,plugins:[vue()],server:{host:'127.0.0.1',port:15185,strictPort:true,proxy:{}},cacheDir:'node_modules/.vite-notes-polish'});await server.listen();
}
