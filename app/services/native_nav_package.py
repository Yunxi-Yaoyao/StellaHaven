"""Portable owner-local package. No network fetches, sessions, secrets or filesystem paths."""
import base64
import copy
import hashlib
import json
import re
from uuid import UUID, uuid5
from fastapi import HTTPException
from app.schemas.native_nav import NavData, Preferences
from app.services.native_nav_budget import canonical, check_config_budget

MAX_SOURCE = 44 * 1024**2
MAX_ASSETS = 100
MAX_BYTES = 30 * 1024**2


def sha(value):
    return hashlib.sha256(value).hexdigest()


def dimensions(content):
    """Bounded header probe only. Never process active SVG/HTML or run a decoder."""
    w = h = None
    mime = None
    if content.startswith(b'\x89PNG\r\n\x1a\n') and len(content)>=33 and content[12:16]==b'IHDR' and content[-8:]==b'IEND\xaeB`\x82':
        w,h = int.from_bytes(content[16:20],'big'),int.from_bytes(content[20:24],'big'); mime='image/png'
    elif content.startswith((b'GIF87a',b'GIF89a')) and len(content)>13 and content.endswith(b';'):
        w,h=int.from_bytes(content[6:8],'little'),int.from_bytes(content[8:10],'little');mime='image/gif'
    elif content.startswith(b'\xff\xd8\xff') and content.endswith(b'\xff\xd9'):
        i=2
        while i+4<len(content):
            if content[i]!=255: break
            marker=content[i+1];i+=2
            if marker in {0xd8,0xd9,0x01} or 0xd0<=marker<=0xd7: continue
            size=int.from_bytes(content[i:i+2],'big')
            if size<2 or i+size>len(content): break
            if marker in {0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf} and size>=7:
                h,w=int.from_bytes(content[i+3:i+5],'big'),int.from_bytes(content[i+5:i+7],'big');mime='image/jpeg';break
            i+=size
    elif len(content)>=30 and content[:4]==b'RIFF' and content[8:12]==b'WEBP' and int.from_bytes(content[4:8],'little')+8==len(content):
        if content[12:16]==b'VP8X': w,h=1+int.from_bytes(content[24:27],'little'),1+int.from_bytes(content[27:30],'little')
        elif content[12:16]==b'VP8 ' and content[23:26]==b'\x9d\x01\x2a': w,h=int.from_bytes(content[26:28],'little')&0x3fff,int.from_bytes(content[28:30],'little')&0x3fff
        elif content[12:16]==b'VP8L' and content[20]==0x2f:
            bits=int.from_bytes(content[21:25],'little');w,h=(bits&0x3fff)+1,((bits>>14)&0x3fff)+1
        mime='image/webp'
    if not mime or not w or not h or w*h>16_000_000: raise HTTPException(415,'素材格式或像素尺寸不安全（最多1600万像素）')
    return mime,w,h


def references(value, prefix='/nav-assets/'):
    if isinstance(value,dict):
        for v in value.values(): yield from references(v,prefix)
    elif isinstance(value,list):
        for v in value: yield from references(v,prefix)
    elif isinstance(value,str) and value.startswith(prefix): yield value


def rewrite(value, mapping):
    if isinstance(value,dict): return {k:rewrite(v,mapping) for k,v in value.items()}
    if isinstance(value,list): return [rewrite(v,mapping) for v in value]
    return mapping.get(value,value) if isinstance(value,str) else value


PANEL = {'backgroundImageSrc':'backgroundUrl','backgroundBlur':'blur','backgroundMaskNumber':'mask','iconTextColor':'textColor','iconTextInfoHideDescription':'hideDescription','iconTextIconHideTitle':'hideTitle','logoText':'title','logoImageSrc':'titleImage','clockShow':'clock','clockShowSecond':'seconds','clockColor':'clockColor','searchBoxShow':'search','searchBoxSearchIcon':'searchIcons','searchBoxBackground':'searchBackground','searchBoxBorderColor':'searchBorder','searchBoxTextColor':'searchText','logoShow':'showTitle','marginTop':'marginTop','marginBottom':'marginBottom','maxWidth':'width','maxWidthUnit':'widthUnit','marginX':'marginX','netModeChangeButtonShow':'networkButton'}


