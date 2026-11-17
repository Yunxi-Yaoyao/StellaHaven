import {monitorTarget} from './monitorTarget';
export const monitorTypes=['ping','tcp','udp','http','https'] as const;
export type MonitorType=typeof monitorTypes[number];
export const defaultPorts:Record<string,string>={tcp:'80',udp:'53',http:'80',https:'443'};
export const orderedTypes=(types:readonly string[])=>monitorTypes.filter(t=>types.includes(t));
export const portTypes=(types:readonly string[])=>orderedTypes(types).filter(t=>t!=='ping');
export function joinMonitorTarget(type:string,host:string,port:string,suffix=''):string{
 const canonical=monitorTarget('ping',host);
 if(type==='ping')return canonical;
 if(!/^\d+$/.test(port)||Number(port)<1||Number(port)>65535)throw Error('端口需要 1–65535 的整数');
 const endpoint=`${canonical.includes(':')?'['+canonical+']':canonical}:${Number(port)}`;
 return monitorTarget(type,(type==='http'||type==='https'?type+'://':'')+endpoint+suffix);
}
export function splitMonitorTarget(type:string,target:string){
 try{
  monitorTarget(type,target);
  if(type==='ping')return {host:target,port:'',suffix:'',legacy:false};
  const match=type==='tcp'||type==='udp'?target.match(/^(\[[^\]]+\]|[^:]+):(\d+)$/):target.match(/^https?:\/\/(\[[^\]]+\]|[^\/:?#@]+)(?::(\d+))?([/?#].*)?$/i);
  if(!match)throw Error('legacy');
  return {host:match[1]!.replace(/^\[|\]$/g,''),port:match[2]??defaultPorts[type]??'',suffix:match[3]??'',legacy:false};
 }catch{return {host:target,port:'',suffix:'',legacy:true};}
}
export function batchTargets(types:readonly string[],host:string,ports:string){
 const ordered=orderedTypes(types),withPorts=portTypes(types),segments=ports.split('/');
 if(!ordered.length)throw Error('请选择至少一种监控类型');
 if(withPorts.length!== (ports===''?0:segments.length))throw Error(`需要 ${withPorts.length} 个端口，按标签顺序用 / 分隔`);
 const byType=Object.fromEntries(withPorts.map((t,i)=>[t,segments[i]!.trim()]));
 return ordered.map(type=>({type,target:joinMonitorTarget(type,host,byType[type]??'')}));
}
