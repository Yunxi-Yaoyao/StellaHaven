/** Editor-only projection. The API and authorization continue to use exact full URIs. */
export interface WebCallback {origin:string;paths:string[]}
export interface CallbackDraft {web:WebCallback[];native:string[];compatibility:string[];order:string[]}
const nativeImmich='app.immich:///oauth-callback';
function validHost(url:URL){return url.hostname.startsWith('[')||(url.hostname.length<=253&&url.hostname.replace(/\.$/,'').split('.').every(label=>/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label)));}
function webParts(uri:string):WebCallback|null {
 try{
  const raw=/^(https:\/\/[^/?#]+)(\/[^?#]*)$/.exec(uri);
  if(!raw)return null;
  const url=new URL(uri);
  if(url.protocol!=='https:'||!validHost(url)||url.username||url.password||url.search||url.hash||/[\s\\*\x00-\x1f\x7f]/.test(decodeURIComponent(uri)))return null;
  // Never normalize an old registration while importing it.
  if(raw[2]!==url.pathname)return null;
  return {origin:raw[1]!,paths:[raw[2]!]};
 }catch{return null;}
}
export function importCallbacks(uris:readonly string[]):CallbackDraft {
 const result:CallbackDraft={web:[],native:[],compatibility:[],order:[...uris]};
 for(const uri of uris){
  if(uri===nativeImmich){result.native.push(uri);continue;}
  const parsed=webParts(uri);
  if(!parsed){result.compatibility.push(uri);continue;}
  const row=result.web.find(row=>row.origin===parsed.origin);
  if(row)row.paths.push(...parsed.paths);else result.web.push(parsed);
 }
 return result;
}
export function expandCallbacks(model:CallbackDraft):string[]{
 const values=[...model.web.flatMap(row=>row.paths.map(path=>row.origin+path)),...model.native,...model.compatibility];
 return [...model.order.filter(uri=>values.includes(uri)),...values.filter(uri=>!model.order.includes(uri))];
}
export function callbackProblem(model:CallbackDraft,previous:readonly string[]):string {
 for(const [index,row] of model.web.entries()){
  let origin:URL;
  try{origin=new URL(row.origin);}catch{return `应用地址 ${index+1}：请填写完整 HTTPS 地址（含端口时一并填写）`;}
  if(origin.protocol!=='https:'||!/^https:\/\/[^/?#]+$/.test(row.origin)||!validHost(origin)||origin.username||origin.password||/[\s\\*%\x00-\x1f\x7f]/.test(row.origin))return `应用地址 ${index+1}：只填 HTTPS 域名与可选端口，不含路径、账号或通配符`;
  if(!row.paths.length)return `应用地址 ${index+1}：至少填写一个回调用途路径`;
  for(const path of row.paths){
   if(!path.startsWith('/')||path.startsWith('//')||!webParts(row.origin+path))return `回调用途路径 ${index+1}：以单个 / 开头，不含域名、查询、片段、通配符或空格`;
  }
 }
 if(model.native.some(uri=>uri!==nativeImmich||!previous.includes(uri))||model.compatibility.some(uri=>!previous.includes(uri)))return '旧登记只能保留或明确移除，不能借兼容列表新增地址';
 const values=[...model.web.flatMap(row=>row.paths.map(path=>row.origin+path)),...model.native,...model.compatibility];
 if(!values.length||values.length>32)return '请登记 1 到 32 条精确回调';
 if(new Set(values).size!==values.length)return '回调地址重复，请删除重复项';
 if(values.some(uri=>uri.length>2048))return '每条回调地址最多 2048 个字符';
 return '';
}
export function callbackDiff(before:readonly string[],after:readonly string[]){
 return {added:after.filter(uri=>!before.includes(uri)),removed:before.filter(uri=>!after.includes(uri))};
}
