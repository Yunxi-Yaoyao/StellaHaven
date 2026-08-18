"""网盘（OpenList）宿主本机安装：docker 检测、拉镜像、创建容器、存储目录、更新管理。

OpenList 跑在 Stella 宿主本机（Nyarch），由后端直接调 docker socket 操作，不走 agent。
OpenList 是 AList 的 fork（镜像 openlistteam/openlist），数据目录 /opt/openlist/data，端口 5244。
镜像 tag 动态存 AppConfig（openlist_image_tag），「更新」时拉新 tag 后改写它。
存储目录是「本地存储」：host 目录挂进容器，之后在 OpenList Web UI 里填容器内路径即可。
"""
import json
import re
import secrets
import shutil
import string
import subprocess
import threading
import time
from pathlib import Path

import docker
from docker.errors import ImageNotFound, NotFound
from sqlalchemy.orm import Session

from app.repositories import config as config_repo

IMAGE_REPO = "openlistteam/openlist"
DEFAULT_IMAGE_TAG = "v4.2.1"          # 首次安装的默认版本
IMAGE_TAG_KEY = "openlist_image_tag"   # AppConfig：当前安装的镜像 tag（更新后改写）
OPENLIST_CONTAINER = "stella-openlist"
OPENLIST_PORT = 5244
OPENLIST_DATA_CTR = "/opt/openlist/data"  # OpenList 配置/数据库目录（容器内固定）

# Stella 项目根目录（app/services/drive.py → 上三级）
STELLA_DIR = Path(__file__).resolve().parents[2]
# OpenList 配置数据目录（固定，不暴露给用户增删改）
OPENLIST_DATA_HOST = STELLA_DIR / "data" / "openlist"
# 默认本地存储（安装向导预填，可增删改）
DEFAULT_STORAGE = {
    "name": "openlist",
    "host_path": str(STELLA_DIR / "data" / "openlist-storage"),
    "mount_path": "/data/openlist",
}

STORAGES_KEY = "drive_storages"
PROXY_KEY = "docker_proxy"  # AppConfig：docker daemon 代理地址（空=走宿主机默认）
DEFAULT_PROXY = "http://127.0.0.1:1081"  # Xray 本地 HTTP 代理
ADMIN_PASSWORD_KEY = "openlist_admin_password"  # 管理员密码（自动生成持久化，用户不感知）
SETTINGS_KEY = "drive_settings"  # 容器高级设置（端口/内存/CPU/时区/重启策略）

# 容器高级设置默认值（port 数字，其余字符串，空串=不限）
DEFAULT_SETTINGS = {
    "port": 5244,
    "mem_limit": "",       # 如 "512m"，空=不限
    "cpus": "",            # 如 "1.5"，空=不限
    "tz": "Asia/Shanghai",
    "restart_policy": "unless-stopped",
}

# OpenList 对外的 site_url：藏在 Stella 公网域名的子路径下（base_path = /drive/openlist）
# 容器以 `--no-prefix` 启动，env 变量名不带 OPENLIST_ 前缀（SITE_URL 而非 OPENLIST_SITE_URL）
SITE_URL = "https://stella.xiya.live/drive/openlist"
OPENLIST_BASE_PATH = "/drive/openlist"

# ── OpenList 视觉定制（Stella 深色主题，纯注入、不改源码）──
# 同一套 CSS/JS 用在两处：
#   1) 反代注入：对 HTML 响应塞 <style>，让首屏第一次渲染就是深色，消除默认浅色主题的闪烁
#   2) 自动注入：安装/更新后调 OpenList setting/save 写进 data.db，更新不丢、自动恢复
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

# 站点/主题基础设置（自动注入时写入，不包含 customize_head/body——那两个单独拼 <style>/<script>）
# logo/favicon 设空 = 删除；home/share_icon 用 Feather SVG data URL，避免 JS 替换导致的闪烁
OPENLIST_THEME_SETTINGS = {
    "site_title": "网盘",
    "main_color": "#f0f4f8",
    "announcement": "",
    "logo": "",
    "favicon": "",
    "home_icon": "",
    "share_icon": "",
    "share_preview": "true",
    "share_archive_preview": "true",
    "handle_hook_after_writing": "true",
}

