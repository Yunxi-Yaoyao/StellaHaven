import {createApp} from 'vue';import {it,expect,vi} from 'vitest';
const m=vi.hoisted(()=>({api:vi.fn(),refresh:vi.fn()}));vi.mock('../../api/client',()=>({api:m.api}));vi.mock('../../stores/notes',()=>({useNotesStore:()=>({refreshList:m.refresh})}));
vi.mock('../home/auth',()=>({auth:{me:{id:'owner'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}}));
import HtmlConversionRow from './HtmlConversionRow.vue';
it('HTML conversion previews losses and retries uncertain commit with same import identity',async()=>{
 const calls:string[]=[];let writes=0;
 m.refresh.mockResolvedValue(undefined);m.api.mockImplementation(async(path:string,args:any)=>{if(path.endsWith('/preview'))return {converted_count:1,documents:[{source:'index.html',target:'index.md',markdown:'# text',losses:['script']}],warnings:['原文件保留']};calls.push(args.body.get('import_id'));if(++writes===1)throw Error('connection lost');return {documents:[{id:'created'}]};});
 const host=document.createElement('div');document.body.append(host);const completed=vi.fn();const file={name:'index.html',size:14,arrayBuffer:async()=>new TextEncoder().encode('<h1>text</h1>').buffer};
 const app=createApp(HtmlConversionRow,{file,target:{workspaceId:'workspace',parentId:null},onComplete:completed});app.mount(host);
 try{
  (host.querySelector('button') as HTMLButtonElement).click();await vi.waitFor(()=>expect(host.textContent).toContain('脚本交互'));
  const button=()=>[...host.querySelectorAll('button')].find(b=>/重试确认/.test(b.textContent||''))!;
  await vi.waitFor(()=>expect(host.textContent).toContain('connection lost'));
  button().click();await vi.waitFor(()=>expect(completed).toHaveBeenCalledWith(1));
  expect(calls).toHaveLength(2);expect(calls[0]).toBe(calls[1]);expect(calls[0]).toMatch(/^[0-9a-f-]{36}$/);
  expect(host.textContent).toContain('已导入');
 }finally{app.unmount();host.remove();}
});
