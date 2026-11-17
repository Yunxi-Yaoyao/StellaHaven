"""Synthetic source matches current yaya-nav export and userConfig types, never real accounts."""
import base64
import hashlib
import json

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qXYAAAAASUVORK5CYII=')


def transfer():
    old={'version':1,'appName':'Stella-Nav-Config','exportTime':'2026-10-23','appVersion':'1',
         'icons':[{'title':'合成完整迁入','description':'仅fixture','sort':0,'style':{'layout':'info','hideDescription':False},'children':[
             {'title':'文档','url':'https://example.test/docs','lanUrl':'http://192.0.2.1/docs','description':'旧站合成卡片','sort':0,'icon':{'itemType':2,'src':'/files/synthetic.png'},'openMethod':3}]}]}
    old['md5']=hashlib.md5(json.dumps(old,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    panel={'backgroundImageSrc':'/files/synthetic.png','backgroundBlur':2,'backgroundMaskNumber':.4,'iconStyle':0,'iconTextColor':'#abc','iconTextInfoHideDescription':True,'iconTextIconHideTitle':False,'logoText':'合成导航','logoImageSrc':'/files/synthetic.png','clockShow':True,'clockShowSecond':True,'clockColor':'#abcd','searchBoxShow':True,'searchBoxSearchIcon':True,'searchBoxBackground':'#1234','searchBoxBorderColor':'#123456','searchBoxTextColor':'#ffffff','logoShow':True,'marginTop':4,'marginBottom':10,'maxWidth':85,'maxWidthUnit':'%','marginX':5,'netModeChangeButtonShow':False,'theme':'auto','footerHtml':'<script>never-execute</script>','systemMonitorShow':True,'systemMonitorShowTitle':True,'systemMonitorPublicVisitModeShow':False}
    engines=[{'title':'首个','url':'https://example.test/?q=%s','iconSrc':'/files/synthetic.png'},{'title':'当前默认','url':'https://example.test/search?q=%s','iconSrc':''}]
    return {'appName':'Stella-Nav-Transfer','version':1,'list':old,'userConfig':{'panel':panel,'searchEngine':{'searchEngineList':engines,'currentSearchEngine':engines[1],'newWindowOpen':False}},'assets':[{'source':'/files/synthetic.png','name':'合成像素','mime':'image/png','size':len(PNG),'sha256':hashlib.sha256(PNG).hexdigest(),'base64':base64.b64encode(PNG).decode()}]}

if __name__=='__main__':
    print(json.dumps(transfer(),ensure_ascii=False))
