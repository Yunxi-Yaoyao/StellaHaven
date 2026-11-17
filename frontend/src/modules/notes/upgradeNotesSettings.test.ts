import {it,expect,vi,afterEach} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
import {createPinia} from 'pinia';
const m=vi.hoisted(()=>({get:vi.fn(),patch:vi.fn(),auth:{me:{id:'alice'},sessionGeneration:1,requestEpoch:1,suspended:false,sessionClosing:false}}));
vi.mock('../../api/notes',async()=>({...await vi.importActual<any>('../../api/notes'),getNotesPreferences:m.get,patchNotesPreferences:m.patch}));
vi.mock('../home/auth',()=>({auth:m.auth,refreshAccess:vi.fn(async()=>false)}));
let app:App|undefined;
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';vi.resetAllMocks();});
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();await nextTick();};
it('notes settings changes default and reenables asking via autosave with verified readback',async()=>{
 m.get.mockResolvedValueOnce({revision:2,delete_action:'permanent',ask_before_delete:false}).mockResolvedValueOnce({revision:3,delete_action:'permanent',ask_before_delete:true});m.patch.mockResolvedValue({revision:3});
 const modules=import.meta.glob('./NotesSettings.vue');expect(modules['./NotesSettings.vue'],'independent Notes settings exists').toBeTypeOf('function');
 const component=(await modules['./NotesSettings.vue']!() as any).default;const root=document.createElement('div');document.body.append(root);app=createApp(component).use(createPinia());app.mount(root);await flush();
 const checkbox=document.querySelector<HTMLInputElement>('[aria-label="删除前询问"]')!;expect(checkbox.checked).toBe(false);checkbox.click();await flush();expect(m.patch).toHaveBeenCalledWith({expected_revision:2,delete_action:'permanent',ask_before_delete:true});expect(document.body.textContent).toContain('已同步');expect(document.querySelectorAll('[aria-label="删除前询问"]')).toHaveLength(1);expect(document.querySelectorAll('.reading-settings input[type=checkbox]')).toHaveLength(2);
});
