"""Materialize effective defaults of the inspected dirty yaya-nav revision only.

The legacy DB stores sparse overrides. Preserve the source defaults too, rather
than silently importing native defaults. Unknown source hashes fail closed.
Builtin SVG logos are rasterized locally to inert PNG; original bytes and hashes
remain in provenance. No fetch, login, application import or source write.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

PINS={
 'src/enums/panel/index.ts':'6f4793195d636d1224d52fedaf74813ac9380f25646efd4baf74e2835bf799a1',
 'src/store/modules/panel/helper.ts':'b14cb3cd3a4b35a6b63163688c59de2bff99b0d08561c885cf71699236708077',
 'src/utils/searchEngines.ts':'f7c8e3f0462da264d64fb1dba5e74b647780a9d8a6e23e4704cac70b9faf9070',
 'src/utils/searchAppearance.ts':'592c9aa2a460a7858ee726a81b0e849c4add17c7b0b24776901097cb39818966',
 'src/assets/defaultBackground.webp':'80f713c82c8138a59b5c807e0d726043242a8ae24a92416e4b48caeeb2c58526',
 'src/assets/search_engine_svg/google.svg':'c8534e94ea138ce532a65cb5b85efa80397c83c8c06ce4f2bbd776f334fb87d5',
 'src/assets/search_engine_svg/bing.svg':'4e21c40a31ee07ab81ee9800a0cdf5fe2c90d345abba5f3c388932fd751280fa',
 'src/assets/search_engine_svg/baidu.svg':'604a969ad00e0e82a16f65fcd7e061bff929c7051996e26ef6023f960f3ab795',
}

def sha(value):return hashlib.sha256(value).hexdigest()

def build(root):
    root=Path(root);sources={}
    for name,digest in PINS.items():
        file=root/name
        if not file.is_file() or file.is_symlink() or sha(file.read_bytes())!=digest:raise ValueError('legacy source is not the inspected supported version: '+name)
        sources[name]=file.read_bytes()
    assets=[];raw_svg=[]
    def add(name,content,mime,category):
        url='/files/__legacy_builtin/'+name
        assets.append({'source':url,'name':name,'mime':mime,'size':len(content),'sha256':sha(content),'base64':base64.b64encode(content).decode(),'category':category})
        return url
    background=add('default-background.webp',sources['src/assets/defaultBackground.webp'],'image/webp','background')
    engines=[]
    for name,title,url in [('google','Google','https://www.google.com/search?q=%s'),('bing','Bing','https://www.bing.com/search?q=%s'),('baidu','百度','https://www.baidu.com/s?wd=%s')]:
        source=sources['src/assets/search_engine_svg/'+name+'.svg']
        with tempfile.TemporaryDirectory(prefix='nav-defaults-render-',dir=os.environ['TMPDIR']) as cache:
            rendered=subprocess.run(['/usr/sbin/rsvg-convert','--format=png','--width=64','--height=64'],input=source,capture_output=True,check=True,timeout=15,env={'PATH':'/usr/bin:/bin','HOME':cache,'XDG_CACHE_HOME':cache})
        icon=add(name+'.png',rendered.stdout,'image/png','icon')
        engines.append({'title':title,'url':url,'iconSrc':icon})
        raw_svg.append({'name':name+'.svg','sha256':sha(source),'base64':base64.b64encode(source).decode()})
    panel={'backgroundImageSrc':background,'backgroundBlur':0,'backgroundMaskNumber':0.35,'iconStyle':1,'iconTextColor':'#ffffff','iconTextInfoHideDescription':False,'iconTextIconHideTitle':False,'logoText':'云曦的导航','theme':'dark','clockShow':False,'logoImageSrc':'','clockShowSecond':False,'searchBoxBackground':'#202126ef','searchBoxBorderColor':'#ffffff45','searchBoxTextColor':'#ffffff','logoShow':True,'searchBoxShow':True,'searchBoxSearchIcon':True,'marginBottom':10,'marginTop':4,'maxWidth':1200,'maxWidthUnit':'px','marginX':5,'footerHtml':'','systemMonitorShow':False,'systemMonitorShowTitle':True,'systemMonitorPublicVisitModeShow':False,'netModeChangeButtonShow':True}
    return {'panel':panel,'searchEngine':{'searchEngineList':engines,'currentSearchEngine':engines[0],'newWindowOpen':False},'assets':assets,'provenance':{'source_files':PINS,'builtin_svg_originals':raw_svg,'svg_conversion':'rsvg-convert --format=png --width=64 --height=64','device_network':'not exported; device scoped','theme_footer_monitors':'explicit native platform differences in preflight'}}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--legacy-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    value=build(args.legacy_root)
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream,ensure_ascii=False,separators=(',',':'))
    print(json.dumps({'source_files':PINS,'builtin_assets':len(value['assets']),'sha256':sha(args.output.read_bytes())}))
