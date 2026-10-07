"""Optional OpenList visual layers; legacy constants stay in drive.py.

Background transparency is device compatibility, not part of the theme switch.
"""

SIMPLIFIED_JS = r"""
(()=>{
  if(window.__stellaSimplified)return;window.__stellaSimplified=true;
  const regions='header,.header,footer,.footer,nav:not(.hope-breadcrumb),.nav:not(.hope-breadcrumb)';
  function brandUrl(value){try{const u=new URL(value,location.href);return u.hostname==='oplist.org'||u.hostname.endsWith('.oplist.org')||(u.hostname==='github.com'&&/^\/(?:OpenListTeam|OpenList)(?:\/|$)/i.test(u.pathname));}catch{return false;}}
  function removeBrand(){
    for(const region of document.querySelectorAll(regions)){
      for(const el of region.querySelectorAll('a[href],img[src]')){
        if(el.closest('.hope-breadcrumb,.list-item,[data-file-name]'))continue;
        if(brandUrl(el.getAttribute(el.tagName==='A'?'href':'src')))el.remove();
      }
      const walker=document.createTreeWalker(region,NodeFilter.SHOW_TEXT);const nodes=[];
      while(walker.nextNode())nodes.push(walker.currentNode);
      for(const node of nodes){
        if(node.parentElement?.closest('a,button,script,style,.hope-breadcrumb,.list-item,[data-file-name]'))continue;
        if(/^\s*(?:Powered by\s+)?OpenList\s*$/i.test(node.textContent))node.textContent='';
      }
    }
  }
  function mergeSwitchLayout(){
    const nav=document.querySelector('nav.hope-breadcrumb,.nav,.hope-breadcrumb');
    const header=document.querySelector('header,.header');
    const switches=document.querySelectorAll('header [aria-label="switch layout"],.header [aria-label="switch layout"],nav [aria-label="switch layout"],.nav [aria-label="switch layout"]');
    if(!nav||!switches.length)return;
    const sw=switches[switches.length-1];
    for(const el of switches)if(el!==sw)el.remove();
    if(!nav.contains(sw))nav.append(sw);
    nav.style.display='flex';nav.style.alignItems='center';nav.style.justifyContent='space-between';nav.style.width='100%';
    if(header&&!header.contains(nav))header.style.display='none';
  }
  function apply(){
    removeBrand();mergeSwitchLayout();
    for(const el of document.querySelectorAll('footer span,.footer span'))if(el.textContent.trim()==='|')el.remove();
    document.documentElement.dataset.stellaTheme='ready';
  }
  function start(){apply();let scheduled=false;new MutationObserver(()=>{if(scheduled)return;scheduled=true;setTimeout(()=>{scheduled=false;apply();},100);}).observe(document.body,{childList:true,subtree:true});}
  if(document.body)start();else document.addEventListener('DOMContentLoaded',start,{once:true});
})();
""".strip()

THEME_CSS = """
html, body, #root { background-color: #14171f !important; color: #f0f4f8 !important; }
* { font-family: Inter, "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important; }
a, .hope-anchor { color: #f0f4f8 !important; }
button.hope-button, [data-focus], [class*="button"] { background-color: #1b1f2a !important; color: #f0f4f8 !important; border-color: rgba(201,212,232,0.15) !important; }
.header, header, [class*="header"] { background-color: #14171f !important; border-color: #1b1f2a !important; }
.nav, nav, .hope-breadcrumb, .obj-box, .hope-progress, [class*="breadcrumb"], [class*="progress"], [class*="menu"], [class*="popover"], [class*="dropdown"] { background-color: #14171f !important; color: #f0f4f8 !important; border-color: #1b1f2a !important; }
.obj-box, [class*="obj"], [class*="menu"], [class*="popover"], [class*="dropdown"], [class*="card"] { box-shadow: none !important; }
.obj-box { border-radius: 16px !important; }
.list-item { border-radius: 10px !important; }
.list.viselect-container { border-radius: 10px !important; overflow: hidden !important; }
input, textarea, select, [class*="input"], [class*="Input"] { background-color: #1b1f2a !important; color: #f0f4f8 !important; border-color: rgba(201,212,232,0.15) !important; }
tr, [class*="row"] { background-color: transparent !important; }
tr:hover, [class*="row"]:hover, [class*="item"]:hover { background-color: #1b1f2a !important; }

""".strip()

