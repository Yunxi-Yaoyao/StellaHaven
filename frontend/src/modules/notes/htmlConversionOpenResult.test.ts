import {createApp} from 'vue';import {it,expect,vi} from 'vitest';
const m=vi.hoisted(()=>({api:vi.fn(),refresh:vi.fn()}));
vi.mock('../../api/client',()=>({api:m.api}));vi.mock('../../stores/notes',()=>({useNotesStore:()=>({refreshList:m.refresh})}));
vi.mock('../home/auth',()=>({auth:{me:{id:'owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}}));
import HtmlConversionRow from './HtmlConversionRow.vue';
it('conversion opens a converted article before earlier ZIP directories without losing other results',async()=>{
 const docs=[{id:'folder',title:'01-岗位依据',path:'01-岗位依据'},{id:'old-md',title:'JD',path:'01-岗位依据/JD.md'},{id:'converted',title:'index',path:'index.md'}];
 m.api.mockImplementation(async(path:string)=>path.endsWith('/preview')?{converted_count:1,documents:[{source:'index.html',target:'index.md',markdown:'# 内容',losses:[]}],warnings:[]}:{documents:docs});m.refresh.mockResolvedValue(undefined);
 const onCreated=vi.fn(),host=document.createElement('div');document.body.append(host);
 const app=createApp(HtmlConversionRow,{file:{name:'原资料.zip',size:10,arrayBuffer:async()=>new Uint8Array(10).buffer},target:{workspaceId:'w',parentId:null},onCreated});app.mount(host);
 try{host.querySelector<HTMLButtonElement>('button')!.click();await vi.waitFor(()=>expect(onCreated).toHaveBeenCalledTimes(1));
  const emitted=onCreated.mock.calls[0]![0];expect(emitted.map((d:any)=>d.id)).toEqual(['converted','folder','old-md']);expect(emitted).toHaveLength(3);
 }finally{app.unmount();host.remove();}
});
