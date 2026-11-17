import {readFileSync} from 'node:fs';
import {it,expect,vi,afterEach} from 'vitest';
// Exercise the actual App capture handler, without importing background stores.
const source=readFileSync('src/App.vue','utf8');
const body=source.match(/function drawerKeys\(event: KeyboardEvent\) \{([\s\S]*?)\n\}/)![1].replace(/querySelectorAll<HTMLElement>/g,'querySelectorAll');
function handler(close:()=>void){return new Function('drawerActive','loginVisible','closeMobile',`return function(event){${body}}`)({value:true},{value:false},close);}
afterEach(()=>{document.body.innerHTML='';});
it.each(['notification-surface','nested-incident'])('lets the real teleported %s dialog own Escape before mobile drawer capture',kind=>{
 const close=vi.fn(),detail=vi.fn(),capture=handler(close);document.addEventListener('keydown',capture,true);
 const dialog=document.createElement('section');dialog.className='detail-dialog '+kind;dialog.setAttribute('role','dialog');dialog.innerHTML='<button>关闭详情</button>';document.body.append(dialog);dialog.addEventListener('keydown',detail);
 try{dialog.querySelector('button')!.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));expect(close).not.toHaveBeenCalled();expect(detail).toHaveBeenCalledOnce();}finally{document.removeEventListener('keydown',capture,true);}
});
it('still closes the actual mobile navigation on its own Escape',()=>{const close=vi.fn(),capture=handler(close);document.addEventListener('keydown',capture,true);const button=document.createElement('button');document.body.append(button);try{button.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));expect(close).toHaveBeenCalledOnce();}finally{document.removeEventListener('keydown',capture,true);}});
