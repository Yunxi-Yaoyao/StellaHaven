import {it, expect, vi, afterEach} from 'vitest';
import {createApp, nextTick, type App} from 'vue';
import {createPinia, setActivePinia} from 'pinia';
import {useNotesStore} from '../../stores/notes';
import DocEditor from './DocEditor.vue';
const renderer = vi.hoisted(() => ({initialize:vi.fn(),render:vi.fn(async()=>({svg:'<svg xmlns="http://www.w3.org/2000/svg"><text>local diagram</text></svg>'}))}));
vi.mock('mermaid',()=>({default:renderer}));
vi.mock('../home/auth',async()=>({auth:(await import('vue')).reactive({me:{id:'alice'},suspended:false,sessionClosing:false,sessionGeneration:1,requestEpoch:1}),refreshAccess:vi.fn(async()=>false)}));
vi.mock('vue-router',()=>({useRoute:()=>({hash:'',query:{}}),useRouter:()=>({push:vi.fn()})}));
vi.mock('./CmEditor.vue',()=>({default:{template:'<div />'}}));
let app:App|undefined;
afterEach(()=>{app?.unmount();vi.unstubAllGlobals();document.body.innerHTML='';document.head.querySelectorAll('script').forEach(s=>s.remove());});
it('DocEditor renders with the local lazy module, never a CDN script',async()=>{
 localStorage.setItem('stella_note_edit_mode','markdown');
 vi.stubGlobal('matchMedia',()=>({matches:false,addEventListener(){},removeEventListener(){}}));
 vi.stubGlobal('WebSocket',class {static OPEN=1;readyState=1;send(){}close(){}});
 vi.stubGlobal('fetch',vi.fn(async(path:string)=>new Response(JSON.stringify(path==='/documents/one'?{id:'one',workspace_id:'ws',title:'one',content:'```mermaid\nflowchart LR\nA-->B\n```',updated_at:'2026-10-16T00:00:00Z'}:[]),{status:200,headers:{'Content-Type':'application/json'}})));
 const root=document.createElement('div');document.body.append(root);const pinia=createPinia();setActivePinia(pinia);const store=useNotesStore();store.userId='alice';store.workspaceId='ws';
 app=createApp(DocEditor,{docId:'one'}).use(pinia);app.mount(root);
 for(let i=0;i<20;i++){await new Promise(r=>setTimeout(r,5));await nextTick();}
 expect(root.querySelector('.mermaid svg')?.textContent).toContain('local diagram');
 expect(document.head.querySelector('script[src*="cdn"]')).toBeNull();
});
