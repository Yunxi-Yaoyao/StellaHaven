"""Always-on directory cache and same-origin background compatibility."""

BACKGROUND_JS = r"""
/* stella:background-ready:v1 */
(()=>{
  if(window.__stellaBackgroundV3)return;window.__stellaBackgroundV3=true;
  const parentOrigin=location.origin;
  const key='stella_drive_bg_mode',legacy='__stella_drive_bg_mode__';
  const valid=v=>v==='image'||v==='solid';
  let mode='solid',observer=null,pending=null,scheduled=false;
  const changed=new Map(),changedMeta=new Map();
  // A style-ready ACK is not an application/content-ready claim.
  function ready(){
    if(!pending||scheduled||!document.body||!document.getElementById('root'))return;
    scheduled=true;
    requestAnimationFrame(()=>{
      scheduled=false;
      if(!pending||!document.body||!document.getElementById('root'))return;
      const reply=pending;pending=null;
      window.parent.postMessage({type:'stella-bg-ready',mode,module_id:reply.module_id,request_id:reply.request_id},parentOrigin);
    });
  }
  function requestMode(){if(window.parent!==window)try{window.parent.postMessage({type:'stella-bg-request'},parentOrigin);}catch{}}
  function transparent(el,prop,value){
    if(!el)return;
    if(!changed.has(el))changed.set(el,new Map());
    const saved=changed.get(el);
    if(!saved.has(prop))saved.set(prop,[el.style.getPropertyValue(prop),el.style.getPropertyPriority(prop)]);
    if(el.style.getPropertyValue(prop)!==value||el.style.getPropertyPriority(prop)!=='important')el.style.setProperty(prop,value,'important');
  }
  function paint(){
    if(mode!=='image'){ready();return;}
    const html=document.documentElement;
    if(html.dataset.bgMode!=='image')html.dataset.bgMode='image';
    transparent(html,'color-scheme','normal');
    // Chromium canvas uses the document's meta scheme even when computed CSS
    // says normal. Match the host's normal canvas only while transparency is on.
    for(const meta of document.querySelectorAll('meta[name="color-scheme" i]')){
      if(!changedMeta.has(meta))changedMeta.set(meta,[meta.hasAttribute('content'),meta.getAttribute('content')]);
      if(meta.getAttribute('content')!=='normal')meta.setAttribute('content','normal');
    }
    for(const el of [html,document.body,document.getElementById('root')])transparent(el,'background-color','transparent');
    ready();
  }
  function apply(value){
    if(!valid(value))return;
    mode=value;
    if(observer)observer.disconnect();
    if(mode==='image'){
      paint();
      observer ||= new MutationObserver(paint);
      observer.observe(document.documentElement,{attributes:true,subtree:true,childList:true,attributeFilter:['style','data-bg-mode','content','name']});
    }else{
      document.documentElement.removeAttribute('data-bg-mode');
      for(const [el,props] of changed)for(const [prop,[v,priority]] of props){if(v)el.style.setProperty(prop,v,priority);else el.style.removeProperty(prop);}
      changed.clear();
      for(const [meta,[present,value]] of changedMeta){if(present)meta.setAttribute('content',value);else meta.removeAttribute('content');}
      changedMeta.clear();
      if(pending&&(!document.body||!document.getElementById('root'))){
        observer ||= new MutationObserver(paint);
        observer.observe(document.documentElement,{subtree:true,childList:true});
      }
      ready();
    }
  }
  function saved(){
    const query=new URLSearchParams(location.search).get('bgmode');
    try{const current=localStorage.getItem(key),old=localStorage.getItem(legacy);if(valid(current))return current;if(valid(old))return old;}catch{}
    return valid(query)?query:'solid';
  }
  function remember(value){try{localStorage.setItem(key,value);localStorage.setItem(legacy,value);}catch{}}
  const initial=saved();remember(initial);apply(initial);
  document.addEventListener('DOMContentLoaded',()=>{paint();requestMode();},{once:true});
  window.addEventListener('message',event=>{
    if(event.origin!==location.origin||event.source!==window.parent)return;
    if(event.data?.type!=='stella-bg-mode'||!valid(event.data.mode))return;
    const data=event.data;
    pending=typeof data.module_id==='string'&&data.module_id.length>0&&data.module_id.length<=128&&typeof data.request_id==='string'&&data.request_id.length>0&&data.request_id.length<=128?{module_id:data.module_id,request_id:data.request_id}:null;
    remember(data.mode);apply(data.mode);
  });
  requestMode();
  for(const type of ['popstate','hashchange'])window.addEventListener(type,()=>apply(saved()));
})();
""".strip()