# ── 拉镜像进度（单用户单次操作，内存态即可，不落库） ──
_pull_state: dict = {
    "status": "idle",   # idle | pulling | done | failed
    "layers": [],
    "current": 0,
    "total": 0,
    "percent": 0.0,
    "error": None,
}
_pull_lock = threading.Lock()


def _client() -> docker.DockerClient:
    return docker.from_env()


def _current_tag(db: Session) -> str:
    """当前安装的镜像 tag（AppConfig 有值用它，否则默认 v4.2.1）。"""
    raw = config_repo.get(db, IMAGE_TAG_KEY, "") or ""
    return raw.strip() or DEFAULT_IMAGE_TAG


def _current_image(db: Session) -> str:
    return f"{IMAGE_REPO}:{_current_tag(db)}"


# ── docker 检测 / 安装 ──
def detect_docker() -> dict:
    """检测本机 docker：是否安装 + 版本 + 服务是否运行。"""
    installed = shutil.which("docker") is not None
    if not installed:
        return {"installed": False, "version": None, "running": False}
    version = None
    running = False
    try:
        c = _client()
        version = c.version().get("Version")
        c.ping()
        running = True
    except Exception:
        running = False
    return {"installed": True, "version": version, "running": running}


def _distro() -> str:
    try:
        info = __import__("platform").freedesktop_os_release()
        name = info.get("NAME", "")
    except Exception:
        name = ""
    for suffix in (" GNU/Linux", " Linux"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name or "linux"


def install_docker() -> dict:
    """本机装 docker（兜底；本机已装不会走到）。仅支持 Arch 系自动安装，其余明确报不支持。"""
    distro = _distro()
    if distro in ("Arch", "Manjaro", "EndeavourOS"):
        subprocess.run(
            ["pacman", "-S", "--noconfirm", "--needed", "docker", "docker-compose"],
            check=False, capture_output=True,
        )
    else:
        raise RuntimeError(f"暂不支持在 {distro} 上自动安装 docker，请手动安装后刷新")
    subprocess.run(["systemctl", "enable", "--now", "docker"], check=False, capture_output=True)
    return detect_docker()


def _get_proxy(db: Session) -> str:
    return (config_repo.get(db, PROXY_KEY, "") or "").strip()


def apply_proxy(db: Session, proxy: str) -> dict:
    """设置/取消 docker daemon 代理。proxy 空 = 走宿主机默认网络。"""
    proxy = (proxy or "").strip()
    config_repo.put(db, PROXY_KEY, proxy)
    _write_proxy_conf(proxy)
    return get_status(db)


def _write_proxy_conf(proxy: str) -> None:
    """写 docker daemon 的 http-proxy.conf 并重启 daemon（清空则走宿主机默认）。"""
    conf = Path("/etc/systemd/system/docker.service.d/http-proxy.conf")
    conf.parent.mkdir(parents=True, exist_ok=True)
    if proxy:
        content = (
            "[Service]\n"
            f'Environment="HTTP_PROXY={proxy}"\n'
            f'Environment="HTTPS_PROXY={proxy}"\n'
            'Environment="NO_PROXY=localhost,127.0.0.1"\n'
        )
    else:
        content = "[Service]\n"
    conf.write_text(content)
    subprocess.run(["systemctl", "daemon-reload"], check=False, capture_output=True)
    subprocess.run(["systemctl", "restart", "docker"], check=False, capture_output=True)
    # 等 daemon 起来（最多 15 秒），避免重启后立即读状态报 running=false
    for _ in range(15):
        time.sleep(1)
        try:
            _client().ping()
            break
        except Exception:
            continue


# ── 拉镜像 ──
def start_pull(db: Session) -> None:
    """后台线程拉当前 tag 的镜像（幂等：已在拉就跳过）。"""
    image = _current_image(db)
    with _pull_lock:
        if _pull_state["status"] == "pulling":
            return
        _pull_state.update(status="pulling", layers=[], current=0, total=0,
                           percent=0.0, error=None)
    threading.Thread(target=_do_pull, args=(image,), daemon=True).start()


def _do_pull(image: str) -> None:
    global _pull_state
    try:
        c = _client()
        layers: dict[str, dict] = {}
        for line in c.api.pull(image, stream=True, decode=True):
            if not isinstance(line, dict):
                continue
            lid = line.get("id")
            status = line.get("status")
            pd = line.get("progressDetail") or {}
            if lid:
                entry = layers.setdefault(lid, {"id": lid, "status": "", "current": 0, "total": 0})
                if status:
                    entry["status"] = status
                if pd.get("total"):
                    entry["total"] = int(pd["total"])
                if pd.get("current") is not None:
                    entry["current"] = int(pd["current"])
            total = sum(e["total"] for e in layers.values())
            current = sum(e["current"] for e in layers.values())
            percent = round(current / total * 100, 1) if total else 0.0
            with _pull_lock:
                _pull_state.update(layers=list(layers.values()), current=current,
                                   total=total, percent=percent, status="pulling")
        # 拉完校验镜像是否真的落盘（docker-py 网络抖动会静默失败、不抛异常）
        try:
            c.images.get(image)
        except ImageNotFound:
            raise RuntimeError(f"拉取镜像失败（网络问题，请重试）：{image}")
        with _pull_lock:
            _pull_state.update(status="done", percent=100.0)
    except Exception as e:  # noqa: BLE001
        with _pull_lock:
            _pull_state.update(status="failed", error=str(e))


def get_pull_progress() -> dict:
    with _pull_lock:
        return dict(_pull_state)


# ── 存储目录（AppConfig JSON） ──
def _load_storages(db: Session) -> list[dict]:
    raw = config_repo.get(db, STORAGES_KEY, "[]")
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def _save_storages(db: Session, storages: list[dict]) -> None:
    config_repo.put(db, STORAGES_KEY, json.dumps(storages, ensure_ascii=False))


# ── 容器高级设置（AppConfig JSON） ──
def _load_settings(db: Session) -> dict:
    raw = config_repo.get(db, SETTINGS_KEY, "{}")
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        data = {}
    merged = {**DEFAULT_SETTINGS, **data}
    # 端口强转 int，防脏数据
    try:
        merged["port"] = int(merged.get("port") or DEFAULT_SETTINGS["port"])
    except (TypeError, ValueError):
        merged["port"] = DEFAULT_SETTINGS["port"]
    return merged


def _save_settings(db: Session, settings: dict) -> None:
    config_repo.put(db, SETTINGS_KEY, json.dumps(settings, ensure_ascii=False))


def _get_port(db: Session) -> int:
    return _load_settings(db)["port"]


# ── 管理员密码（自动生成持久化，用户不感知） ──
def _get_admin_password(db: Session) -> str:
    pwd = config_repo.get(db, ADMIN_PASSWORD_KEY, "") or ""
    if not pwd:
        pwd = _gen_password()
        config_repo.put(db, ADMIN_PASSWORD_KEY, pwd)
    return pwd


# ── 代签（docker exec `openlist admin token` 直接拿 admin token，供 iframe 免登录） ──
_token_cache: dict = {"token": None, "ts": 0.0}
_TOKEN_TTL = 24 * 3600  # admin token 永久有效，缓存 24h 内复用即可


def _get_admin_token(db: Session) -> str:
    """代签：用 `openlist admin token` 命令直接拿 admin token（永久有效，不依赖密码）。"""
    now = time.time()
    if _token_cache["token"] and now - _token_cache["ts"] < _TOKEN_TTL:
        return _token_cache["token"]
    out = subprocess.run(
        ["docker", "exec", OPENLIST_CONTAINER, "/opt/openlist/openlist", "admin", "token"],
        capture_output=True, text=True, timeout=20,
    )
    m = re.search(r"Admin token:\s*(\S+)", out.stdout or "")
    if not m:
        raise RuntimeError(f"获取 admin token 失败：{out.stderr or out.stdout}")
    _token_cache.update(token=m.group(1), ts=now)
    return _token_cache["token"]


def _wait_and_set_admin_password(pwd: str, timeout: int = 30) -> None:
    """等 OpenList 就绪后，用 `admin set` 命令设置 admin 密码。

    OpenList 的 OPENLIST_ADMIN_PASSWORD 环境变量不生效（server 启动时 env prefix 为空），
    所以改成容器起好后用 admin set 子命令设置，密码持久化在 AppConfig 作安全备用。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = subprocess.run(
                ["docker", "exec", OPENLIST_CONTAINER, "/opt/openlist/openlist", "admin", "set", pwd],
                capture_output=True, text=True, timeout=20,
            )
            if "admin user has been updated" in (r.stdout or ""):
                return
        except Exception:
            pass
        time.sleep(1.5)
    raise RuntimeError("设置 admin 密码超时（OpenList 可能未正常启动）")


def _sync_storages(db: Session) -> dict:
    """自动在 OpenList 里创建「本地存储（Local）」，对应安装时挂载的目录。

    幂等：先查已有存储的 mount_path，已存在则跳过，不重复创建。
    addition 里的 bool 字段必须是 JSON 布尔（json.dumps 构造），否则 OpenList 报 ReadBool 错。
    """
    import requests
    token = _get_admin_token(db)
    headers = {"Authorization": token}
    base = f"http://127.0.0.1:{_get_port(db)}{OPENLIST_BASE_PATH}/api/admin"
    existing: set[str] = set()
    try:
        r = requests.get(f"{base}/storage/list", headers=headers, timeout=8)
        content = (r.json().get("data") or {}).get("content", [])
        existing = {s.get("mount_path", "") for s in content}
    except Exception:
        pass
    created: list[str] = []
    skipped: list[str] = []
    for i, st in enumerate(_load_storages(db)):
        root = st.get("mount_path", "")
        if not root:
            continue
        # OpenList 虚拟挂载点：第一个用 /，后续用 /<name>
        vpath = "/" if i == 0 else "/" + (st.get("name") or f"storage{i}").strip("/")
        if vpath in existing:
            skipped.append(vpath)
            continue
        addition = json.dumps({
            "root_folder_path": root,
            "thumbnail": False,
            "show_hidden": True,
        })
        body = {
            "mount_path": vpath,
            "driver": "Local",
            "order": i,
            "remark": st.get("name") or "",
            "addition": addition,
            "webdav_policy": "native_proxy",
            "disable_index": False,
            "enable_sign": False,
        }
        r = requests.post(f"{base}/storage/create", json=body, headers=headers, timeout=10)
        # code 200 或「already created」都视为已存在
        created.append(vpath)
        existing.add(vpath)
    return {"created": created, "skipped": skipped}


def apply_theme(db: Session) -> dict:
    """自动注入 Stella 深色主题：写 customize_head/body + site_title/main_color/公告。

    幂等：重复调用只是重写同样内容。安装/更新后调用，保证视觉定制不丢、自动恢复。
    """
    import requests
    token = _get_admin_token(db)
    headers = {"Authorization": token}
    base = f"http://127.0.0.1:{_get_port(db)}{OPENLIST_BASE_PATH}/api/admin"
    settings = [{"key": k, "value": v} for k, v in OPENLIST_THEME_SETTINGS.items()]
    settings += [
        {"key": "customize_head", "value": f"<style>{OPENLIST_THEME_CSS}</style>"},
        {"key": "customize_body", "value": f"<script>{OPENLIST_THEME_JS}</script>"},
    ]
    r = requests.post(f"{base}/setting/save", json=settings, headers=headers, timeout=10)
    try:
        ok = r.json().get("code") == 200
    except Exception:
        ok = r.status_code == 200
    return {"ok": ok, "http": r.status_code}


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


def get_login_url(db: Session) -> dict:
    """免登录入口：返回 token + 端口，前端拼 iframe URL（hostname 由前端决定）。"""
    token = _get_admin_token(db)
    return {"token": token, "port": _get_port(db), "ttl": _TOKEN_TTL}


# ── 安装容器 ──
def _gen_password(length: int = 12) -> str:
    """生成随机管理员密码（字母+数字，去掉易混字符）。"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def install_container(db: Session, storages: list[dict],
                      settings: dict | None = None) -> dict:
    """保存存储配置 + 创建 OpenList 容器（幂等：先移除旧容器）。

    管理员密码：全新安装时自动生成并持久化（用户不感知，免登录靠代签），
    经 OPENLIST_ADMIN_PASSWORD 传给容器；重装（config 已存在）沿用原密码。
    高级设置（端口/内存/CPU/时区/重启策略）保存到 AppConfig，重装/更新沿用。
    """
    _save_storages(db, storages)
    if settings:
        _save_settings(db, settings)
    s = _load_settings(db)
    port = s["port"]
    c = _client()
    image = _current_image(db)
    # 确保镜像已拉
    try:
        c.images.get(image)
    except ImageNotFound:
        raise RuntimeError("镜像尚未拉取，请先拉取镜像")
    # 数据目录必须存在
    OPENLIST_DATA_HOST.mkdir(parents=True, exist_ok=True)
    config_exists = (OPENLIST_DATA_HOST / "config.json").exists()
    mounts = {str(OPENLIST_DATA_HOST): {"bind": OPENLIST_DATA_CTR, "mode": "rw"}}
    for st in storages:
        host = Path(st.get("host_path", "")).expanduser()
        mount = st.get("mount_path", "")
        if not host or not mount:
            continue
        host.mkdir(parents=True, exist_ok=True)
        mounts[str(host)] = {"bind": mount, "mode": "rw"}
    # 环境变量：时区 + site_url（--no-prefix 启动，变量名不带 OPENLIST_ 前缀）
    env = {"TZ": s.get("tz") or DEFAULT_SETTINGS["tz"], "SITE_URL": SITE_URL}
    admin_pwd = _get_admin_password(db) if not config_exists else None
    # 资源限制（空=不限）
    mem_limit = s.get("mem_limit") or None
    nano_cpus = None
    if (s.get("cpus") or "").strip():
        nano_cpus = int(float(s["cpus"]) * 1e9)
    # 幂等重装：移除同名旧容器
    try:
        old = c.containers.get(OPENLIST_CONTAINER)
        old.remove(force=True)
    except NotFound:
        pass
    container = c.containers.create(
        image,
        name=OPENLIST_CONTAINER,
        ports={"5244/tcp": ("127.0.0.1", port)},  # 只绑本机，公网不暴露（由 Stella 反代）
        volumes=mounts,
        environment=env,
        user="0:0",  # OpenList v4.1.0+ 默认以 openlist(1001) 运行，root 跑才能写宿主 root 目录
        restart_policy={"Name": s.get("restart_policy") or DEFAULT_SETTINGS["restart_policy"]},  # type: ignore[arg-type]
        mem_limit=mem_limit,
        nano_cpus=nano_cpus,
        detach=True,
    )
    container.start()
    # 全新安装：等 OpenList 就绪后设置 admin 密码（OPENLIST_ADMIN_PASSWORD env 不生效，走 admin set）
    if admin_pwd:
        _wait_and_set_admin_password(admin_pwd)
    # 自动创建「本地存储」对应挂载目录（失败不阻塞安装，仅记录）
    try:
        _sync_storages(db)
    except Exception:
        pass
    # 自动注入 Stella 深色主题（失败不阻塞安装，仅记录）
    try:
        apply_theme(db)
    except Exception:
        pass
    return get_status(db)