SIMPLIFIED_CSS = """
.footer { justify-content: center !important; }
/* 面包屑首页 Feather home 图标（CSS 伪元素注入，首次渲染就有，不闪烁） */
.hope-breadcrumb__item:first-child .hope-breadcrumb__link::before,
.hope-breadcrumb__item:first-child a::before,
nav.hope-breadcrumb li:first-child a::before {
  content: '';
  display: inline-block;
  width: 16px;
  height: 16px;
  background-image: url("data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20width='24'%20height='24'%20viewBox='0%200%2024%2024'%20fill='none'%20stroke='%23c9d4e8'%20stroke-width='2'%20stroke-linecap='round'%20stroke-linejoin='round'%3E%3Cpath%20d='M3%209l9-7%209%207v11a2%202%200%200%201-2%202H5a2%202%200%200%201-2-2z'/%3E%3Cpolyline%20points='9%2022%209%2012%2015%2012%2015%2022'/%3E%3C/svg%3E");
  background-size: contain;
  background-repeat: no-repeat;
  margin-right: 4px;
  vertical-align: -3px;
}

""".strip()

BACKGROUND_CSS = """
/* 统一字体大小和颜色 */
html[data-bg-mode="image"] .hope-text,
html[data-bg-mode="image"] [class*="text"],
html[data-bg-mode="image"] [class*="meta"],
html[data-bg-mode="image"] [class*="info"] {
  font-size: 16px !important;
  color: #f0f4f8 !important;
}
/* 强制 color-scheme:normal，避免浏览器因 OpenList 的 light/dark meta 给 iframe canvas 填默认黑/白色 */
html[data-bg-mode="image"] { color-scheme: normal !important; background-color: transparent !important; }
html[data-bg-mode="image"] body,
html[data-bg-mode="image"] #root { background-color: transparent !important; }
/* 背景图模式：大容器磨砂玻璃半透明 */
html[data-bg-mode="image"] .obj-box {
  background: rgba(27, 31, 42, 0.25) !important;
  backdrop-filter: blur(8px) !important;
  -webkit-backdrop-filter: blur(8px) !important;
  border-color: rgba(201, 212, 232, 0.12) !important;
}
/* 文件列表容器：去掉磨砂，避免和 obj-box 两层 */
html[data-bg-mode="image"] .list.viselect-container {
  background: transparent !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
  border-color: transparent !important;
}
/* 面包屑/导航：纯透明，只保留文字和图标 */
html[data-bg-mode="image"] nav,
html[data-bg-mode="image"] .hope-breadcrumb,
html[data-bg-mode="image"] .hope-breadcrumb__list,
html[data-bg-mode="image"] .hope-breadcrumb__item,
html[data-bg-mode="image"] .hope-breadcrumb__link,
html[data-bg-mode="image"] .hope-breadcrumb__separator,
html[data-bg-mode="image"] [class*="separator"],
html[data-bg-mode="image"] [class*="sep"],
html[data-bg-mode="image"] .header,
html[data-bg-mode="image"] header,
html[data-bg-mode="image"] [class*="header"] {
  background: transparent !important;
  border-color: transparent !important;
  box-shadow: none !important;
}
/* 文件项：不要单独背景，完全透明，hover 时只加一点点遮罩 */
html[data-bg-mode="image"] .list-item,
html[data-bg-mode="image"] .list-item.inactive,
html[data-bg-mode="image"] .viselect-item {
  background: transparent !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}
html[data-bg-mode="image"] .list-item:hover,
html[data-bg-mode="image"] .list-item.inactive:hover,
html[data-bg-mode="image"] .viselect-item:hover {
  background: rgba(27, 31, 42, 0.15) !important;
}
/* 操作条/直接下载条等 */
html[data-bg-mode="image"] .toolbar,
html[data-bg-mode="image"] [class*="toolbar"],
html[data-bg-mode="image"] .actions,
html[data-bg-mode="image"] [class*="actions"],
html[data-bg-mode="image"] .operation,
html[data-bg-mode="image"] [class*="operation"] {
  background: rgba(27, 31, 42, 0.25) !important;
  backdrop-filter: blur(8px) !important;
  -webkit-backdrop-filter: blur(8px) !important;
}
/* 按钮/控件：透明背景，只保留文字和图标（select trigger 除外，单独磨砂） */
html[data-bg-mode="image"] button.hope-button,
html[data-bg-mode="image"] [data-focus],
html[data-bg-mode="image"] [class*="button"],
html[data-bg-mode="image"] input,
html[data-bg-mode="image"] textarea,
html[data-bg-mode="image"] select,
html[data-bg-mode="image"] [class*="input"],
html[data-bg-mode="image"] [class*="Input"] {
  background: transparent !important;
  border: none !important;
  border-radius: 0 !important;
  color: #f0f4f8 !important;
  box-shadow: none !important;
}
/* select trigger：透明无底，只留文字和箭头（和其他按钮统一） */
html[data-bg-mode="image"] .hope-select__trigger,
html[data-bg-mode="image"] [class*="select__trigger"] {
  background: transparent !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
  border: none !important;
  border-radius: 0 !important;
  color: #f0f4f8 !important;
  box-shadow: none !important;
}
/* 按钮 hover 效果 */
html[data-bg-mode="image"] button.hope-button:hover,
html[data-bg-mode="image"] .hope-select__trigger:hover,
html[data-bg-mode="image"] [class*="button"]:hover {
  background: rgba(27, 31, 42, 0.15) !important;
}
/* 下拉菜单/弹出层：磨砂深色底，保证选项可读（select__option 等不能被透明规则误伤） */
html[data-bg-mode="image"] .hope-select__content,
html[data-bg-mode="image"] [class*="select__content"],
html[data-bg-mode="image"] [class*="select-content"],
html[data-bg-mode="image"] [class*="dropdown"],
html[data-bg-mode="image"] .hope-menu__content,
html[data-bg-mode="image"] [class*="menu__content"],
html[data-bg-mode="image"] [class*="popover"],
html[data-bg-mode="image"] [class*="tooltip"] {
  background: rgba(20, 23, 31, 0.92) !important;
  backdrop-filter: blur(12px) !important;
  -webkit-backdrop-filter: blur(12px) !important;
  border: 1px solid rgba(201, 212, 232, 0.15) !important;
  border-radius: 10px !important;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4) !important;
  color: #f0f4f8 !important;
}
html[data-bg-mode="image"] .hope-select__option,
html[data-bg-mode="image"] [class*="select__option"],
html[data-bg-mode="image"] .hope-menu__item,
html[data-bg-mode="image"] [class*="menu__item"] {
  background: transparent !important;
  color: #f0f4f8 !important;
  border-radius: 6px !important;
}
html[data-bg-mode="image"] .hope-select__option:hover,
html[data-bg-mode="image"] [class*="select__option"]:hover,
html[data-bg-mode="image"] .hope-menu__item:hover,
html[data-bg-mode="image"] [class*="menu__item"]:hover {
  background: rgba(201, 212, 232, 0.12) !important;
}
/* 下拉选中项：淡蓝灰磨砂高亮，与菜单底色区分、不与文字色冲突 */
html[data-bg-mode="image"] .hope-select__option[aria-selected="true"],
html[data-bg-mode="image"] [class*="select__option"][aria-selected="true"] {
  background: rgba(201, 212, 232, 0.18) !important;
  border-radius: 6px !important;
}
/* 文件详情页 */
html[data-bg-mode="image"] .detail,
html[data-bg-mode="image"] [class*="detail"],
html[data-bg-mode="image"] .preview,
html[data-bg-mode="image"] [class*="preview"] {
  background: rgba(27, 31, 42, 0.25) !important;
  backdrop-filter: blur(8px) !important;
  -webkit-backdrop-filter: blur(8px) !important;
}
/* hover 反馈 */
html[data-bg-mode="image"] .list-item:hover,
html[data-bg-mode="image"] .list-item.inactive:hover,
html[data-bg-mode="image"] .viselect-item:hover,
html[data-bg-mode="image"] tr:hover,
html[data-bg-mode="image"] [class*="row"]:hover,
html[data-bg-mode="image"] [class*="item"]:hover {
  background: rgba(27, 31, 42, 0.15) !important;
}
/* 文字投影保证复杂背景可读 */
html[data-bg-mode="image"] .list-item *,
html[data-bg-mode="image"] .obj-box *,
html[data-bg-mode="image"] nav *,
html[data-bg-mode="image"] .hope-breadcrumb *,
html[data-bg-mode="image"] .toolbar *,
html[data-bg-mode="image"] [class*="toolbar"] *,
html[data-bg-mode="image"] .detail *,
html[data-bg-mode="image"] [class*="detail"] * {
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.9), 0 0 10px rgba(0, 0, 0, 0.7);
}
""".strip()
