// Test-only mount; parent owns App.vue global integration.
import {createApp} from 'vue';
import {createPinia} from 'pinia';
import router from '../src/router';
import CommandPalette from '../src/modules/notes/CommandPalette.vue';
export function mountPaletteHarness(){
 if(document.querySelector('.command-palette-root'))return false;
 const host=document.createElement('div');document.body.append(host);
 createApp(CommandPalette,{modules:[{label:'验收笔记模块',path:'/notes'},{label:'验收服务器模块',path:'/status'}]}).use(createPinia()).use(router).mount(host);
 return true;
}
