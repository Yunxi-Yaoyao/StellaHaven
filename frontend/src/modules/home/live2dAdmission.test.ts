import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {createApp,h,ref,nextTick} from 'vue';
import {useLive2dAdmission} from './live2dAdmission';
let app:ReturnType<typeof createApp>|undefined;
beforeEach(()=>vi.useFakeTimers());
afterEach(()=>{app?.unmount();vi.useRealTimers();vi.unstubAllGlobals();});
it('decoration starts once at idle after business readiness and waits while hidden',async()=>{
 const ready=ref(false),active=ref(true),start=vi.fn(),idle=vi.fn(cb=>{return window.setTimeout(cb,10)});
 vi.stubGlobal('requestIdleCallback',idle);vi.stubGlobal('cancelIdleCallback',window.clearTimeout);
 app=createApp({setup(){useLive2dAdmission(ready,active,start);return()=>h('div');}});app.mount(document.createElement('div'));
 await vi.advanceTimersByTimeAsync(50);expect(start).not.toHaveBeenCalled();
 ready.value=true;active.value=false;await nextTick();await vi.advanceTimersByTimeAsync(50);expect(start).not.toHaveBeenCalled();
 active.value=true;await nextTick();await vi.advanceTimersByTimeAsync(10);expect(start).toHaveBeenCalledTimes(1);
 active.value=false;await nextTick();active.value=true;await nextTick();await vi.advanceTimersByTimeAsync(50);expect(start).toHaveBeenCalledTimes(1);
});
import {syncOwnedLive2dPlayback} from './live2dAdmission';
it('hidden media detaches only its own render/model subscriptions, never shared ticker stop',()=>{
 const render=()=>{},ticker={add:vi.fn(),remove:vi.fn(),stop:vi.fn()},app={ticker,render},model={autoUpdate:true};
 syncOwnedLive2dPlayback(app as any,model,false);expect(model.autoUpdate).toBe(false);expect(ticker.remove).toHaveBeenCalledWith(render,app);expect(ticker.stop).not.toHaveBeenCalled();
 syncOwnedLive2dPlayback(app as any,model,true);expect(model.autoUpdate).toBe(true);expect(ticker.add).toHaveBeenCalledWith(render,app,-25);expect(ticker.stop).not.toHaveBeenCalled();
});
it('unmount cancels queued idle initialization',async()=>{
 const start=vi.fn();app=createApp({setup(){useLive2dAdmission(ref(true),ref(true),start);return()=>h('div');}});app.mount(document.createElement('div'));app.unmount();app=undefined;
 await vi.runAllTimersAsync();expect(start).not.toHaveBeenCalled();
});
