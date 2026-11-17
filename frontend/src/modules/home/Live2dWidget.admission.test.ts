import {it,expect,vi,afterEach} from 'vitest';
import {createApp,nextTick} from 'vue';
import Live2dWidget from './Live2dWidget.vue';
import {auth} from './auth';
import {navigation} from '../../stores/navigation';
let app:ReturnType<typeof createApp>|undefined;
afterEach(()=>{app?.unmount();vi.unstubAllGlobals();});
it('real widget defers runtime until verified owner navigation is ready and browser is idle',async()=>{
 Object.assign(auth,{checked:false,me:{id:'fixture'},suspended:false,sessionClosing:false});navigation.loaded=false;navigation.error='';
 let idle:IdleRequestCallback|undefined;vi.stubGlobal('requestIdleCallback',vi.fn(cb=>{idle=cb;return 7}));vi.stubGlobal('cancelIdleCallback',vi.fn());
 app=createApp(Live2dWidget);app.mount(document.createElement('div'));await nextTick();
 expect(document.querySelector('script[src="/live2dcubismcore.min.js"]')).toBeNull();expect(idle).toBeUndefined();
 auth.checked=true;await nextTick();expect(idle).toBeUndefined();navigation.loaded=true;await nextTick();expect(idle).toBeDefined();
 idle!({didTimeout:false,timeRemaining:()=>50});await nextTick();expect(document.querySelector('script[src="/live2dcubismcore.min.js"]')).not.toBeNull();
});
