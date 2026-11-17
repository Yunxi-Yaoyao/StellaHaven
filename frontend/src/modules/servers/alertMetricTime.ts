// IANA is a display zone. API endpoints always remain absolute instants.
export function browserZone():string {return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';}
const formatters=new Map<string,Intl.DateTimeFormat>();
export function localTime(instant:string,zone:string):string {
 const date=new Date(instant);
 let formatter=formatters.get(zone);
 if(!formatter){
  formatter=new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
  if(formatters.size>=32)formatters.clear();
  formatters.set(zone,formatter);
 }
 const parts=formatter.formatToParts(date);
 const p=Object.fromEntries(parts.map(v=>[v.type,v.value]));
 const fraction=date.getUTCMilliseconds()?'.'+String(date.getUTCMilliseconds()).padStart(3,'0'):'';
 return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}${fraction}`;
}
export interface OriginalEndpoint {local:string;zone:string;instant:string}
export function sameLocal(a:string,b:string):boolean {return Date.parse(a+'Z')===Date.parse(b+'Z');}
export function utcInstant(instant:string):string {
 const fraction=instant.match(/\.(\d+)(?=Z|[+-]\d\d:\d\d$)/)?.[1];
 return new Date(instant).toISOString().replace(/\.\d{3}Z$/,fraction?'.'+fraction+'Z':'Z');
}
function instantNanos(instant:string):bigint {
 const utc=utcInstant(instant),fraction=utc.match(/\.(\d+)Z$/)?.[1]||'';
 return BigInt(Date.parse(utc.replace(/\.\d+Z$/,'Z')))*1000000n+BigInt(fraction.padEnd(9,'0'));
}
export function validWindow(start:string,end:string):boolean {
 const duration=instantNanos(end)-instantNanos(start);
 return duration>0n && duration<=31n*86400n*1000000000n;
}
// Enumerate surrounding IANA offsets, then round-trip every candidate. Never
// let Date's host-zone DST normalization silently choose an offset or fill a gap.
export function localCandidates(local:string,zone:string):string[] {
 if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?$/.test(local))throw new Error('请选择完整日期与时间喵~');
 const normalized=local.length===16?local+':00':local;
 const wall=Date.parse(normalized+'Z');
 // Validate the calendar before searching offsets; Date.parse normalizes Feb 30.
 const canonical=normalized.includes('.')?normalized.split('.')[0]+'.'+normalized.split('.')[1]!.padEnd(3,'0'):normalized;
 if(!Number.isFinite(wall)||localTime(new Date(wall).toISOString(),'UTC')!==canonical.replace(/\.000$/,''))throw new Error('日期或时间无效喵~');
 const offsets=new Set<number>();
 for(let hour=-48;hour<=48;hour++){
  const instant=new Date(wall+hour*3600000).toISOString();
  offsets.add(Date.parse(localTime(instant,zone)+'Z')-Date.parse(instant));
 }
 const target=localTime(new Date(wall).toISOString(),'UTC');
 return [...offsets].map(offset=>new Date(wall-offset).toISOString()).filter(instant=>localTime(instant,zone)===target).sort();
}
export function resolveLocal(local:string,zone:string,original?:OriginalEndpoint,choice=''):string {
 if(original && sameLocal(original.local,local) && original.zone===zone)return original.instant;
 const candidates=localCandidates(local,zone);
 if(!candidates.length)throw new Error('这个当地时间不存在（时区跳时），请重新选择喵~');
 if(candidates.length>1){
  if(candidates.includes(choice))return choice;
  throw new Error('这个当地时间重复出现，请明确选择第一次或第二次喵~');
 }
 return candidates[0]!;
}
