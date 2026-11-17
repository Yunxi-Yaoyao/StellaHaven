"""No proxy/stub responses: run actual Vue HTTP against the one owned PG fixture."""
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from test_client_preferences import site  # same owned schema, real registration and middleware


def test_real_vue_http_post_zip_and_restore_readback(site, engine, tmp_path, monkeypatch):
    import uvicorn
    from app.models.config import AppConfig
    from app.models.workspace import Workspace
    from app.models.document import Document
    from app.services import blob_store
    client, center = site
    owner = client.get('/auth/me').json()['id']
    with Session(engine) as db:
        workspace, document = uuid4(), uuid4()
        db.add(Workspace(id=workspace, user_id=UUID(owner), name='private-workspace'))
        db.flush()
        db.add(Document(id=document, workspace_id=workspace, title='private-note', file_path='/private.md', content='PG-PRIVATE-NOTE-BODY', content_hash='fixture'))
        db.add(AppConfig(key='web-project:'+str(document), value='PG-PRIVATE-WEB-SOURCE'))
        db.add(AppConfig(key='private-browser-token', value='PG-PRIVATE-BROWSER-TOKEN'))
        blob_store.put(db, 'attachments/private', io.BytesIO(b'PG-PRIVATE-ATTACHMENT'), 'application/octet-stream', 1000)
        db.commit()
    assert client.post('/auth/admin/setup', json={'user_password':'fixture-daily-password','new_password':'fixture-management-password'}).status_code == 410
    assert client.post('/auth/admin/unlock', json={'password':'fixture-management-password'}).status_code == 410
    # An explicit fixture directory, not a mutation disguised as a GET/default probe.
    directory = tmp_path/'owned-backups'
    directory.mkdir(mode=0o700)
    assert client.patch('/operations/backups/config', json={'expected_revision':0,'directory':str(directory)}).status_code == 200
    sock = socket.socket()
    sock.bind(('127.0.0.1',0))
    sock.listen(128)
    port = sock.getsockname()[1]
    # Node fetch owns Host, just as a browser does. Trust only this exact owned loopback origin.
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', f'http://testserver,http://127.0.0.1:{port}')
    seen_headers = []
    async def observed_app(scope, receive, send):
        if scope['type']=='http':
            seen_headers.append({key.decode():value.decode() for key,value in scope['headers'] if key in (b'host',b'origin')})
        await client.app(scope, receive, send)
    server = uvicorn.Server(uvicorn.Config(observed_app, log_level='warning', access_log=False, lifespan='off', loop='asyncio'))
    thread = threading.Thread(target=lambda:server.run(sockets=[sock]), daemon=True)
    thread.start()
    root = Path(os.environ['TMPDIR'])
    frontend = Path(__file__).resolve().parents[1]/'frontend'
    assert not (frontend/'.env').exists()
    node = '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'
    env = {'HOME':str(root/'home'), 'TMPDIR':str(root), 'PATH':str(Path(node).parent)+':/usr/bin:/bin',
           'STELLA_PREFS_TEST_BASE':f'http://127.0.0.1:{port}', 'STELLA_PREFS_TEST_OWNER':owner,
           'STELLA_PREFS_TEST_COOKIE':'; '.join(f'{key}={value}' for key,value in client.cookies.items()),
           'STELLA_PREFS_TEST_REPORT':str(root/'preferences-http-vue.json')}
    try:
        import httpx
        deadline = time.monotonic()+5
        while True:
            try:
                ready = httpx.get(env['STELLA_PREFS_TEST_BASE']+'/operations/backups/client-preferences',
                                  headers={'Host':'testserver','Cookie':env['STELLA_PREFS_TEST_COOKIE']},timeout=.5)
                if ready.status_code==200:
                    break
            except httpx.HTTPError:
                pass
            assert time.monotonic()<deadline, 'owned HTTP fixture readiness failed'
            time.sleep(.02)
        result = subprocess.run([node,'node_modules/vitest/vitest.mjs','run','--config','vitest.settings.config.mjs',
                                 'src/modules/settings/clientPreferencePg.http.test.ts','--reporter=verbose',
                                 '--reporter=junit','--outputFile.junit='+str(root/'preferences-http-vue-junit.xml')],
                                cwd=frontend,env=env,capture_output=True,text=True,timeout=60)
        log = (result.stdout+result.stderr).replace(env['STELLA_PREFS_TEST_COOKIE'],'<fixture-cookie-redacted>')
        (root/'preferences-http-vue.log').write_text(log)
        assert result.returncode==0, log+'\nObserved nonsecret origin headers: '+json.dumps(seen_headers)
        report = json.loads((root/'preferences-http-vue.json').read_text())
        assert report['private_zip_sentinels_absent'] and report['mounted_draft_preserved'] and report['no_restore_echo_put']
        assert report['restored_revision'] > report['changed_revision'] > report['saved_revision']
        with Session(engine) as db:
            assert db.get(Document,document).content == 'PG-PRIVATE-NOTE-BODY'
            assert b''.join(blob_store.read_range(db,'attachments/private',0,21)) == b'PG-PRIVATE-ATTACHMENT'
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()
        sock.close()
        center.wait()
