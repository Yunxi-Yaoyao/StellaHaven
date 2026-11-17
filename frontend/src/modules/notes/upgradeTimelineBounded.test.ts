// Component contract with captured owned-PG input; not a real-network proof.
import {it,expect,vi,afterEach} from 'vitest';
import {createApp,h,nextTick,type App} from 'vue';
import Panel from './NoteTimelinePanel.vue';
import capture from './bounded-timeline.http.json';
const state=vi.hoisted(()=>({unknown:false,push:vi.fn(),history:vi.fn()}));
vi.mock('vue-router',()=>({useRouter:()=>({push:state.push})}));
vi.mock('../../api/client',()=>({api:vi.fn(async()=>[{id:1,name:'fixture',status:'online'}])}));
vi.mock('../../api/notes',()=>({readNoteNode:vi.fn(async()=>({node_id:1})),setNoteNode:vi.fn(),nodeTimeline:vi.fn(async()=>({items:capture.rows,has_more:false,unknown_notes_present:state.unknown,history_path:state.unknown?'/notes':null}))}));
let app:App|undefined;
afterEach(()=>{app?.unmount();document.body.innerHTML='';state.unknown=false;state.push.mockClear();state.history.mockClear();});
async function mount(){const root=document.createElement('div');document.body.append(root);app=createApp({render:()=>h(Panel,{doc:{id:'doc',workspace_id:'ws'} as any,onHistory:state.history})});app.mount(root);for(let i=0;i<30;i++)await Promise.resolve();await nextTick();}
it('renders real PG event instants in HTTP completion order without eight-hour drift',async()=>{
 await mount();const rows=[...document.querySelectorAll('li')];
 expect(rows.map(r=>r.querySelector('button')!.textContent)).toEqual(capture.rows.map(r=>r.label));
 for(let i=0;i<rows.length;i++)expect(rows[i]!.textContent).toContain(new Date(capture.rows[i]!.ts).toLocaleString());
 expect(capture.actual).toEqual(capture.expected);
});
it('makes omitted unknown history visible and points back to existing Notes recovery',async()=>{
 state.unknown=true;await mount();expect(document.body.textContent).toContain('历史保存时间未知');
 const button=[...document.querySelectorAll('button')].find(b=>b.textContent==='查看笔记列表')!;expect(button).toBeTruthy();button.click();await nextTick();expect(state.history).toHaveBeenCalledOnce();expect(state.push).not.toHaveBeenCalled();
});
