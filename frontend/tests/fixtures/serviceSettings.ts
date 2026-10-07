// Synthetic configuration only. No production endpoints or credentials.
export function serviceFixture(site: 'drive'|'gallery' = 'drive') {
  return {
    site, name: site === 'drive' ? '网盘' : '图库', icon: site === 'drive' ? 'drive' : 'image', visible: true,
    connection: site === 'drive'
      ? {service_url: 'http://owned.test:5244/drive/openlist', auth_mode: 'token', has_token: true}
      : {browser_url: 'https://owned-gallery.test', upstream_url: '', alternate_browser_url: '', auth_mode: 'oidc'},
    appearance: site === 'drive' ? {theme: 'stella', simplified: true} : {logo: 'stella'},
    injection: {draft: null, active: {enabled: false, css: '', js: '', timing: 'dom_ready', csp_policy: 'reject', version: 'preset-v1', status: 'active'}, previous: null},
    capabilities: {background: site === 'drive', oidc: site === 'gallery'},
    scopes: {appearance: site === 'drive' ? 'embedded' : 'domain', background: site === 'drive' ? 'device' : null},
    oidc: site === 'gallery' ? {client_registered: true, issuer: 'https://owned-stella.test', client_id: 'immich', redirect_uris: ['https://owned-gallery.test/auth/login']} : null,
    compatibility: ['缓存与权限适配保持启用'],
  };
}
