"""Read-only compatibility preflight; never claims a website list is a backup."""
import copy
import hashlib
import json
from uuid import uuid5, NAMESPACE_URL
from pydantic import ValidationError
from fastapi import HTTPException
from app.schemas.native_nav import NavData, Style

def preview(source, current):
    if len(source.encode())>2*1024*1024: raise HTTPException(413,'导入文件超过 2 MiB')
    try:
        raw=json.loads(source)
        if not isinstance(raw,dict): raise ValueError()
        native=raw.get('appName')=='Stella-Native-Nav' and raw.get('version')==1
        if native:
            data=NavData.model_validate(raw['data']).model_dump(mode='json')
            groups=copy.deepcopy(data['groups'])
            for g in groups: g['children']=g.pop('items')
        else:
            if raw.get('appName') not in {'Sun-Panel-Config','Stella-Nav-Config'} or raw.get('version')!=1 or not isinstance(raw.get('exportTime'),str) or not isinstance(raw.get('appVersion'),str): raise ValueError()
            unsigned={k:v for k,v in raw.items() if k!='md5'}
            digest=hashlib.md5(json.dumps(unsigned,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            if digest!=raw.get('md5'): raise ValueError('文件校验失败')
            groups=copy.deepcopy(raw.get('icons',[]))
        if not isinstance(groups,list) or len(groups)>100: raise ValueError()
        assets=set(); decisions=[]; mappings=[]
        titles={g['title'] for g in current['groups']}
        count=0
        def scan(value):
            if isinstance(value,dict):
                for v in value.values(): scan(v)
            elif isinstance(value,list):
                for v in value: scan(v)
            elif isinstance(value,str) and value.startswith(('/files/','/nav-assets/')): assets.add(value)
        for gi,g in enumerate(groups):
            if not isinstance(g,dict) or not isinstance(g.get('title'),str) or not 1<=len(g['title'])<=100 or not isinstance(g.get('children'),list): raise ValueError()
            if g.get('style') is not None: Style.model_validate(g['style'])
            matches=[x for x in current['groups'] if (native and x['id']==g.get('id')) or (not native and x['title']==g['title'])]
            existing=matches[0] if len(matches)==1 else None
            if len(matches)>1: decisions.append(f'{g["title"]}：同名分组不唯一，需人工指定目标')
            mapped_id=existing['id'] if existing else str(uuid5(NAMESPACE_URL,f'stella-nav-preview:group:{gi}:{g["title"]}'))
            group_fields={key:copy.deepcopy(g.get(key)) for key in ('title','description','icon','style') if key in g}
            mappings.append({'source_index':gi,'target_id':mapped_id,'title':g['title'],'action':'compare' if existing else 'add','sort':g.get('sort',gi),'fields':group_fields,'changes':{key:{'before':existing.get(key) if existing else None,'after':value} for key,value in group_fields.items() if not existing or existing.get(key)!=value}})
            for ci,item in enumerate(g['children']):
                if not isinstance(item,dict) or not isinstance(item.get('title'),str) or not isinstance(item.get('url',''),str): raise ValueError()
                count+=1
                if item.get('openMethod')==3: decisions.append(f'{g["title"]} / {item["title"]}：旧嵌入打开方式需映射到现有网站模块或明确改为链接')
                fields={key:copy.deepcopy(item.get(key)) for key in ('title','url','lanUrl','description','icon','openMethod','module_id') if key in item}
                candidates=[c for c in (existing['items'] if existing else []) if (native and c['id']==item.get('id')) or (not native and c.get('url','')==item.get('url','') and c.get('lanUrl','')==item.get('lanUrl',''))]
                target=candidates[0] if len(candidates)==1 else None
                if len(candidates)>1: decisions.append(f'{g["title"]} / {item["title"]}：目标网址重复，需人工指定卡片')
                mappings.append({'group_index':gi,'source_index':ci,'target_id':target['id'] if target else str(uuid5(NAMESPACE_URL,f'{mapped_id}:card:{ci}')),'title':item['title'],'action':'compare' if target else 'add','sort':item.get('sort',ci),'fields':fields,'changes':{key:{'before':target.get(key) if target else None,'after':value} for key,value in fields.items() if not target or target.get(key)!=value}})
        if count>2000: raise ValueError()
        scan(raw)
        return {'kind':'native' if native else 'legacy-list','source':raw,'groups':groups,'counts':{'groups':len(groups),'items':count},'mapping':mappings,'asset_mappings':[{'source':s,'target':None,'status':'requires-owner-asset-transfer'} for s in sorted(assets)],'requires_decisions':decisions,'settings_missing':[] if native else ['完整 panel 偏好','搜索引擎配置','素材记录与字节','分组图标和描述（旧清单未包含）'],'settings':raw.get('data',{}).get('preferences') if native else raw.get('styleConfig'),'boundary':'仅解析及差异预览，未写入。网站清单不含完整设置与素材；素材必须按 owner 转移并重写引用。','current_counts':{'groups':len(current['groups']),'items':sum(len(g['items']) for g in current['groups'])}}
    except (ValueError,TypeError,KeyError,RecursionError,ValidationError):
        raise HTTPException(422,'不是有效的兼容导航导出，或文件校验失败') from None
