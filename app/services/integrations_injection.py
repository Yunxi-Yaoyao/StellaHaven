"""Trusted target-only injection; draft != active, explicit CSP permission."""
import json
import re
import secrets
import shutil
import subprocess
from uuid import uuid4
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from app.services import integrations as store
from app.services.backup_health import record_change


class InjectionInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled: bool=False
    css: str=''
    js: str=''
    timing: str='dom_ready'
    csp_policy: str='reject'

    @field_validator('css','js')
    @classmethod
    def size(cls,value,info):
        limit=65536 if info.field_name=='css' else 131072
        if len(value.encode('utf-8'))>limit or '\x00' in value:
            raise ValueError('代码过长或包含 NUL')
        return value

    @field_validator('timing')
    @classmethod
    def valid_timing(cls,value):
        if value not in {'dom_ready','document_start'}: raise ValueError('不支持的注入时机')
        return value

    @field_validator('csp_policy')
    @classmethod
    def valid_csp(cls,value):
        if value not in {'reject','controlled'}: raise ValueError('不支持的 CSP 策略')
        return value


def errors(value,module,target):
    problems=[]
    if value['enabled'] and module['mode']!='isolated_proxy':
        problems.append('此接法不能由 Stella 注入；请选择隔离 origin 代理')
    if value['csp_policy']=='controlled' and not (target and target['controlled']):
        problems.append('CSP 修改仅允许已批准的受控上游')
    if value['js']:
        node=shutil.which('node')
        if not node:
            problems.append('服务器缺少 node，无法检查 JavaScript 语法，拒绝发布')
        else:
            try:
                result=subprocess.run([node,'--check','-'],input=value['js'],text=True,capture_output=True,timeout=3)
                if result.returncode: problems.append('JavaScript 语法检查失败')
            except (OSError,subprocess.TimeoutExpired):
                problems.append('JavaScript 检查失败或超时')
    return problems


def validate_draft(db,mid,incoming):
    value=incoming.model_dump()
    with store.edit(db) as config:
        module=config['modules'].get(mid)
        if not module: raise HTTPException(404,'模块不存在')
        problems=errors(value,module,config['targets'].get(module['target_id']))
        module['injection']['draft']=value
    return dict(valid=not problems,errors=problems,draft=value)


def apply(db,mid,actor_id):
    with store.edit(db) as config:
        module=config['modules'].get(mid)
        if not module: raise HTTPException(404,'模块不存在')
        value=module['injection']['draft']
        if value is None: raise HTTPException(422,'没有可发布草稿')
        problems=errors(value,module,config['targets'].get(module['target_id']))
        if problems: raise HTTPException(422,{'errors':problems})
        module['injection']['previous']=module['injection']['active']
        module['injection']['active']=value | {'version':uuid4().hex}
        record_change(db,action='injection.apply',actor_id=actor_id,resource_id=mid,changed_fields=['injection'])
        output=module['injection'].copy()
    return output


def rollback(db,mid,actor_id):
    with store.edit(db) as config:
        module=config['modules'].get(mid)
        if not module: raise HTTPException(404,'模块不存在')
        injection=module['injection']
        if injection['previous'] is None: raise HTTPException(409,'没有上一版本')
        binding = config.get('website_version_origins',{}).get(mid,{}).get(injection['previous']['version'])
        if binding:
            from app.services.website_check import origin
            target = config['targets'].get(module.get('target_id'))
            if not target or origin(binding) != origin(target['upstream_url']):
                raise HTTPException(409,'上一版本属于旧网站身份，不能在新站自动回退执行')
        injection['active'],injection['previous']=injection['previous'],injection['active']
        record_change(db,action='injection.rollback',actor_id=actor_id,resource_id=mid,changed_fields=['injection'])
        output=injection.copy()
    return output


def safe_json(value):
    # JSON strings in an HTML script raw-text context MUST escape '<'; textContent
    # restores literal CSS/JS, including </style>, </script>, Unicode separators.
    return json.dumps(value,ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')


def inject_html(html,mid,active,nonce=''):
    if not active or not active['enabled']: return html,False
    marker=f'<meta name="stella-injection" content="{mid}:{active["version"]}">'
    if marker in html: return html,False
    payload=safe_json(dict(id=mid,version=active['version'],css=active['css'],js=active['js'],timing=active['timing'],nonce=nonce))
    code="""(()=>{const p=PAYLOAD;const key='__stellaInjection_'+p.id;if(window[key]===p.version)return;window[key]=p.version;const style=document.createElement('style');style.dataset.stellaIntegration=p.id;style.nonce=p.nonce;style.textContent=p.css;(document.head||document.documentElement).appendChild(style);const run=()=>{if(!p.js)return;const script=document.createElement('script');script.nonce=p.nonce;script.dataset.stellaIntegration=p.id;script.textContent=p.js;(document.head||document.documentElement).appendChild(script);};if(p.timing==='document_start'||document.readyState!=='loading')run();else document.addEventListener('DOMContentLoaded',run,{once:true});})();""".replace('PAYLOAD',payload)
    fragment=marker+f'<script nonce="{nonce}">'+code+'</script>'
    match=re.search(r'<head\b[^>]*>',html,re.I)
    if match:
        offset=match.end()
    else:
        opening=re.search(r'<html\b[^>]*>',html,re.I) or re.search(r'<!doctype\b[^>]*>',html,re.I)
        offset=opening.end() if opening else 0
    return html[:offset]+fragment+html[offset:],True


def controlled_csp(policy,nonce,parent_origin):
    directives={}
    for item in policy.split(';'):
        parts=item.strip().split()
        if parts and parts[0].lower() not in directives: directives[parts[0].lower()]=parts[1:]
    default=directives.get('default-src',[])
    for name in ('script-src','style-src','script-src-elem','style-src-elem'):
        inherited=directives.get(name,directives.get(name.removesuffix('-elem'),default))
        directives[name]=[v for v in inherited if v!="'none'"]+[f"'nonce-{nonce}'"]
    directives['frame-ancestors']=[parent_origin]
    return '; '.join(' '.join([k]+v) for k,v in directives.items())