# ── 容器管理 ──
def _get_container():
    """取 OpenList 容器（不存在抛 NotFound）。"""
    return _client().containers.get(OPENLIST_CONTAINER)


def start_container(db: Session) -> dict:
    _get_container().start()
    return get_status(db)


def stop_container(db: Session) -> dict:
    _get_container().stop()
    return get_status(db)


def restart_container(db: Session) -> dict:
    _get_container().restart()
    return get_status(db)


def uninstall_container(db: Session, remove_image: bool = False) -> dict:
    """卸载：删容器 + 可选删镜像。保留数据目录（用户文件不删）。"""
    c = _client()
    try:
        c.containers.get(OPENLIST_CONTAINER).remove(force=True)
    except NotFound:
        pass
    if remove_image:
        try:
            c.images.remove(_current_image(db), force=True)
        except (ImageNotFound, NotFound):
            pass
    return get_status(db)


def remove_image(db: Session) -> dict:
    """删镜像（若容器还在，先强制删容器再删镜像）。"""
    c = _client()
    try:
        c.containers.get(OPENLIST_CONTAINER).remove(force=True)
    except NotFound:
        pass
    try:
        c.images.remove(_current_image(db), force=True)
    except (ImageNotFound, NotFound):
        pass
    return get_status(db)


def check_update(db: Session) -> dict:
    """检测更新：本地镜像版本 vs Docker Hub 最新稳定版本。"""
    local = _current_tag(db)
    try:
        _client().images.get(_current_image(db))
    except ImageNotFound:
        return {"local_version": local, "latest_version": None,
                "update_available": False, "error": "本地无镜像"}
    latest, err = _fetch_latest_version()
    if err:
        return {"local_version": local, "latest_version": None,
                "update_available": False, "error": err}
    return {
        "local_version": local,
        "latest_version": latest,
        "update_available": _version_newer(latest, local),
        "error": None,
    }


