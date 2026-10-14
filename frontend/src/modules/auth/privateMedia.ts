import {watch, type Directive} from 'vue';
import {auth} from '../home/auth';
import {privateRequest,sessionBlocked,assertSession} from './sessionFence';

/** Display URLs only: never mutate Markdown or ProseMirror's source attributes. */
export function setPrivateMediaSource(el:Element,url:string,attr='src') {
  if(url && privateRequest(url)) {
    el.removeAttribute(attr);
    el.setAttribute(`data-private-${attr}`,url);
  } else {
    el.removeAttribute(`data-private-${attr}`);
    if(url)el.setAttribute(attr,url);else el.removeAttribute(attr);
  }
}
export const vPrivateSrc:Directive<HTMLElement,string>={
  beforeMount:(el,{value})=>setPrivateMediaSource(el,value),
  updated:(el,{value,oldValue})=>{if(value!==oldValue)setPrivateMediaSource(el,value);},
};
/** Inert parsing before v-html insertion prevents native loads, including during suspension. */
export function guardPrivateMediaHtml(html:string):string {
  const template=document.createElement('template');template.innerHTML=html;
  for(const el of template.content.querySelectorAll('img,video,audio,source,image,input[type=image]')) {
    for(const attr of ['src','poster','href']) {
      const url=el.getAttribute(attr);if(url&&privateRequest(url))setPrivateMediaSource(el,url,attr);
    }
    // A private candidate must not bypass the guarded src via the native srcset loader.
    const linked=el.getAttribute('xlink:href');
    if(linked&&privateRequest(linked)){el.removeAttribute('xlink:href');setPrivateMediaSource(el,linked,'href');}
    const srcset=el.getAttribute('srcset');
    const candidates=srcset?.split(',').map(part=>part.trim().split(/\s+/)[0]!).filter(Boolean);
    if(candidates?.some(url=>privateRequest(url))) {
      el.setAttribute('data-private-srcset',srcset!);el.removeAttribute('srcset');
      if(!el.hasAttribute('src')&&!el.hasAttribute('data-private-src'))setPrivateMediaSource(el,candidates[0]!);
    }
  }
  return template.innerHTML;
}
/** HTML exports retain original/relative URLs, never transient object URLs. */
export function restorePrivateMediaHtml(html:string):string {
  const template=document.createElement('template');template.innerHTML=html;
  for(const el of template.content.querySelectorAll('[data-private-src],[data-private-poster],[data-private-href]')) {
    for(const attr of ['src','poster','href']) {
      const url=el.getAttribute(`data-private-${attr}`);
      if(url!==null){el.setAttribute(attr,url);el.removeAttribute(`data-private-${attr}`);}
    }
  }
  for(const el of template.content.querySelectorAll('[data-private-srcset]')){el.setAttribute('srcset',el.getAttribute('data-private-srcset')!);el.removeAttribute('data-private-srcset');}
  return template.innerHTML;
}

type Media={el:Element;attr:string;source:string;owner:string|undefined;generation:number;epoch:number;controller?:AbortController;objectUrl?:string;loaded:boolean;removeListeners:()=>void};
/** Private native media goes through an epoch-bound blob producer before native decoding.
 * Loaded media stays in memory on expiry; pending loads are canceled and never admitted.
 * Owner changes, removal, replacement and teardown revoke all owned object URLs.
 */
