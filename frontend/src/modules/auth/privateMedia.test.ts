import {it,expect,vi,afterEach} from 'vitest';
import {auth,acceptLogin} from '../home/auth';
import {sanitizeNoteHtml} from '../notes/noteHtml';
// The implementation is imported dynamically so RED exercises existing display HTML too.
let dispose:(()=>void)|undefined;
afterEach(()=>{dispose?.();dispose=undefined;vi.unstubAllGlobals();vi.restoreAllMocks();document.body.innerHTML='';});
it('private display HTML never gives a native loader an authenticated URL',async()=>{
 const {guardPrivateMediaHtml}=await import('./privateMedia');
 const html=guardPrivateMediaHtml(sanitizeNoteHtml('<p>draft retained</p><img src="/attachments/private" alt="draft"><video src="/attachments/movie"></video>'));
 const host=document.createElement('div');host.innerHTML=html;
 expect(host.querySelector('img')?.hasAttribute('src')).toBe(false);
 expect(host.querySelector('img')?.getAttribute('data-private-src')).toBe('/attachments/private');
 expect(host.querySelector('video')?.hasAttribute('src')).toBe(false);
 expect(host.textContent).toBe('draft retained');
});
it('private srcset and SVG image href cannot bypass media admission and exports recover source URLs',async()=>{
 const {guardPrivateMediaHtml,restorePrivateMediaHtml}=await import('./privateMedia');
 const source='<img srcset="/attachments/one 1x, /attachments/two 2x"><svg><image href="/attachments/svg" /></svg>';
 const host=document.createElement('div');host.innerHTML=guardPrivateMediaHtml(sanitizeNoteHtml(source));
 expect(host.querySelector('img')?.hasAttribute('srcset')).toBe(false);
 expect(host.querySelector('img')?.getAttribute('data-private-srcset')).toBe('/attachments/one 1x, /attachments/two 2x');
 expect(host.querySelector('img')?.getAttribute('data-private-src')).toBe('');
 expect(host.querySelector('image')?.hasAttribute('href')).toBe(false);
 expect(host.querySelector('image')?.getAttribute('data-private-href')).toBe('/attachments/svg');
 const exported=restorePrivateMediaHtml(host.innerHTML);expect(exported).toContain('srcset="/attachments/one 1x, /attachments/two 2x"');expect(exported).toContain('href="/attachments/svg"');
});
it('media epoch detaches pending native sources, ignores late callbacks, resumes and cleans replacement/removal',async()=>{
 const {installPrivateMedia,guardPrivateMediaHtml,setPrivateMediaSource}=await import('./privateMedia');
 const owner={id:'media-owner',username:'fixture',display_name:'Fixture',home_bg:'x',avatar_url:'',is_admin:false,email:'',email_verified:false};
 Object.assign(auth,{me:owner,checked:true,suspended:false,sessionClosing:false,sessionGeneration:501,requestEpoch:1});
 const network=vi.fn();vi.stubGlobal('fetch',network);
 dispose=installPrivateMedia();
 const host=document.createElement('div');host.innerHTML=guardPrivateMediaHtml('<img src="/attachments/private">');document.body.append(host);
 const img=host.querySelector('img')!;
 await vi.waitFor(()=>expect(img.getAttribute('src')).toBe('/attachments/private'));
 expect(network).not.toHaveBeenCalled();
 auth.requestEpoch++;auth.suspended=true;
 expect(img.hasAttribute('src')).toBe(false);
 img.dispatchEvent(new Event('load'));await new Promise(r=>setTimeout(r,10));expect(img.hasAttribute('src')).toBe(false);
 acceptLogin(owner);await vi.waitFor(()=>expect(img.getAttribute('src')).toBe('/attachments/private'));
 Object.defineProperties(img,{naturalWidth:{value:10},complete:{value:true}});
 auth.requestEpoch++;auth.suspended=true;expect(img.getAttribute('src')).toBe('/attachments/private');
 host.remove();await vi.waitFor(()=>expect(img.hasAttribute('src')).toBe(false));
 acceptLogin(owner);const next=document.createElement('div');next.innerHTML=guardPrivateMediaHtml('<img src="/attachments/private">');document.body.append(next);
 const nextImage=next.querySelector('img')!;await vi.waitFor(()=>expect(nextImage.getAttribute('src')).toBe('/attachments/private'));
 setPrivateMediaSource(nextImage,'/assets/public.svg');await new Promise(r=>setTimeout(r,10));expect(nextImage.getAttribute('src')).toBe('/assets/public.svg');
 setPrivateMediaSource(nextImage,'/attachments/replacement');await vi.waitFor(()=>expect(nextImage.getAttribute('src')).toBe('/attachments/replacement'));
 auth.me={...owner,id:'other-owner'};expect(nextImage.hasAttribute('src')).toBe(false);
 await new Promise(r=>setTimeout(r,10));expect(nextImage.hasAttribute('src')).toBe(false);
 dispose();dispose=undefined;expect(nextImage.hasAttribute('src')).toBe(false);
});
it.each(['http://[','https://host:invalid/image'])('invalid URL %s rejects only media, retains body and valid image',async url=>{
 const {guardPrivateMediaHtml}=await import('./privateMedia');
 const host=document.createElement('div');host.innerHTML=guardPrivateMediaHtml(sanitizeNoteHtml('<p>draft intact</p><img src="'+url+'"><img src="/attachments/good">'));
 expect(host.textContent).toBe('draft intact');expect(host.querySelector('img')?.hasAttribute('src')).toBe(false);expect(host.querySelector('img:last-child')?.getAttribute('data-private-src')).toBe('/attachments/good');
});
it('imported SVG filter loaders are removed but ordinary SVG image/vector content remains',async()=>{
 const {guardPrivateMediaHtml}=await import('./privateMedia');
 const host=document.createElement('div');host.innerHTML=guardPrivateMediaHtml(sanitizeNoteHtml('<svg><defs><filter id="f"><feImage href="/attachments/filter"/></filter></defs><rect width="10"/><image href="/attachments/image"/></svg>'));
 expect(host.querySelector('feImage')).toBeNull();expect(host.querySelector('rect')).not.toBeNull();expect(host.querySelector('image')?.hasAttribute('href')).toBe(false);
});
it('untrusted note data-private metadata cannot create active javascript links or forge media sources',async()=>{
 const {guardPrivateMediaHtml,restorePrivateMediaHtml}=await import('./privateMedia');
 const result=guardPrivateMediaHtml(sanitizeNoteHtml('<a data-private-href="javascript:alert(1)">text</a><img data-private-src="/attachments/forged" src="/attachments/real">'));
 const host=document.createElement('div');host.innerHTML=result;
 expect(host.querySelector('a')?.hasAttribute('data-private-href')).toBe(false);
 expect(host.querySelector('img')?.getAttribute('data-private-src')).toBe('/attachments/real');
 expect(restorePrivateMediaHtml(result)).not.toContain('javascript:');
});
it('malformed fetch classification delegates native rejection without crashing URL parser',async()=>{
 const {privateRequest,installSessionFence}=await import('./sessionFence');
 const error=new TypeError('native invalid URL');const network=vi.fn().mockRejectedValue(error);vi.stubGlobal('fetch',network);
 const restore=installSessionFence();try{expect(privateRequest('http://[')).toBe(false);await expect(fetch('http://[')).rejects.toBe(error);expect(network).toHaveBeenCalledOnce();}finally{restore();}
});