CACHE_JS = r"""
(function () {
  if (window.__stellaCacheFix) return;
  window.__stellaCacheFix = true;
  // ── 写操作后清除 OpenList 前端历史快照缓存 ──
  // OpenList 机制（编译代码实锤）：fT Map 按 path-page 存目录快照 {obj, page, scroll}；
  // 导航时 _T() 命中 fT → gT() 直接恢复快照，不发任何请求。
  // 仅有点击 <a href="/..."> 时 document 捕获监听器会 vT() 清掉目标路径缓存——
  // 所以点文件夹（<a>）正常，点面包屑「首页」（<span>）/浏览器后退命中旧快照看不到新文件。
  // 方案：写操作成功后，对受影响路径合成一次 <a> 点击，触发 OpenList 自己的 vT 清缓存。
  // 不 reload、不操作列表 DOM、不改源码。
  function normPath(p) {
    if (!p || p === '/') return '/';
    return p.replace(/[/]+$/, '') || '/';
  }
  function parentPath(p) {
    const parts = p.split('/').filter(Boolean);
    parts.pop();
    return normPath('/' + parts.join('/'));
  }
  function clearPathCache(path) {
    // record 的 key 是剥离 base 前缀的路径（/test、/），vT 用 href 原文做 key。
    // 两种格式都 dispatch，确保命中（vT 对不存在的 key 静默跳过，无副作用）。
    const hrefs = [path, '/drive/openlist' + (path === '/' ? '/' : path)];
    hrefs.forEach(href => {
      try {
        const a = document.createElement('a');
        a.setAttribute('href', href);
        a.style.display = 'none';
        a.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); });
        document.body.appendChild(a);
        // 捕获阶段的 document 监听器先执行（清缓存），target 阶段的 preventDefault 阻止导航
        a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        a.remove();
      } catch (e) {}
    });
  }
  function clearCacheFromApi(url, bodyText, headers) {
    try {
      let body = {};
      try { body = JSON.parse(bodyText || '{}'); } catch (e) {}
      if (url.includes('/api/fs/move') || url.includes('/api/fs/copy') || url.includes('/api/fs/recursive_move')) {
        if (body.dst_dir) clearPathCache(normPath(body.dst_dir));
        if (body.src_dir) clearPathCache(normPath(body.src_dir));
      } else if (url.includes('/api/fs/remove') || url.includes('/api/fs/remove_empty_directory')) {
        if (body.dir) clearPathCache(normPath(body.dir));
        if (body.src_dir) clearPathCache(normPath(body.src_dir));
      } else if (url.includes('/api/fs/mkdir') || url.includes('/api/fs/rename') || url.includes('/api/fs/batch_rename') || url.includes('/api/fs/regex_rename')) {
        if (body.path) clearPathCache(parentPath(body.path));
        if (body.src_dir) clearPathCache(normPath(body.src_dir));
      } else if (url.includes('/api/fs/put') || url.includes('/api/fs/form')) {
        const fp = (headers && (headers['File-Path'] || headers['file-path'])) || '';
        if (fp) {
          try { clearPathCache(parentPath(decodeURIComponent(fp))); } catch (e) { clearPathCache(parentPath(fp)); }
        }
      }
    } catch (e) {}
  }
  // 包装 fetch
  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const resp = await origFetch.apply(this, args);
    try {
      const url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url) || '';
      if (url.includes('/api/fs/')) {
        const headers = (args[1] && args[1].headers) || {};
        const bodyText = (args[1] && args[1].body) || '';
        resp.clone().json().then(data => {
          if (data && data.code === 200) clearCacheFromApi(url, bodyText, headers);
        }).catch(() => {});
      }
    } catch (e) {}
    return resp;
  };
  // 包装 XHR（OpenList 用 axios → XHR）
  const origXhrOpen = XMLHttpRequest.prototype.open;
  const origXhrSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__stellaUrl = url;
    return origXhrOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (body) {
    const url = this.__stellaUrl || '';
    if (url.includes('/api/fs/')) {
      this.addEventListener('load', function () {
        try {
          const data = JSON.parse(this.responseText);
          if (data && data.code === 200) clearCacheFromApi(url, body, null);
        } catch (e) {}
      });
    }
    return origXhrSend.call(this, body);
  };

})();
""".strip()
