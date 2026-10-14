import {watch, type Directive} from 'vue';
import {auth} from '../home/auth';
import {privateRequest,sessionBlocked,parseMediaUrl} from './sessionFence';

const attributes=['srcset','src','poster','href','xlink:href','background'] as const;
const marker=(attr:string)=>`data-private-${attr.replace(':','-')}`;
const selector=attributes.map(attr=>`[${marker(attr)}]`).join(',');
const xlinkNamespace='http://www.w3.org/1999/xlink';
function sourceAttribute(el:Element,attr:string) {
  return attr==='xlink:href'?el.getAttributeNS(xlinkNamespace,'href'):el.getAttribute(attr);
}
function removeSourceAttribute(el:Element,attr:string) {
  if(attr==='xlink:href')el.removeAttributeNS(xlinkNamespace,'href');
  el.removeAttribute(attr);
}
function setSourceAttribute(el:Element,attr:string,url:string) {
  if(attr==='xlink:href'){removeSourceAttribute(el,attr);el.setAttributeNS(xlinkNamespace,attr,url);}
  else el.setAttribute(attr,url);
}
/** Display URLs only: never mutate Markdown or ProseMirror's source attributes. */
export function setPrivateMediaSource(el:Element,url:string,attr='src') {
  el.removeAttribute(marker(attr));
  if(url && parseMediaUrl(url)) {
    if(privateRequest(url)) {removeSourceAttribute(el,attr);el.setAttribute(marker(attr),url);}
    else setSourceAttribute(el,attr,url);
  } else removeSourceAttribute(el,attr);
}
export const vPrivateSrc:Directive<HTMLElement,string>={
  beforeMount:(el,{value})=>setPrivateMediaSource(el,value),
  updated:(el,{value,oldValue})=>{if(value!==oldValue)setPrivateMediaSource(el,value);},
};
// Read only candidate URLs, not descriptors. Data URL commas are part of the URL.
function candidates(srcset:string):string[] {
  const urls:string[]=[];let rest=srcset;
  while(rest) {
    rest=rest.replace(/^[\s,]+/,'');if(!rest)break;
    const token=/^\S+/.exec(rest)![0];rest=rest.slice(token.length);
    urls.push(token.replace(/,+$/,''));
    if(!token.endsWith(',')){const end=rest.indexOf(',');rest=end<0?'':rest.slice(end+1);}
  }
  return urls;
}
/** Inert parsing before insertion. Native selection/streaming runs only after admission. */
export function guardPrivateMediaHtml(html:string):string {
  const template=document.createElement('template');template.innerHTML=html;
  // Internal display metadata is not trusted note input (DOMPurify allows data-*).
  for(const el of template.content.querySelectorAll(selector))for(const attr of attributes)el.removeAttribute(marker(attr));
  for(const el of template.content.querySelectorAll('img,video,audio,source,track,image,input[type=image],[background]')) {
    for(const attr of ['src','poster','href','xlink:href','background']) {
      const url=el.getAttribute(attr);if(url)setPrivateMediaSource(el,url,attr);
    }
    const srcset=el.getAttribute('srcset');
    if(srcset) {
      const urls=candidates(srcset);
      if(urls.some(url=>!parseMediaUrl(url)))el.removeAttribute('srcset');
      else if(urls.some(url=>privateRequest(url))){el.setAttribute(marker('srcset'),srcset);el.removeAttribute('srcset');}
    }
  }
  for(const img of template.content.querySelectorAll('img[data-private-srcset]'))if(!img.hasAttribute(marker('src'))) {
    img.setAttribute(marker('src'),img.getAttribute('src')||'');img.removeAttribute('src');
  }
  // A private picture candidate also owns the fallback image's display lifetime.
  // Empty srcset marks absence so exports/resume can remove a frozen selection.
  for(const source of template.content.querySelectorAll('picture source[data-private-srcset]')) {
    const img=source.parentElement?.querySelector('img');if(!img)continue;
    for(const attr of ['srcset','src'])if(!img.hasAttribute(marker(attr))) {
      const value=img.getAttribute(attr);if(value!==null||attr==='srcset'){img.setAttribute(marker(attr),value||'');img.removeAttribute(attr);}
    }
  }
  return template.innerHTML;
}
/** HTML exports retain original/relative URLs, never frozen display selections. */
export function restorePrivateMediaHtml(html:string):string {
  const template=document.createElement('template');template.innerHTML=html;
  for(const el of template.content.querySelectorAll(selector))for(const attr of attributes) {
    const url=el.getAttribute(marker(attr));
    if(url!==null){if(url)setSourceAttribute(el,attr,url);else removeSourceAttribute(el,attr);el.removeAttribute(marker(attr));}
  }
  return template.innerHTML;
}

