import {it,expect,vi,afterEach} from 'vitest';
import {createApp,KeepAlive,h,ref,nextTick} from 'vue';
vi.mock('./backgroundMedia',()=>({useBackgroundMedia:()=>({source:ref('/fixture.mp4'),poster:ref(''),media:ref({})})}));
import BgLayer from './BgLayer.vue';
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
it('retained background pauses while its home owner is deactivated and resumes without replacing video',async()=>{
 vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}});
 const play=vi.spyOn(HTMLMediaElement.prototype,'play').mockResolvedValue();const pause=vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{});vi.spyOn(HTMLMediaElement.prototype,'load').mockImplementation(()=>{});
 const active=ref(true);const app=createApp({setup:()=>()=>h(KeepAlive,null,{default:()=>active.value?h(BgLayer,{url:'/fixture.mp4',crop:{cx:.5,cy:.5,w:1,h:1}}):null})});const host=document.createElement('div');app.mount(host);await nextTick();
 const video=host.querySelector('video');expect(video).not.toBeNull();pause.mockClear();active.value=false;await nextTick();expect(pause).toHaveBeenCalled();
 active.value=true;await nextTick();expect(host.querySelector('video')).toBe(video);expect(play).toHaveBeenCalled();app.unmount();
});
