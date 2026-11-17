import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
vi.mock('../home/auth',async()=>{const {reactive,ref}=await import('vue');return {auth:reactive({me:{id:'fixture'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false}),security:reactive({configured:true,enabled:true,elevated:false}),securityChecked:ref(true),loadSecurity:vi.fn(async()=>{})};});
vi.mock('../../api/client',()=>({api:vi.fn(async()=>({ok:true}))}));
import {loadSecurity,auth} from '../home/auth';
import {api} from '../../api/client';
import {toasts} from '../../composables/useToast';
import SecuritySettings from './SecuritySettings.vue';
let app:App|undefined;
const tick=async()=>{for(let i=0;i<10;i++)await Promise.resolve();await nextTick();};
beforeEach(()=>{Object.assign(auth,{me:{id:'fixture'},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false});});
afterEach(()=>{app?.unmount();app=undefined;document.body.innerHTML='';toasts.splice(0);vi.clearAllMocks();});
async function mount(){const root=document.createElement('div');document.body.append(root);app=createApp(SecuritySettings);app.mount(root);await tick();return root;}
it('retired management card renders no form, request, notification or unlock',async()=>{
 const root=await mount();expect(root.querySelector('form,input,button')).toBeNull();expect(root.textContent).toBe('');
 expect(api).not.toHaveBeenCalled();expect(loadSecurity).not.toHaveBeenCalled();expect(toasts).toHaveLength(0);
});
it('retired compatibility slot remains inert across identity changes',async()=>{
 const root=await mount();auth.sessionGeneration++;auth.me={id:'other'} as never;await tick();
 expect(root.querySelector('form,input,button')).toBeNull();expect(api).not.toHaveBeenCalled();expect(loadSecurity).not.toHaveBeenCalled();expect(toasts).toHaveLength(0);
});
