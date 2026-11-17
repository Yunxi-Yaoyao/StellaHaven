"""Owned PG + full main.py lifespan + production App build media-picker journeys.

No production credentials/DB, no restored source package, no host installation.
Run with a pinned existing Python, scrubbed environment, NAV_MEDIA_EVIDENCE new
scratch directory and NAV_MEDIA_DIST pointing at the full Vite build.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
NODE = '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'


def child():
    from qa.native_nav_pg_guard import target, verify_connection
    port, database, username, container = target()
    def connection_guard(event, args):
        if event=='socket.connect':
            address=args[1]
            if not isinstance(address,tuple) or address[:2] != ('127.0.0.1',port):
                raise RuntimeError('owned-PG-only network fence rejected '+repr(address))
    sys.addaudithook(connection_guard)
    from app.database import Base, engine, sessionLocal
    import main
    import app.models
    from app.models.user import User
    from app.models.config import AppConfig
    from app.routers import auth
    from app.services.admin_security import STATE_KEY
    from app.services import blob_store
    from starlette.requests import Request
    from starlette.responses import Response
    import uvicorn
    out = Path(os.environ['NAV_MEDIA_EVIDENCE'])
    with engine.connect() as db:
        verify_connection(db, database, username)
    Base.metadata.create_all(engine)
    # Actual main routes/lifespan and database factory, not get_db overrides.
    main.FRONTEND_DIR = Path(os.environ['NAV_MEDIA_DIST'])
    owner = uuid4()
    with sessionLocal() as db:
        user = User(id=owner, username='media-picker-owner', display_name='Media QA', home_bg='/assets/homebg/synthetic-home.png')
        db.add(user)
        db.add(AppConfig(key=STATE_KEY, value=json.dumps({'owner_id':str(owner)})))
        db.commit()
        request = Request({'type':'http','scheme':'https','server':('127.0.0.1',int(os.environ['NAV_HTTP_PORT'])),'path':'/auth/login','headers':[(b'host',os.environ['STELLA_MAIN_ORIGIN'].removeprefix('https://').encode())],'query_string':b'','client':('127.0.0.1',12345)})
        response = Response()
        auth._create_session(db,user,request,response,False)
        cookies = [{'name':c.split('=',1)[0],'value':c.split('=',1)[1].split(';',1)[0],'domain':'127.0.0.1','path':'/','secure':True,'httpOnly':True,'sameSite':'Lax'} for c in response.headers.getlist('set-cookie')]
        db.commit()
    import io
    import struct
    import zlib
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    image=io.BytesIO(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',320,180,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\x24\x4b\x66'*320)*180))+chunk(b'IEND',b''))
    # A fresh App bootstraps the real default bgImage into account preferences.
    # Supply that built-in URL too: PG must not accept a missing local resource.
    packaged_default = subprocess.run(['ffmpeg','-v','error','-nostdin','-f','image2pipe','-i','pipe:0','-frames:v','1','-c:v','libwebp','-f','webp','pipe:1'],input=image.getvalue(),capture_output=True,check=True).stdout
    with sessionLocal() as db:
        blob_store.put(db,'homebg/default-bg-kimono-1920.webp',io.BytesIO(packaged_default),'image/webp',100000)
        blob_store.put(db,'homebg/synthetic-home.png',io.BytesIO(image.getvalue()),'image/png',100000)
        db.add(AppConfig(key='homebg_index',value=json.dumps([{'id':'synthetic-home','name':'Synthetic home protected','file':'synthetic-home.png','ext':'png','isDefault':False,'owner':str(owner),'media':{'url':'/assets/homebg/synthetic-home.png','status':'ready','variants':{'original':'/assets/homebg/synthetic-home.png'},'thumbnail':'/assets/homebg/synthetic-home.png'}}])))
        db.commit()
    state=out/'private-state.json';state.write_text(json.dumps({'cookies':cookies,'origins':[]}));state.chmod(0o600)
    (out/'synthetic.png').write_bytes(image.getvalue())
    subprocess.run(['ffmpeg','-v','error','-nostdin','-f','lavfi','-i','testsrc2=size=320x180:rate=12','-t','1','-c:v','libx264','-crf','0','-preset','ultrafast','-pix_fmt','yuv420p','-movflags','+faststart',str(out/'synthetic.mp4')],check=True)
    (out/'broken.mp4').write_bytes(b'not an mp4: synthetic codec failure')
    cert,key=out/'cert.pem',out/'private-key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    sock=socket.socket();sock.bind(('127.0.0.1',int(os.environ['NAV_HTTP_PORT'])));sock.listen()
    server=uvicorn.Server(uvicorn.Config(main.app,log_level='warning',ssl_keyfile=str(key),ssl_certfile=str(cert)))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    deadline=time.monotonic()+20
    while not server.started:
        assert thread.is_alive() and time.monotonic()<deadline,'full main startup failed'
        time.sleep(.02)
    try:
        result=subprocess.run([NODE,str(ROOT/'frontend/e2e/native-nav-media-picker.mjs')],cwd=out,env={**os.environ,'PLAYWRIGHT_BROWSERS_PATH':'/root/.cache/ms-playwright'},capture_output=True,text=True,timeout=150)
        (out/'browser.log').write_text(result.stdout+result.stderr)
        assert result.returncode==0,result.stdout+result.stderr
        from app.models.native_nav import NavState
        with sessionLocal() as db:
            assert db.get(User,owner).home_bg=='/assets/homebg/synthetic-home.png'
            nav=db.get(NavState,owner)
            assert nav is not None and nav.revision==1
            entries=json.loads(db.get(AppConfig,'homebg_index').value)
            assert len(entries)==3 and {e['name'] for e in entries}=={'Synthetic home protected','synthetic','broken'}
            broken=next(e for e in entries if e['name']=='broken')
            assert broken['media']['status']=='error'
            assert blob_store.metadata(db,'homebg/'+broken['file'])['size']==len((out/'broken.mp4').read_bytes())
            (out/'pg-readback.json').write_text(json.dumps({'full_main_lifespan':True,'full_app_build':True,'nav_revision':nav.revision,'home_unchanged':True,'retained_media':len(entries),'failed_original_retained':True,'synthetic_deleted_absent':True},indent=2))
    finally:
        server.should_exit=True;thread.join(timeout=20);sock.close()
        state.unlink(missing_ok=True);key.unlink(missing_ok=True)
        assert not thread.is_alive(),'full main shutdown failed'
    print('full main/App media-picker browser + PG readback passed')


def parent():
    out=Path(os.environ['NAV_MEDIA_EVIDENCE']).resolve()
    assert out.is_relative_to(Path(os.environ['TMPDIR']).resolve())
    out.mkdir(mode=0o700,parents=True,exist_ok=False)
    nonce=uuid4().hex;name='stella-nav-media-'+nonce[:12];database='navqa_'+nonce[:12]
    container=subprocess.check_output(['docker','run','-d','--name',name,'--label','stella.navqa.purpose=native-nav-tests','--label','stella.navqa.nonce='+nonce,'--memory','512m','--cpus','2','--tmpfs','/var/lib/postgresql:rw,size=256m','-p','127.0.0.1::5432','-e','POSTGRES_DB='+database,'-e','POSTGRES_USER='+database,'-e','POSTGRES_HOST_AUTH_METHOD=trust','postgres:18'],text=True).strip()
    result=None
    try:
        row=json.loads(subprocess.check_output(['docker','inspect',container]))[0]
        port=row['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
        deadline=time.monotonic()+40
        while subprocess.run(['docker','exec',container,'pg_isready','-U',database,'-d',database],stdout=subprocess.DEVNULL).returncode:
            assert time.monotonic()<deadline;time.sleep(.2)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));http=sock.getsockname()[1]
        origin=f'https://127.0.0.1:{http}'
        env={k:os.environ[k] for k in ['PATH','TMPDIR','NAV_MEDIA_DIST'] if k in os.environ}
        env.update(HOME=str(out),PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1',NAV_MEDIA_EVIDENCE=str(out),NAV_HTTP_PORT=str(http),NAV_PG_CONTAINER=name,NAV_PG_NONCE=nonce,POSTGRES_HOST='127.0.0.1',POSTGRES_PORT=port,POSTGRES_DB=database,POSTGRES_USER=database,POSTGRES_PASSWORD='',STELLA_SECRET_KEY='owned-media-picker-synthetic-signing-key-only',STELLA_BLOB_STORAGE='postgres',STELLA_BLOB_CACHE=str(out/'blob-cache'),STELLA_MAIN_ORIGIN=origin,STELLA_TRUSTED_ORIGINS=origin,STELLA_BACKUP_DATA_ROOT=str(out/'data'),STELLA_BACKUP_DIRECTORY=str(out/'backups'),STELLA_BACKUP_RECEIPT_DIR=str(out/'receipts'),STELLA_OIDC_PRIVATE_KEY_FILE=str(out/'private-oidc-key.pem'),STELLA_NODE_FILE_STATE=str(out/'node-files'))
        (out/'target.json').write_text(json.dumps({'container':container,'name':name,'database':database,'pg_port':port,'origin':origin,'nonce':nonce,'root':str(ROOT),'dist':env['NAV_MEDIA_DIST']}))
        with (out/'server.log').open('w') as log:
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--child'],env=env,cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=200)
        print('full App runner exit',result.returncode,'evidence',str(out))
    finally:
        subprocess.run(['docker','rm','-f',container],check=True,stdout=subprocess.DEVNULL)
        absent=subprocess.run(['docker','inspect',container],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0
        (out/'cleanup.json').write_text(json.dumps({'container':container,'absent':absent}))
    raise SystemExit(result.returncode if result else 1)


if __name__=='__main__':
    child() if '--child' in sys.argv else parent()
