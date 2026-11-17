import {afterEach,expect,it,vi} from 'vitest';
import {createApp,nextTick,type App} from 'vue';
import {createMemoryHistory,createRouter} from 'vue-router';
import ServersSideBar from '../servers/ServersSideBar.vue';
import {saveDriveBackground} from '../drive/driveBackground';
import {onClientPreferenceChange} from './clientPreferenceEvents';
let app:App|undefined;
afterEach(()=>{app?.unmount();app=undefined;localStorage.clear();document.body.innerHTML='';});
it('original server fold/tools and drive persistence actions notify account synchronization',async()=>{
  const changed=vi.fn(),stop=onClientPreferenceChange(changed);
  try{
    const router=createRouter({history:createMemoryHistory(),routes:[{path:'/status',component:{template:'<div/>'}}]});await router.push('/status');await router.isReady();
    const root=document.createElement('div');document.body.append(root);app=createApp(ServersSideBar);app.use(router);app.mount(root);
    root.querySelector<HTMLButtonElement>('.fold-btn')!.click();await nextTick();expect(localStorage.getItem('stella_servers_fold')).toBe('1');expect(changed).toHaveBeenNthCalledWith(1,'stella_servers_fold','1');
    root.querySelector<HTMLButtonElement>('[aria-label="展开列表"]')!.click();await nextTick();const tools=[...root.querySelectorAll('button')].find(b=>b.textContent?.includes('工具'))!;tools.click();await nextTick();expect(localStorage.getItem('stella_tools_open')).toBe('1');expect(changed).toHaveBeenCalledTimes(3);
    saveDriveBackground('image');expect(localStorage.getItem('stella_drive_bg_mode')).toBe('image');expect(localStorage.getItem('__stella_drive_bg_mode__')).toBe('image');expect(changed).toHaveBeenCalledTimes(4);
  }finally{stop();}
});
// Supplemental wiring guard: retain original per-control persistence (legacy source contracts).
const sources=import.meta.glob(['../../App.vue','../servers/ServerWorldMap.vue','../servers/OverviewView.vue','../notes/DocEditor.vue','../notes/NotesPage.vue','../drive/ConnectionPanel.vue'],{query:'?raw',import:'default',eager:true});
it.each([
  ['../../App.vue','stella_sidebar_fold'],['../servers/ServerWorldMap.vue','stella_server_world_map_collapsed'],['../servers/OverviewView.vue','stella_mon_mode'],['../notes/DocEditor.vue','stella_note_edit_mode'],['../notes/NotesPage.vue','stella_list_fold'],['../drive/ConnectionPanel.vue','stella_drive_bg_mode'],
])('retains original persistence and a bounded signal for %s', (path,key)=>{
  const source=String(sources[path]);expect(source).toContain('localStorage.setItem(');expect(new RegExp(`notifyClientPreferenceChange\\(['\"]${key}['\"],`).test(source)).toBe(true);
});
