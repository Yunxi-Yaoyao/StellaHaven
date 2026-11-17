import {it,expect,vi,afterEach} from 'vitest';
import {createApp,h,ref,nextTick,type App} from 'vue';
import NoteTimelinePanel from './NoteTimelinePanel.vue';
const m=vi.hoisted(()=>({read:vi.fn(),write:vi.fn(),catalog:vi.fn(),timeline:vi.fn()}));
vi.mock('../../api/client',()=>({api:m.catalog}));
vi.mock('../../api/notes',()=>({readNoteNode:m.read,setNoteNode:m.write,nodeTimeline:m.timeline}));
vi.mock('vue-router',()=>({useRouter:()=>({push:vi.fn()})}));
let app:App|undefined;
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';vi.resetAllMocks();});
async function settle(){for(let i=0;i<20;i++)await Promise.resolve();await nextTick();}
it.each(['resolve','reject'])('document switch aborts a held write and loads the new association before stale %s',async outcome=>{
 m.catalog.mockResolvedValue([{id:1,name:'One'},{id:2,name:'Two'}]);m.read.mockImplementation(async(id:string)=>({node_id:id==='one'?1:2}));m.timeline.mockResolvedValue({items:[],has_more:false});
 let resolve!:()=>void,reject!:(e:Error)=>void;const held=new Promise<void>((yes,no)=>{resolve=yes;reject=no;});m.write.mockReturnValue(held);
 const doc=ref({id:'one',workspace_id:'ws'});const root=document.createElement('div');document.body.append(root);app=createApp({render:()=>h(NoteTimelinePanel,{doc:doc.value as any})});app.mount(root);await settle();
 const save=()=>[...document.querySelectorAll('button')].find(b=>b.textContent==='保存关联')!;save().click();await settle();const signal=m.write.mock.calls[0]![2] as AbortSignal;
 doc.value={id:'two',workspace_id:'ws'};await settle();expect(signal.aborted).toBe(true);expect(m.read.mock.calls.map(c=>c[0])).toEqual(['one','two']);expect(save().disabled).toBe(false);expect(document.querySelector<HTMLSelectElement>('select')?.value).toBe('2');
 if(outcome==='resolve')resolve();else reject(Error('stale'));await settle();expect(document.querySelector<HTMLSelectElement>('select')?.value).toBe('2');expect(document.body.textContent).not.toContain('失败');expect(m.read).toHaveBeenCalledTimes(2);
});
