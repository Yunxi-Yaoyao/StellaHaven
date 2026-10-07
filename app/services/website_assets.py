"""Origin-bound classic loader. Only authenticated owners receive active code."""
from urllib.parse import urlsplit
from app.services import integrations as store
from app.services.integrations_injection import safe_json


def asset_code(db, mid, *, custom_allowed=False):
    if not custom_allowed: return '/* Owner session required. */'
    module = store.state(db)['modules'].get(mid)
    if not module or not module.get('enabled') or module['mode'] != 'iframe' or module.get('connection',{}).get('injection_delivery') != 'loader':
        return '/* Website loader inactive. */'
    active = module.get('injection',{}).get('active')
    if not active or not active.get('enabled'): return '/* Website customization disabled. */'
    url = urlsplit(module['browser_url'])
    from app.services.request_security import canonical_origin
    payload = safe_json(dict(id=mid, origin=canonical_origin(url.scheme+'://'+url.netloc), version=active['version'], css=active['css'], js=active['js'], timing=active['timing']))
    return """(()=>{const p=PAYLOAD;if(location.origin!==p.origin)return;
const key='__stellaInjection_'+p.id;if(window[key]===p.version)return;window[key]=p.version;
const style=document.createElement('style');style.dataset.stellaIntegration=p.id;style.textContent=p.css;(document.head||document.documentElement).appendChild(style);
const run=()=>{if(!p.js)return;const script=document.createElement('script');script.dataset.stellaIntegration=p.id;script.textContent=p.js;(document.head||document.documentElement).appendChild(script);};
if(p.timing==='document_start'||document.readyState!=='loading')run();else document.addEventListener('DOMContentLoaded',run,{once:true});})();""".replace('PAYLOAD',payload)
