import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {createPinia,setActivePinia} from 'pinia';
import {useNotesStore} from '../../stores/notes';
import {auth} from '../home/auth';
const m=vi.hoisted(()=>({refresh:vi.fn()}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}),refreshAccess:m.refresh}));
function ws(id:string){return {id,name:id,user_id:'alice'};}
let requests:{path:string;method:string}[];
let resume:(v:boolean)=>void;
beforeEach(()=>{
 setActivePinia(createPinia());Object.assign(auth,{me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false});requests=[];
 m.refresh.mockReset();m.refresh.mockImplementation(()=>new Promise<boolean>(r=>resume=r));
 vi.stubGlobal('fetch',vi.fn(async(path:string,options:RequestInit={})=>{
  const method=options.method??'GET';requests.push({path,method});
  if(method==='DELETE')return requests.filter(r=>r.method==='DELETE').length===1?new Response('',{status:401}):new Response(null,{status:204});
  if(path.startsWith('/workspaces/'))return new Response(JSON.stringify([ws('a'),ws('c')]));
  if(path.startsWith('/documents/'))return new Response('[]');
  throw Error('Unexpected request '+path);
 }));
});
afterEach(()=>vi.unstubAllGlobals());
function setup(){const s=useNotesStore();s.userId='alice';s.workspaceId='a';s.workspaces=['a','b','c'].map(ws);return s;}
async function held(){await vi.waitFor(()=>expect(m.refresh).toHaveBeenCalledTimes(1));}
it('control: unchanged current admission allows ordinary 401 refresh retry',async()=>{
 const s=setup();const pending=s.deleteWorkspaceBatch(['b']);await held();resume(true);const result=await pending;
 expect(requests.filter(r=>r.method==='DELETE')).toHaveLength(2);expect(result.results).toEqual([{id:'b',status:'deleted'}]);
});
it.each(['owner','generation','requestEpoch'])('control: authentication %s changes suppress the held retry',async(boundary)=>{
 const s=setup();const pending=s.deleteWorkspaceBatch(['b']);await held();
 if(boundary==='owner')auth.me={id:'bob'} as any;else if(boundary==='generation')auth.sessionGeneration++;else auth.requestEpoch++;
 resume(true);await pending;expect(requests.filter(r=>r.method==='DELETE')).toHaveLength(1);
});
it.each(['workspace-leave-reentry','component-unmount'])('must not dispatch DELETE after %s invalidates held refresh admission',async(boundary)=>{
 const s=setup();let mounted=true;const pending=s.deleteWorkspaceBatch(['b','c'],()=>mounted);await held();
 if(boundary==='workspace-leave-reentry'){s.workspaceId='c';s.workspaceId='a';}else mounted=false;
 resume(true);const result=await pending;
 console.log(JSON.stringify({boundary,requests,result}));
 expect(requests.filter(r=>r.method==='DELETE'),'invalidated admission must stop the automatic destructive retry').toHaveLength(1);
});
