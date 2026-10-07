"""Actual isolated Chromium/HTTP proofs, with only synthetic SQLite data."""
import json
import os
import subprocess
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from tests_service_settings.test_api import api, elevate, payload
from tests_builtin.test_builtin_browser import local_server
from app.services import builtin_injection as builtin


def browser(origin, mode, tmp_path):
    runner=Path(__file__).with_name('appearance_browser.mjs')
    result=subprocess.run(['node',str(runner)],env=os.environ|{'APPEARANCE_ORIGIN':origin,'APPEARANCE_MODE':mode,'APPEARANCE_SCREENSHOT':str(tmp_path/(mode+'.png'))},text=True,capture_output=True,timeout=40)
    assert result.returncode==0,result.stdout+result.stderr
    evidence=json.loads(result.stdout)
    assert evidence['errors']==[]
    print('BROWSER_EVIDENCE='+json.dumps(evidence,ensure_ascii=False))
    return evidence


def test_original_drive_retains_compatibility_no_filename_damage(api,tmp_path):
    client,factory,_,_=api;elevate(client)
    assert client.put('/service-settings/drive',json=payload()).status_code==200
    from app.services.drive import OPENLIST_THEME_CSS,OPENLIST_THEME_JS
    upstream='''<html><head><title>OpenList filename</title><style>body{background:rgb(12,34,56)}</style>LEGACY<script>
window.cache=new Map([['/src',1],['/dst',1]]);
document.addEventListener('click',e=>{const a=e.target.closest('a');if(a)cache.delete(a.getAttribute('href'))},true);
</script></head><body><div id="root"><header><span id="brand">OpenList</span><a id="project" href="https://github.com/OpenListTeam/OpenList">Project</a><a id="header-other" href="https://github.com/example/docs">Docs</a><button aria-label="switch layout">layout</button></header><nav class="hope-breadcrumb"></nav><main><span class="list-item" id="file">OpenList backups.tar</span><a id="file-link" href="https://github.com/OpenListTeam/OpenList">OpenList file link</a><a id="other-link" href="https://github.com/example/readme">GitHub file</a></main></div></body></html>'''.replace('LEGACY',f'<style>{OPENLIST_THEME_CSS}</style><script>{OPENLIST_THEME_JS}</script>')
    app=FastAPI();denied=[]
    @app.get('/')
    def html():
        with factory() as db:return HTMLResponse(builtin.transform_html(upstream,'drive',db))
    @app.post('/api/fs/move')
    def move():return {'code':200}
    @app.post('/api/fs/remove')
    def remove():
        denied.append(True)
        return JSONResponse({'detail':{'code':'admin_elevation_required'}},status_code=403)
    with local_server(app) as origin:
        evidence=browser(origin,'drive-original',tmp_path)
        assert evidence['color']=='rgb(12, 34, 56)'
        assert len(denied)==2
        data=payload();data['appearance']['simplified']=True
        assert client.put('/service-settings/drive',json=data).status_code==200
        browser(origin,'drive-simple',tmp_path)


def test_gallery_persistent_logo_anonymous_no_custom_cleanup(api,tmp_path,monkeypatch):
    client,factory,_,_=api;elevate(client)
    data=payload('gallery')|{'custom':{'enabled':True,'js':'window.ownerOnlySecret=91;'}}
    assert client.put('/service-settings/gallery',json=data).status_code==200
    app=FastAPI()
    @app.get('/')
    def html():return HTMLResponse('<html><head><style data-stella-gallery-base="v1">'+builtin.GALLERY_LOGO_CSS+'</style></head><body><img alt="Immich logo"><h1>Gallery</h1></body></html>')
    @app.get('/code.js')
    def code():
        from fastapi.responses import Response
        with factory() as db:
            script,version=builtin.gallery_asset(db,custom_allowed=False)
        return Response(script,media_type='application/javascript',headers={'X-Stella-Injection-Version':version})
    with local_server(app) as origin:
        monkeypatch.setenv('STELLA_GALLERY_CLIENT_ORIGINS',origin)
        original=browser(origin,'gallery-original',tmp_path)
        assert 'ownerOnlySecret' not in original['code']
        data['appearance']['logo']='stella'
        assert client.put('/service-settings/gallery',json=data).status_code==200
        branded=browser(origin,'gallery-stella',tmp_path)
        assert branded['version']!=original['version']
        assert 'ownerOnlySecret' not in branded['code']
    assert '<style' not in builtin.gallery_head_loader()