def pull_latest(db: Session) -> dict:
    """拉最新版本镜像 + 改写 tag（不重建容器，安装阶段或更新都用它）。"""
    check = check_update(db)
    if check["error"]:
        raise RuntimeError(check["error"])
    if not check["update_available"]:
        raise RuntimeError("已是最新版本，无需更新")
    new_tag = check["latest_version"]
    new_image = f"{IMAGE_REPO}:{new_tag}"
    c = _client()
    # 同步拉新镜像（阻塞直到完成），拉完校验是否真的落盘（网络抖动会静默失败）
    c.images.pull(new_image)
    try:
        c.images.get(new_image)
    except ImageNotFound:
        raise RuntimeError(f"拉取镜像 {new_tag} 失败（网络问题，请重试）")
    config_repo.put(db, IMAGE_TAG_KEY, new_tag)
    return get_status(db)


def update_container(db: Session) -> dict:
    """更新到最新版本：拉新镜像 + 重建容器（config 已存在 → 沿用原密码）。"""
    pull_latest(db)
    storages = _load_storages(db)
    return install_container(db, storages)


def _fetch_latest_version() -> tuple[str | None, str | None]:
    """查 Docker Hub 最新稳定版本 tag。返回 (version, error)。"""
    import requests
    try:
        r = requests.get(
            "https://hub.docker.com/v2/repositories/openlistteam/openlist/tags",
            params={"page_size": 50, "ordering": "last_updated"},
            timeout=12,
        )
        if r.status_code != 200:
            return None, f"查询失败 HTTP {r.status_code}"
        tags = [t["name"] for t in r.json().get("results", [])]
        vers = []
        for t in tags:
            m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", t)
            if m:
                vers.append(tuple(int(x) for x in m.groups()))
        if not vers:
            return None, "未找到稳定版本 tag"
        latest = max(vers)
        return "v" + ".".join(map(str, latest)), None
    except Exception as e:  # noqa: BLE001
        return None, f"网络异常：{e}"


def _version_newer(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False

    def parse(v: str) -> tuple:
        m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", v)
        return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)

    return parse(a) > parse(b)


# ── 总状态 ──
def get_status(db: Session) -> dict:
    docker_info = detect_docker()
    image_exists = False
    image_version = None
    container_exists = False
    container_running = False
    container_status = None
    image = _current_image(db)
    if docker_info["running"]:
        try:
            c = _client()
            try:
                c.images.get(image)
                image_exists = True
                image_version = _current_tag(db)
            except ImageNotFound:
                pass
            try:
                ct = c.containers.get(OPENLIST_CONTAINER)
                container_exists = True
                container_status = ct.status
                container_running = ct.status == "running"
            except NotFound:
                pass
        except Exception:
            pass
    return {
        "docker": docker_info,
        "image_exists": image_exists,
        "image_version": image_version,
        "container_exists": container_exists,
        "container_running": container_running,
        "container_status": container_status,
        "storages": _load_storages(db),
        "default_storage": DEFAULT_STORAGE,
        "settings": _load_settings(db),
        "proxy": _get_proxy(db),
        "default_proxy": DEFAULT_PROXY,
        "pull": get_pull_progress(),
    }
