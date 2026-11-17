import {createApp,nextTick,type App} from 'vue';
import {it,expect,vi,afterEach} from 'vitest';
import AvatarCropper from './AvatarCropper.vue';
let app:App;
afterEach(()=>{app?.unmount();document.body.innerHTML='';vi.unstubAllGlobals();vi.restoreAllMocks();});
it('uses the fenced upload request and keeps a retryable error after network failure',async()=>{
 vi.stubGlobal('Image',class{naturalWidth=400;naturalHeight=300;onload?:()=>void;set src(_s:string){queueMicrotask(()=>this.onload?.());}});
 URL.createObjectURL=vi.fn(()=> 'blob:test');
 vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:vi.fn()} as unknown as CanvasRenderingContext2D);
 vi.spyOn(HTMLCanvasElement.prototype,'toBlob').mockImplementation(cb=>cb(new Blob(['png'],{type:'image/png'})));
 const raw=vi.fn();vi.stubGlobal('fetch',raw);
 const request=vi.fn().mockRejectedValue(new Error('网络断开，请重试'));
 const root=document.createElement('div');document.body.append(root);app=createApp(AvatarCropper,{request});app.mount(root);await nextTick();
 const file=document.querySelector('input[type=file]')!;Object.defineProperty(file,'files',{value:[new File(['image'],'test.png')]});file.dispatchEvent(new Event('change'));await new Promise(r=>setTimeout(r,0));await nextTick();
 const confirm=[...document.querySelectorAll('button')].find(b=>b.textContent?.includes('裁这个'))!;expect(confirm).toBeTruthy();confirm.click();await new Promise(r=>setTimeout(r,0));await nextTick();
 expect(request).toHaveBeenCalledWith('/auth/avatar',expect.objectContaining({method:'POST',body:expect.any(FormData)}));expect(raw).not.toHaveBeenCalled();expect(document.body.textContent).toContain('网络断开，请重试');expect(confirm.disabled).toBe(false);
});