export function installPrivateMedia(root:Node=document.documentElement) {
  const records=new Map<Element,Map<string,Media>>();
  let disposed=false;
  function cancel(record:Media,discard=false) {
    record.controller?.abort();record.controller=undefined;
    if(discard||!record.loaded) {
      if(record.objectUrl){
        const url=record.objectUrl;
        if(record.el.getAttribute(record.attr)===url)record.el.removeAttribute(record.attr);
        const player=record.el instanceof HTMLMediaElement?record.el:record.el.parentElement;
        if(player instanceof HTMLMediaElement&&player.currentSrc===url){player.pause();player.load();}
        URL.revokeObjectURL(url);record.objectUrl=undefined;
      }
      record.loaded=false;
    }
  }
  function current(record:Media,epoch:number) {
    return record.el.isConnected && record.el.getAttribute(`data-private-${record.attr}`)===record.source
      && !sessionBlocked() && epoch===auth.requestEpoch && record.owner===auth.me?.id && record.generation===auth.sessionGeneration;
  }
  async function load(record:Media) {
    if(record.controller||record.objectUrl||sessionBlocked())return;
    const epoch=auth.requestEpoch;record.epoch=epoch;
    const controller=new AbortController();record.controller=controller;
    try {
      const response=await fetch(record.source,{signal:controller.signal});
      if(!response.ok)throw new Error('媒体加载失败');
      const blob=await response.blob();
      assertSession(record.generation,record.owner,epoch);
      if(controller.signal.aborted||!current(record,epoch))return;
      record.objectUrl=URL.createObjectURL(blob);
      if(record.attr==='poster'){
        const poster=new Image();poster.src=record.objectUrl;await poster.decode();
        if(controller.signal.aborted||!current(record,epoch))return;
        record.loaded=true;
      }
      record.el.setAttribute(record.attr,record.objectUrl!);
      if(record.el.tagName.toLowerCase()==='source'&&record.el.parentElement instanceof HTMLMediaElement)record.el.parentElement.load();
    } catch { /* Expired or removed producers are deliberately silent; source/draft stays intact. */ }
    finally {if(record.controller===controller)record.controller=undefined;}
  }
  function scan() {
    if(disposed)return;
    for(const [el,attrs] of records) {
      for(const [attr,record] of attrs) {
        if(!el.isConnected || el.getAttribute(`data-private-${attr}`)!==record.source) {
          cancel(record,true);record.removeListeners();attrs.delete(attr);
        }
      }
      if(!attrs.size)records.delete(el);
    }
    if(!(root instanceof Element))return;
    for(const el of root.querySelectorAll('[data-private-src],[data-private-poster],[data-private-href]')) {
      for(const attr of ['src','poster','href']) {
        const source=el.getAttribute(`data-private-${attr}`);
        if(!source||!privateRequest(source))continue;
        let attrs=records.get(el);if(!attrs){attrs=new Map();records.set(el,attrs);}
        let record=attrs.get(attr);
        if(!record) {
          const loaded=()=>{
            if(record!.objectUrl && record!.epoch===auth.requestEpoch&&!sessionBlocked())record!.loaded=true;
          };
          const target=el.tagName.toLowerCase()==='source'?el.parentElement||el:el;
          el.addEventListener('load',loaded);target.addEventListener('loadeddata',loaded);
          record={el,attr,source,owner:auth.me?.id,generation:auth.sessionGeneration,epoch:auth.requestEpoch,loaded:false,
            removeListeners:()=>{el.removeEventListener('load',loaded);target.removeEventListener('loadeddata',loaded);}};
          attrs.set(attr,record);
        }
        if(record.owner===auth.me?.id&&record.generation===auth.sessionGeneration)void load(record);
      }
    }
  }
  const observer=new MutationObserver(scan);
  observer.observe(root,{subtree:true,childList:true,attributes:true,attributeFilter:['data-private-src','data-private-poster','data-private-href']});
  const stop=watch(()=>[auth.requestEpoch,auth.suspended,auth.sessionClosing,auth.me?.id,auth.sessionGeneration],(value,previous)=>{
    if(previous&&value.every((item,index)=>item===previous[index]))return;
    for(const attrs of records.values())for(const record of attrs.values()) {
      const discard=record.owner!==auth.me?.id||record.generation!==auth.sessionGeneration;
      cancel(record,discard);
      if(discard){record.removeListeners();attrs.delete(record.attr);}
    }
    // Admission waits until the whole synchronous auth transition has settled.
    // Expiry advances the epoch before setting suspended; never start work in that gap.
    if(!sessionBlocked())queueMicrotask(()=>{if(!sessionBlocked())scan();});
  },{flush:'sync'});
  scan();
  return ()=>{disposed=true;observer.disconnect();stop();for(const attrs of records.values())for(const record of attrs.values()){cancel(record,true);record.removeListeners();}records.clear();};
}
