// Syntax feedback only; the API independently validates every write.
function hostName(raw:string):string {
 if(!raw||/[\s\/@%\\?#\[\]]/u.test(raw))throw Error('请填写有效 IP 或主机名，不能是裸数字');
 if(raw.includes(':')){
  try{const u=new URL(`http://[${raw}]/`);return u.hostname.slice(1,-1);}catch{throw Error('IPv6 地址无效');}
 }
 if(/^[0-9.]+$/.test(raw)){
  if(!/^\d+\.\d+\.\d+\.\d+$/.test(raw)||raw.split('.').some(s=>! /^(0|[1-9]\d{0,2})$/.test(s)||Number(s)>255))throw Error('请填写有效 IP 或主机名，不能是裸数字');
  return raw;
 }
 let host:string;try{host=new URL(`http://${raw}/`).hostname;}catch{throw Error('目标主机名无效');}
 if(host.length>253||!/[a-z]/i.test(host)||!host.replace(/\.$/,'').split('.').every(s=>/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(s)))throw Error('目标主机名无效');
 return host;
}
function portNumber(raw:string):number {
 if(!/^[0-9]+$/.test(raw)||Number(raw)<1||Number(raw)>65535)throw Error('端口需要 1–65535');
 return Number(raw);
}
export function monitorTarget(type:string,raw:string):string {
 if(/[\p{C}]/u.test(raw))throw Error('目标不能含控制字符');
 const value=raw.trim().replace(/：/g,':');
 if(!value||value.length>256||/[\s\\]/u.test(value))throw Error('目标不能为空或含空白、反斜线，且最多 256 字符');
 if(type==='ping'){
  if(/[\[\]]/.test(value))throw Error('Ping 请填写 IP 或主机名，不含路径、端口');
  return hostName(value);
 }
 if(type==='tcp'||type==='udp'){
  const m=value.match(/^(\[[^\[\]]+\]|[^:]+):([0-9]+)$/);
  if(!m)throw Error('TCP/UDP 需要主机:端口；IPv6 使用 [地址]:端口');
  if(m[1]!.startsWith('[')&&!m[1]!.includes(':'))throw Error('方括号仅用于 IPv6 地址');
  const host=hostName(m[1]!.startsWith('[')?m[1]!.slice(1,-1):m[1]!);
  return `${host.includes(':')?'['+host+']':host}:${portNumber(m[2]!)}`;
 }
 if(type!=='http'&&type!=='https')throw Error('监控类型不正确');
 const m=value.match(/^(https?):\/\/(\[[^\[\]]+\]|[^\/:?#@]+)(?::([0-9]+))?([/?#].*)?$/i);
 if(!m||m[1]!.toLowerCase()!==type)throw Error('请填写协议匹配的 HTTP(S) URL，不含账号密码');
 const host=hostName(m[2]!.startsWith('[')?m[2]!.slice(1,-1):m[2]!);
 return `${type}://${host.includes(':')?'['+host+']':host}${m[3]?':'+portNumber(m[3]):''}${m[4]??''}`;
}
export function monitorTargetError(type:string,value:string):string {
 try{monitorTarget(type,value);return '';}catch(e){return e instanceof Error?e.message:'目标格式无效';}
}
export function monitorWriteError(e:any,fallback:string):string {
 if(typeof e?.detail==='string')return e.detail;
 if(Array.isArray(e?.detail))return e.detail.map((d:any)=>typeof d?.msg==='string'?d.msg.replace(/^Value error, /,''):'目标或采样设置不正确').join('；');
 return e instanceof Error?e.message:fallback;
}
