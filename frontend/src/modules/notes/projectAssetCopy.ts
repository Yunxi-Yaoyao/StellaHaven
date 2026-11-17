import {ref,watch,type InjectionKey} from 'vue';
import type {FileProject} from '../../api/projectFiles';
export const PROJECT_ASSET_MIME='application/x-stella-project-image+json';
export const projectCatalogKey:InjectionKey<{projectFor:(id:string|null)=>FileProject|null;identityFor?:(id:string|null)=>{id:string}|null;assetFor?:(id:string|null)=>ProjectAsset|null}>=Symbol('project-file-catalog');
export interface ProjectAsset {root:string;file:string;path:string;mime:string}
const uuid=/^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i;
export function parseProjectAsset(raw:string):ProjectAsset|null {
 try{const v=JSON.parse(raw);return v&&uuid.test(v.root)&&uuid.test(v.file)&&typeof v.path==='string'&&v.path.length>0&&v.path.length<=1024&&typeof v.mime==='string'&&v.mime.startsWith('image/')?{root:v.root,file:v.file,path:v.path,mime:v.mime}:null;}catch{return null;}
}
export function dragProjectAsset(event:DragEvent,project:FileProject,id:string):boolean {
 const file=project.files.find(f=>f.id===id);if(!file?.mime.startsWith('image/')||!event.dataTransfer)return false;
 event.dataTransfer.setData(PROJECT_ASSET_MIME,JSON.stringify({root:project.id,file:file.id,path:file.path,mime:file.mime}));
 event.dataTransfer.effectAllowed='copyMove';return true;
}
/** Bound each transport attempt, not the idempotent user operation. */
export const PROJECT_ASSET_COPY_TIMEOUT_MS=30000;
/** One explicit user operation: uncertain ACK retains its exact request ID. */
export function createProjectAssetCopy(options:{
 copy:(root:string,path:string,target:string,id:string,signal?:AbortSignal)=>Promise<{url:string;filename:string}>;
 target:()=>string|null;capture:()=>()=>boolean;insert:(markdown:string)=>void;
}){
 const pending=ref(false),busy=ref(false),error=ref('');
 let task:{asset:ProjectAsset;target:string;id:string}|null=null,disposed=false;
 let flight:{cancel:(message:string)=>void}|null=null;
 const uncertain='复制结果待确认，可重试或取消这次插入；服务端可能已有独立附件，取消不会删除它。';
 async function retry(){
  if(!task||busy.value||disposed||options.target()!==task.target)return;
  const current=options.capture(),operation=task;if(!current())return;
  const controller=new AbortController();
  let rejectAbort!:(reason:Error)=>void,stop=()=>{},timer:ReturnType<typeof setTimeout>|undefined;
  const aborted=new Promise<never>((_,reject)=>{rejectAbort=reject;});
  const attempt={cancel:(message:string)=>{
   if(flight!==attempt)return;
   // Retire ownership before aborting: even an ignored abort/late finally
   // cannot release a replacement attempt or publish its ACK.
   flight=null;clearTimeout(timer);stop();busy.value=false;error.value=message;
   controller.abort();rejectAbort(new DOMException(message,'AbortError'));
  }};
  flight=attempt;busy.value=true;error.value='';
  stop=watch(()=>current()&&options.target()===operation.target,valid=>{
   if(!valid)attempt.cancel(uncertain);
  },{flush:'sync'});
  timer=setTimeout(()=>attempt.cancel('图片复制等待超时。'+uncertain),PROJECT_ASSET_COPY_TIMEOUT_MS);
  const ownsFlight=()=>!disposed&&task===operation&&flight===attempt;
  try{
   // Race independently of fetch's abort handling (including a held body).
   const result=await Promise.race([options.copy(operation.asset.root,operation.asset.path,operation.target,operation.id,controller.signal),aborted]);
   if(!ownsFlight())return;
   if(!current()||options.target()!==operation.target){error.value=uncertain;return;}
   if(!/^\/attachments\/[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i.test(result.url))throw Error('复制未返回独立附件地址');
   const name=String(result.filename).replace(/[\r\n]/g,' ').replace(/[\\\[\]]/g,'\\$&');
   options.insert(`![${name}](${result.url})`);task=null;pending.value=false;
  }catch(e){if(ownsFlight())error.value=(e instanceof Error?e.message:'图片复制失败')+'。'+uncertain;}
  finally{clearTimeout(timer);stop();if(flight===attempt){flight=null;busy.value=false;}}
 }
 async function start(asset:ProjectAsset){
  if(pending.value||disposed)return;
  const target=options.target();if(!target)return;
  task={asset,target,id:crypto.randomUUID()};pending.value=true;await retry();
 }
 function discard(){flight?.cancel(uncertain);task=null;pending.value=false;error.value='';}
 function dispose(){disposed=true;discard();}
 return {pending,busy,error,start,retry,discard,dispose};
}