def legacy_data(raw, owner):
    from app.services.native_nav_import import preview
    old=preview(json.dumps(raw['list'],ensure_ascii=False),NavData().model_dump(mode='json'))
    config=raw['userConfig']
    if set(config)-{'panel','searchEngine'}: raise ValueError('unexpected user config')
    panel=config['panel']
    allowed=set(PANEL)|{'iconStyle','theme','footerHtml','systemMonitorShow','systemMonitorShowTitle','systemMonitorPublicVisitModeShow'}
    if set(panel)-allowed: raise ValueError('unknown panel fields')
    p={v:panel[k] for k,v in PANEL.items() if k in panel}
    # Match the actual old CSS: vertical margins percent, horizontal margin px.
    if 'backgroundImageSrc' in panel: p['background']='custom' if panel['backgroundImageSrc'] else 'none'
    if 'iconStyle' in panel:
        if panel['iconStyle'] not in {0,1,'icon','info'}: raise ValueError('layout')
        p['layout']='info' if panel['iconStyle'] in {0,'info'} else 'icon'
    search=config.get('searchEngine')
    if search is not None:
        if set(search)-{'searchEngineList','currentSearchEngine','newWindowOpen'}: raise ValueError('search config')
        p['newWindowOpen']=search.get('newWindowOpen',False)
        p['engines']=[{'id':str(uuid5(owner,'engine:'+str(i)+':'+e['url'])),'title':e['title'],'url':e['url'].replace('%s','{query}'),'icon':e.get('iconSrc','')} for i,e in enumerate(search.get('searchEngineList',[]))]
        p['defaultEngine']=next((e['id'] for e,source in zip(p['engines'],search.get('searchEngineList',[])) if source['url']==search.get('currentSearchEngine',{}).get('url')),None)
    groups=[];warnings=[]
    for i,g in enumerate(old['groups']):
        gid=str(uuid5(owner,'legacy-group:'+str(i)))
        items=[]
        for j,c in enumerate(g['children']):
            item={k:v for k,v in c.items() if k in {'title','url','lanUrl','description','icon','openMethod'}}
            item['id']=str(uuid5(owner,gid+':'+str(j)))
            if item.get('openMethod')==3:
                item['openMethod']=2;warnings.append(f'{g["title"]} / {c["title"]}：旧 openMethod=3 → 独立新标签打开，不嵌入 iframe')
            items.append(item)
        groups.append({**{k:v for k,v in g.items() if k in {'title','description','icon','style'}},'id':gid,'items':items})
    warnings.extend(['旧 theme 归并 Stella 全站主题，不覆盖主站外观','旧 footerHtml 不执行；系统监控使用 Stella 现有节点中心，不新建导航监控'])
    return {'groups':groups,'preferences':p},warnings


