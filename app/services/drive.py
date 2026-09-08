"""OpenList external connection; existing visual theme preserved."""
import re
from urllib.parse import urlencode
from app.services import external_services as external

OPENLIST_THEME_CSS = """
html, body, #root { background-color: #14171f !important; color: #f0f4f8 !important; }
* { font-family: Inter, "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif !important; }
/* 统一字体大小和颜色 */
html[data-bg-mode="image"] .hope-text,
html[data-bg-mode="image"] [class*="text"],
html[data-bg-mode="image"] [class*="meta"],
html[data-bg-mode="image"] [class*="info"] {
  font-size: 16px !important;
  color: #f0f4f8 !important;
}
img[src*="oplist.org"] { display: none !important; }
a[href*="oplist.org"], a[href*="github.com/OpenList"] { display: none !important; }
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

OPENLIST_THEME_JS = """
(function () {
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

  // 读取 URL bgmode 参数，并在 iframe 内部自己设置透明背景
  // 同时监听外层 Stella 通过 postMessage 实时切换模式
  const STELLA_BG_LS_KEY = '__stella_drive_bg_mode__';
  function applyImageBg() {
    const html = document.documentElement;
    const body = document.body;
    const root = document.getElementById('root');
    html.setAttribute('data-bg-mode', 'image');
    html.style.setProperty('background-color', 'transparent', 'important');
    html.style.setProperty('color-scheme', 'normal', 'important');
    if (body) body.style.setProperty('background-color', 'transparent', 'important');
    if (root) root.style.setProperty('background-color', 'transparent', 'important');
  }
  function applySolidBg() {
    const html = document.documentElement;
    html.removeAttribute('data-bg-mode');
  }
  function getSavedBgMode() {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get('bgmode');
    if (fromUrl === 'image' || fromUrl === 'solid') return fromUrl;
    try { return localStorage.getItem(STELLA_BG_LS_KEY); } catch (e) { return null; }
  }
  function saveBgMode(mode) {
    try { localStorage.setItem(STELLA_BG_LS_KEY, mode); } catch (e) {}
  }
  function applyBgMode(mode) {
    if (mode === 'image') {
      applyImageBg();
      // 守护：OpenList 初始化会覆盖 html/body 背景，监听并保持透明
      if (!window.__stellaBgGuard) {
        window.__stellaBgGuard = new MutationObserver(() => {
          const html = document.documentElement;
          if (html.getAttribute('data-bg-mode') !== 'image' || getComputedStyle(html).backgroundColor !== 'rgba(0, 0, 0, 0)') {
            applyImageBg();
          }
        });
        window.__stellaBgGuard.observe(document.documentElement, { attributes: true, attributeFilter: ['style', 'data-bg-mode'] });
      }
      if (document.body && !window.__stellaBodyGuard) {
        window.__stellaBodyGuard = new MutationObserver(() => {
          const b = document.body;
          if (b && getComputedStyle(b).backgroundColor !== 'rgba(0, 0, 0, 0)') {
            b.style.setProperty('background-color', 'transparent', 'important');
          }
        });
        window.__stellaBodyGuard.observe(document.body, { attributes: true, attributeFilter: ['style'] });
      }
    } else {
      applySolidBg();
    }
  }
  function initBgMode() {
    const mode = getSavedBgMode();
    applyBgMode(mode);
  }
  initBgMode();
  // 监听外层 Stella 的 postMessage 切换
  if (!window.__stellaMsgListener) {
    window.__stellaMsgListener = function (e) {
      if (e.origin !== window.location.origin) return;
      if (e.data && e.data.type === 'stella-bg-mode') {
        saveBgMode(e.data.mode);
        applyBgMode(e.data.mode);
      }
    };
    window.addEventListener('message', window.__stellaMsgListener);
  }
  // SPA 路由返回时重新应用保存的模式（URL query 在 OpenList 内部路由切换后可能不变）
  if (!window.__stellaRouteListener) {
    window.__stellaRouteListener = function () {
      const mode = getSavedBgMode();
      if (mode) applyBgMode(mode);
    };
    window.addEventListener('popstate', window.__stellaRouteListener);
    window.addEventListener('hashchange', window.__stellaRouteListener);
  }

  function cleanTitle() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.textContent.includes('OpenList')) {
        node.textContent = node.textContent.split('OpenList').join('').trim();
      }
    }
    if (document.title.includes('OpenList')) {
      document.title = document.title.split('OpenList').join('').trim() || '网盘';
    }
  }

  function removeBrand() {
    document.querySelectorAll('a[href*="oplist.org"], a[href*="github.com"]').forEach(e => e.remove());
    document.querySelectorAll('img[src*="oplist.org"]').forEach(e => e.remove());
  }

  function mergeSwitchLayout() {
    const allSwitches = document.querySelectorAll('[aria-label="switch layout"]');
    const nav = document.querySelector('nav.hope-breadcrumb, .nav, .hope-breadcrumb');
    const header = document.querySelector('.header, header, [class*="header"]');
    if (!nav || allSwitches.length === 0) return;
    // 保留最后一个，移除其他重复的
    const sw = allSwitches[allSwitches.length - 1];
    allSwitches.forEach((el, idx) => { if (idx !== allSwitches.length - 1) el.remove(); });
    if (!nav.contains(sw)) nav.appendChild(sw);
    nav.style.display = 'flex';
    nav.style.alignItems = 'center';
    nav.style.justifyContent = 'space-between';
    nav.style.width = '100%';
    if (header) header.style.display = 'none';
  }

  function cleanFooter() {
    const footer = document.querySelector('.footer');
    if (footer) {
      footer.querySelectorAll('span').forEach(s => {
        if (s.textContent.trim() === '|') s.remove();
      });
      footer.style.justifyContent = 'center';
    }
  }

  function applyImageModeItems() {
    const imgMode = document.documentElement.getAttribute('data-bg-mode') === 'image';
    document.querySelectorAll('.list-item').forEach(e => {
      if (imgMode) {
        e.style.setProperty('background-color', 'transparent', 'important');
      } else {
        e.style.removeProperty('background-color');
      }
    });
  }

  function kill() {
    initBgMode();
    removeBrand();
    cleanTitle();
    mergeSwitchLayout();
    cleanFooter();
    applyImageModeItems();
  }

  kill();

  let observer;
  function startObserver() {
    if (observer) return;
    observer = new MutationObserver(() => {
      if (window.__stellaKillTimer) return;
      window.__stellaKillTimer = setTimeout(() => {
        window.__stellaKillTimer = null;
        kill();
      }, 100);
    });
    const target = document.body || document.documentElement;
    observer.observe(target, { childList: true, subtree: true });
  }

  if (document.body) startObserver();
  else window.addEventListener('DOMContentLoaded', startObserver);

  let readyTimer = setInterval(() => {
    const sw = document.querySelector('[aria-label="switch layout"]');
    const nav = document.querySelector('nav.hope-breadcrumb, .nav, .hope-breadcrumb');
    if (sw && nav && nav.contains(sw)) {
      clearInterval(readyTimer);
      document.documentElement.setAttribute('data-stella-theme', 'ready');
    }
  }, 200);
  setTimeout(() => {
    clearInterval(readyTimer);
    document.documentElement.setAttribute('data-stella-theme', 'ready');
  }, 3000);
})();
""".strip()

def inject_theme_html(html: str) -> str:
    """反代注入：把深色主题 CSS 塞进 HTML 的 <head>，让首屏第一次渲染就是深色。

    消除「先显示默认浅色主题，再被 customize_head 覆盖」的闪烁。
    同时把 OpenList 的 <meta name="color-scheme" content="light dark"> 改成 normal，
    否则 iframe canvas 在真实浏览器下会被填成黑色/白色，导致背景图透不出来。
    """
    style = f"<style>{OPENLIST_THEME_CSS}</style>"
    if "</head>" in html:
        html = html.replace("</head>", style + "</head>", 1)
    elif "<head>" in html:
        html = html.replace("<head>", "<head>" + style, 1)
    else:
        html = style + html
    # 覆盖 OpenList 的 color-scheme meta，让 iframe canvas 在透明 html/body 下也能透背景
    html = re.sub(
        r'<meta\s+name="color-scheme"\s+content="[^"]*"\s*/?>',
        '<meta name="color-scheme" content="normal">',
        html,
        flags=re.IGNORECASE,
    )
    return html

def get_status(db):
    cfg = external.load(db, 'drive')
    return {'configured': True, 'auth_mode': cfg.auth_mode}


def get_login_url(db, is_admin=False):
    cfg = external.load(db, 'drive')
    base = '/drive/openlist'
    if is_admin and cfg.auth_mode == 'token' and cfg.token:
        return {'url': base + '/@login?' + urlencode({'token': cfg.token})}
    return {'url': base + '/'}