type Media={el:Element;sources:Map<string,string>;display:Map<string,string>;owner:string|undefined;generation:number;frozen?:boolean};
function snapshotDensity(el:HTMLImageElement) {
  // naturalWidth is density-corrected, not the selected bitmap's physical width.
  // Read only existing candidates; never load another Image/Blob to discover pixels.
  const sets=[el.getAttribute(marker('srcset'))||el.getAttribute('srcset')||''];
  if(el.parentElement?.tagName==='PICTURE')for(const source of el.parentElement.querySelectorAll('source'))sets.unshift(source.getAttribute(marker('srcset'))||source.getAttribute('srcset')||'');
  for(const set of sets)for(const match of set.matchAll(/(?:^|,)\s*(\S+)\s+(\d*\.?\d+)([xw])(?=\s*(?:,|$))/g)) {
    if(parseMediaUrl(match[1])?.href===el.currentSrc) {
      const density=Number(match[2])/(match[3]==='w'?el.naturalWidth:1);
      if(Number.isFinite(density)&&density>0)return density;
    }
  }
  const rect=el.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
  return Math.max(1,dpr,rect.width*dpr/el.naturalWidth,rect.height*dpr/el.naturalHeight);
}
/** No fetch/blob producer: preserve browser Range, lazy, srcset/sizes and picture selection.
 * Synchronous session transitions detach pending sources. Completed HTML images survive
 * same-owner expiry; video/audio pause+load discards buffers (not a buffer-retention promise).
 * Native cancellation cannot retract requests already issued or bytes already downloaded.
 * The server must authenticate every request. No asynchronous callbacks write sources back.
 */
export function installPrivateMedia(root:Node=document.documentElement) {
  const records=new Map<Element,Media>(),retired=new WeakSet<Element>();
  let disposed=false;
  const sameOwner=(r:Media)=>r.owner===auth.me?.id&&r.generation===auth.sessionGeneration;
  function detach(r:Media) {
    for(const [attr,url] of r.display)if(sourceAttribute(r.el,attr)===url)removeSourceAttribute(r.el,attr);
    r.display.clear();r.frozen=false;
  }
  function player(el:Element){return el instanceof HTMLMediaElement?el:el.parentElement instanceof HTMLMediaElement?el.parentElement:undefined;}
  function pause(discard=false) {
    const players=new Set<HTMLMediaElement>();
    // Freeze selected completed images before removing their picture/srcset candidates.
    for(const r of [...records.values()].sort((a,b)=>Number(b.el instanceof HTMLImageElement)-Number(a.el instanceof HTMLImageElement))) {
      const el=r.el;
      if(!discard&&sameOwner(r)&&r.frozen)continue;
      if(!discard&&sameOwner(r)&&el instanceof HTMLImageElement&&el.complete&&el.naturalWidth>0) {
        if(r.sources.has('srcset')||el.parentElement?.tagName==='PICTURE') {
          // Only already decoded responsive images need a local pixel snapshot on pause.
          // Native srcset removal/reselection re-requests no-store sources. Never fetch
          // or snapshot pending media; a tainted canvas fails closed by detaching.
          try {
            const density=snapshotDensity(el),width=Math.ceil(el.naturalWidth*density),height=Math.ceil(el.naturalHeight*density);
            // A per-snapshot ceiling, not a new page-wide media budget. Fail closed
            // rather than allocate without bound or silently downsample private pixels.
            if(!Number.isFinite(width*height)||width<1||height<1||width>8192||height>8192||width*height>16777216)throw new Error('Image snapshot too large');
            const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
            const ctx=canvas.getContext('2d');if(!ctx)throw new Error('No image canvas');
            ctx.drawImage(el,0,0,width,height);const pixels=canvas.toDataURL(),selection=`${pixels} ${width/el.naturalWidth}x`;
            // Preserve density-corrected intrinsic layout as well as screen pixels.
            el.setAttribute('srcset',selection);el.setAttribute('src',pixels);
            r.display.set('srcset',selection);r.display.set('src',pixels);r.frozen=true;
          } catch {detach(r);}
        }
      } else {detach(r);const media=player(el);if(media)players.add(media);}
      if(!sameOwner(r)){detach(r);retired.add(el);}
    }
    for(const media of players){media.pause();media.load();}
  }
  function scan() {
    if(disposed||!(root instanceof Element))return;
    const players=new Set<HTMLMediaElement>();
    for(const [el,r] of records) {
      if(!root.contains(el)||[...r.sources].some(([attr,url])=>el.getAttribute(marker(attr))!==url)) {
        detach(r);records.delete(el);const media=player(el);if(media)players.add(media);
      }
    }
    const elements=[...(root.matches(selector)?[root]:[]),...root.querySelectorAll(selector)];
    for(const el of elements) {
      if(retired.has(el))continue; // Old owner's still-mounted nodes never rebind to a new login.
      let r=records.get(el);
      if(!r) {
        const sources=new Map<string,string>();
        for(const attr of attributes){const url=el.getAttribute(marker(attr));if(url!==null)sources.set(attr,url);}
        r={el,sources,display:new Map(),owner:auth.me?.id,generation:auth.sessionGeneration};records.set(el,r);
      }
      if(sessionBlocked()||!sameOwner(r))continue;
      for(const [attr,url] of r.sources) {
        if(sourceAttribute(el,attr)!==(url||null)){if(url)setSourceAttribute(el,attr,url);else removeSourceAttribute(el,attr);const media=player(el);if(media&&attr!=='poster')players.add(media);}
        if(url)r.display.set(attr,url);else r.display.delete(attr);
      }
      r.frozen=false;
    }
    for(const media of players)media.load();
  }
  const observer=new MutationObserver(scan);
  observer.observe(root,{subtree:true,childList:true,attributes:true,attributeFilter:attributes.map(marker)});
  const stop=watch(()=>[auth.requestEpoch,auth.suspended,auth.sessionClosing,auth.me?.id,auth.sessionGeneration],()=>{
    pause();
    // Epoch advances before suspended/owner changes. Never restore in that synchronous gap.
    queueMicrotask(()=>{if(!disposed&&!sessionBlocked())scan();});
  },{flush:'sync'});
  scan();
  return ()=>{disposed=true;observer.disconnect();stop();pause(true);records.clear();};
}