def parse(source, owner, existing=None):
    if len(source.encode())>MAX_SOURCE: raise HTTPException(413,'完整包超过44 MiB')
    try:
        raw=json.loads(source,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        legacy=raw.get('appName')=='Stella-Nav-Transfer' and raw.get('version')==1
        if legacy:
            if set(raw)!={'appName','version','list','userConfig','assets'}: raise ValueError()
            data,warnings=legacy_data(raw,owner)
        else:
            if set(raw)!={'appName','version','data','assets','counts','sha256'} or raw['appName']!='Stella-Native-Nav-Package' or raw['version']!=2: raise ValueError()
            if raw['sha256']!=sha(canonical({k:v for k,v in raw.items() if k!='sha256'}).encode()): raise ValueError()
            data=copy.deepcopy(raw['data']);warnings=[]
        assets=raw['assets']
        if not isinstance(assets,list) or len(assets)>MAX_ASSETS: raise ValueError()
        total=0;mapping={};planned=[]
        for a in assets:
            if set(a) not in ({'source','name','mime','size','sha256','base64'}, {'source','name','mime','size','sha256','base64','category'}): raise ValueError()
            category=a.get('category','uncategorized')
            if category not in {'uncategorized','icon','background','logo','other'}: raise ValueError()
            src=a['source']
            if not isinstance(src,str) or src in mapping: raise ValueError()
            if legacy:
                if not re.fullmatch(r'/files/[A-Za-z0-9_./-]{1,200}',src) or '..' in src: raise ValueError()
            elif not re.fullmatch(r'/nav-assets/[0-9a-f-]{36}',src): raise ValueError()
            if not isinstance(a['name'],str) or not 1<=len(a['name'])<=120: raise ValueError()
            if not isinstance(a['base64'],str) or len(a['base64'])>4*1024**2: raise ValueError()
            content=base64.b64decode(a['base64'],validate=True)
            if len(content)>3*1024**2 or len(content)!=a['size'] or sha(content)!=a['sha256']: raise ValueError()
            mime,w,h=dimensions(content)
            if mime!=a['mime']: raise ValueError()
            total+=len(content)
            if total>MAX_BYTES: raise ValueError()
            # Content + source identity are scoped to destination owner, never trust source IDs.
            aid=uuid5(owner,src+':'+a['sha256'])
            # A native same-owner roundtrip reuses only server-proven identical
            # owned bytes. A source package cannot assert ownership itself.
            if not legacy and existing and existing.get(src)==a['sha256']:
                aid=UUID(src.removeprefix('/nav-assets/'))
            mapping[src]='/nav-assets/'+str(aid)
            planned.append({'id':aid,'name':a['name'],'mime':mime,'size':len(content),'content':content,'sha256':a['sha256'],'width':w,'height':h,'source':src,'category':category})
        refs=set(references(data))|set(references(data,'/files/'))
        if not refs<=set(mapping): raise ValueError('missing owner asset bytes')
        data=NavData.model_validate(rewrite(data,mapping)).model_dump(mode='json')
        check_config_budget(data)
        counts={'groups':len(data['groups']),'items':sum(len(g['items']) for g in data['groups']),'assets':len(planned),'bytes':total}
        if not legacy and raw['counts']!=counts: raise ValueError()
        return data,planned,counts,warnings
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError):
        raise HTTPException(422,'完整包字段、计数、哈希、偏好或素材引用无效；未写入') from None


def package(data, assets):
    data=NavData.model_validate(data).model_dump(mode='json')
    rows=[{'source':'/nav-assets/'+str(a.id),'name':a.name,'mime':a.mime,'size':a.size,'sha256':sha(a.content),'base64':base64.b64encode(a.content).decode(),'category':a.category} for a in assets]
    value={'appName':'Stella-Native-Nav-Package','version':2,'data':data,'assets':rows,'counts':{'groups':len(data['groups']),'items':sum(len(g['items']) for g in data['groups']),'assets':len(rows),'bytes':sum(a['size'] for a in rows)}}
    value['sha256']=sha(canonical(value).encode())
    return value


def preview(source, owner, current, existing=None):
    data,assets,counts,warnings=parse(source,owner,existing)
    return {'digest':sha(source.encode()),'counts':counts,'data':data,'warnings':warnings,
            'asset_mappings':[{k:str(a[k]) for k in ('source','id','sha256','size','width','height')} for a in assets],
            'preference_changes':{k:{'before':current['preferences'].get(k),'after':v} for k,v in data['preferences'].items() if current['preferences'].get(k)!=v},
            'before_counts':{'groups':len(current['groups']),'items':sum(len(g['items']) for g in current['groups'])},
            'boundary':'确认后原子替换导航聚合；新增owner安全素材，保留现有未引用素材；不写旧站、不修改账号/会话/其他设置。'}
