"""Real built Vue App + HTTP/TLS + owned PG + Chromium acceptance.

Not production main/login: reuse the guarded Notes fixture's synthetic owner and
session, with real current_user checks. No API substitutes or browser fulfill.
Run only via run_notes_boundary_pg.py --run-disposable-postgres ... -k full_vue_real.
"""
import base64
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import zipfile

from sqlalchemy.orm import Session
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes

ROOT = Path(__file__).resolve().parents[1]
NODE = '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'


def test_full_vue_real_web_project_journey(notes, monkeypatch, tmp_path):
    import uvicorn
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    import app.database as database
    monkeypatch.setattr(database, 'sessionLocal', lambda: Session(notes.engine), raising=False)
    from app.routers.web_project_host import WebProjectHostMiddleware
    from app.services import web_projects

    evidence = Path(os.environ['FULL_WEB_PROJECT_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(database, 'sessionLocal', lambda: Session(notes.engine), raising=False)
    app = notes.client.app
    for name in ('workspace', 'notes_preferences', 'notes_tools', 'web_projects', 'project_files', 'detached_sources', 'attachment', 'tag', 'doc_tag', 'document_link', 'document_version'):
        app.include_router(importlib.import_module('app.routers.' + name).router)
    dist = ROOT / 'frontend/dist'
    assert (dist / 'index.html').is_file(), 'Parent-built frontend dist required'
    app.mount('/static', StaticFiles(directory=dist / 'static'), name='built-static')
    @app.get('/avatar.png', include_in_schema=False)
    def built_avatar():
        return FileResponse(dist / 'avatar.png')
    @app.get('/favicon.svg', include_in_schema=False)
    def built_favicon():
        return FileResponse(dist / 'favicon.svg')
    @app.get('/notes', include_in_schema=False)
    def built_app():
        return FileResponse(dist / 'index.html')
    if os.environ.get('FINAL_EXPERIENCE') == '1':
        # Actual product routers and account-scoped PG preferences, no fulfill.
        from app.services.backup_center import BackupCenter
        from app.security import hash_refresh
        with Session(notes.engine) as db:
            db.get(notes.models.AuthSession, notes.sid).refresh_hash = hash_refresh('final-experience-test-refresh')
            db.commit()
        app.state.backup_center = BackupCenter(notes.engine, tmp_path / 'resources', key=b'final-experience-isolated-key-0000', default_directory=tmp_path / 'backups')
        for name in ('backups', 'config', 'integrations', 'auth_provider'):
            module = importlib.import_module('app.routers.' + name)
            app.include_router(module.router)
            if hasattr(module, 'public_router'):
                app.include_router(module.public_router)
        app.add_api_route('/settings', built_app, methods=['GET'], include_in_schema=False)
    # Unrelated shell API 404s stay visible rather than fake HTTP API responses.
    app = WebProjectHostMiddleware(app, lambda: Session(notes.engine))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    source, target = f'https://stella.test:{port}', f'https://pages.test:{port}'
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([
        {'service_id': 'stella', 'public': source},
        {'service_id': 'web-project-runtime', 'public': target}]))
    key, cert = tmp_path / 'key.pem', tmp_path / 'cert.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=stella.test', '-addext', 'subjectAltName=DNS:stella.test,DNS:pages.test', '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
    pub = x509.load_pem_x509_certificate(cert.read_bytes()).public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning', lifespan='off', ssl_keyfile=str(key), ssl_certfile=str(cert), proxy_headers=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    # Synthetic ORIGINAL input files, uploaded through the real Vue dialog.
    # Visible 240x120 PNG (stdlib only), not a misleading one-pixel placeholder.
    import struct
    import zlib
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    pixels = b''.join(b'\0' + b''.join(bytes((190, 150, 220) if (x//30+y//30)%2 else (95, 160, 190)) for x in range(240)) for y in range(120))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B',240,120,8,2,0,0,0)) + chunk(b'IDAT',zlib.compress(pixels)) + chunk(b'IEND',b'')
    quiz_js = '''import {label} from './label.js';
const score=document.querySelector('#score');
const render=()=>score.textContent=localStorage.getItem('answer')||'未作答';
render();document.querySelector('#answer').onclick=()=>{localStorage.setItem('answer','B');render();};
document.querySelector('#version').textContent=label;
'''
    html = '<!doctype html><html lang="zh"><head><meta charset="UTF-8"><link rel="stylesheet" href="assets/style.css"></head><body><h1>隔离答题原网页</h1><p>请选择正确答案</p><button id="answer">选择 B</button><p id="score"></p><p id="version"></p><img id="pixel" src="images/pixel.png" alt="保留图片"><script type="module" src="js/app.js"></script></body></html>'
    zip_path = tmp_path / 'quiz-original.zip'
    with zipfile.ZipFile(zip_path, 'w') as z:
        for name, body in {'index.html':'<h1>不要选的默认入口</h1>', 'quiz.html':html, 'js/app.js':quiz_js, 'js/label.js':"export const label='JS-v1';", 'assets/style.css':'body{font-family:sans-serif;padding:20px;background:#f4f0fa}button{padding:12px}#pixel{width:64px;height:64px}', 'images/pixel.png':png}.items():
            z.writestr(name, body)
    standalone = tmp_path / 'standalone.html'
    standalone.write_text('<!doctype html><html><head><meta charset="UTF-8"></head><body><h1 id="standalone">单文件原版 HTML</h1></body></html>')
    conversion = tmp_path / 'convert-images.zip'
    with zipfile.ZipFile(conversion, 'w') as z:
        z.writestr('article.html', '<html><head><meta charset="UTF-8"><title>图片转换验收</title></head><body><h1>图片转换验收</h1><p>普通笔记正文</p><img src="images/pixel.png" alt="原始图片"><script>window.conversionMustNotRun=true</script></body></html>')
        z.writestr('images/pixel.png', png)
    (evidence / 'inputs').mkdir(exist_ok=True)
    for input_file in (zip_path, standalone, conversion):
        (evidence / 'inputs' / input_file.name).write_bytes(input_file.read_bytes())
    spec = dict(source=source, target=target, port=port, token=notes.token,
                spki=base64.b64encode(hashlib.sha256(pub).digest()).decode(),
                evidence=str(evidence), zip=str(zip_path), standalone=str(standalone), conversion=str(conversion), workspace=str(notes.wid))
    hashes = {str(p.relative_to(dist)): hashlib.sha256(p.read_bytes()).hexdigest() for p in dist.rglob('*') if p.is_file()}
    (evidence / 'boundary.json').write_text(json.dumps({'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(), 'boundary':'unchanged full built Vue App; real routers/auth checks; synthetic seeded owner/session and get_db override; NOT production main/lifespan/migrations/login', 'dist_sha256':hashes, 'input_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (zip_path,standalone,conversion)}, 'source':source,'target':target}, indent=2))
    thread.start()
    try:
        deadline = time.monotonic() + 8
        while not server.started and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started
        result = subprocess.run([NODE, str(ROOT / 'frontend/tests/full-web-project-e2e.mjs')], env={**os.environ, 'NODE_ENV':'test', 'STELLA_PROJECT_FIXTURE':json.dumps(spec)}, capture_output=True, text=True, timeout=240)
        (evidence / 'browser.stdout.log').write_text(result.stdout)
        (evidence / 'browser.stderr.log').write_text(result.stderr)
        print(result.stdout)
        browser = json.loads((evidence / 'results.json').read_text())
        readbacks = {}
        for label, project in browser.get('projects', {}).items():
            with Session(notes.engine) as db:
                manifest = web_projects.manifest(db, notes.uid, project['id'])
                state = web_projects.read_state(db, notes.uid, project['id'])
                readbacks[label] = {'manifest':manifest, 'state':state, 'source_sha256':{f['path']:hashlib.sha256(web_projects.read_file(db,notes.uid,project['id'],f['path'])[0]).hexdigest() for f in manifest['files']}}
        if browser.get('conversion'):
            from uuid import UUID
            from app.models import Attachment, Document
            from app.services import blob_store
            with Session(notes.engine) as db:
                converted_id = UUID(browser['conversion']['documents'][0]['id'])
                doc = db.get(Document, converted_id)
                attachments = db.query(Attachment).join(Document, Attachment.doc_id == Document.id).filter(Document.workspace_id == notes.wid).all()
                original_name = browser['conversion']['conversion']['original_path']
                original = next(a for a in attachments if a.filename == original_name)
                original_bytes = b''.join(blob_store.read_range(db, 'attachments/'+str(original.id), 0, original.size))
                assert original_bytes == conversion.read_bytes()
                import re
                image_ids = re.findall(r'!\[原始图片\]\([^)]*?/attachments/([0-9a-f-]{36})', doc.content)
                assert len(image_ids) == 1
                image = db.get(Attachment, UUID(image_ids[0]))
                image_bytes = b''.join(blob_store.read_range(db, 'attachments/'+str(image.id), 0, image.size))
                assert image_bytes == png
                readbacks['conversion'] = {'doc_id':str(doc.id), 'content':doc.content, 'image_id':str(image.id), 'image_sha256':hashlib.sha256(image_bytes).hexdigest(), 'original_archive_sha256':hashlib.sha256(original_bytes).hexdigest(), 'source_archive_exact':True, 'image_exact':True}
        if browser.get('dragCopy', {}).get('document_id'):
            from uuid import UUID
            from app.models import Attachment, Document
            from app.services import blob_store
            import re
            with Session(notes.engine) as db:
                dragged = browser['dragCopy']
                target_doc = db.get(Document, UUID(dragged['document_id']))
                copied_id = re.search(r'/attachments/([0-9a-f-]{36})', dragged['response']['url']).group(1)
                attachment = db.get(Attachment, UUID(copied_id))
                copied_bytes = b''.join(blob_store.read_range(db, 'attachments/'+copied_id, 0, attachment.size))
                source_bytes = web_projects.read_file(db, notes.uid, browser['projects']['zip']['id'], 'images/pixel.png')[0]
                assert copied_bytes == source_bytes == png
                assert attachment.doc_id == target_doc.id
                assert copied_id in target_doc.content
                readbacks['drag_copy'] = {'attachment_id':copied_id, 'doc_id':str(target_doc.id), 'source_file_id':dragged['source_file_id'], 'exact_png_sha256':hashlib.sha256(copied_bytes).hexdigest(), 'independent_attachment_owner':True, 'source_exact':True}
        if os.environ.get('FINAL_EXPERIENCE') == '1':
            from app.services.backup_preferences import read_preferences
            from app.services.notes_preferences import get_preferences
            readbacks['account_preferences'] = read_preferences(notes.engine, notes.uid)
            with Session(notes.engine) as db:
                readbacks['notes_preferences'] = get_preferences(db, notes.uid)
                readbacks['backup_state_not_written'] = db.get(notes.models.AppConfig, 'backup_center_v1') is None
        (evidence / 'pg-readback.json').write_text(json.dumps(readbacks, indent=2, default=str))
        assert result.returncode == 0, result.stderr
        assert browser['passed']
        if os.environ.get('PROJECT_RENAME_ONLY') == '1':
            rename = browser['rename']
            with Session(notes.engine) as db:
                ident = browser['projects']['zip']['id']
                info = web_projects.manifest(db, notes.uid, ident)
                assert info == rename['finalManifest']
                assert info['entry'] == 'renamed.html'
                assert web_projects.read_file(db, notes.uid, ident, 'renamed.html')[0] == html.encode()
                assert web_projects.read_file(db, notes.uid, ident, 'js/app.js')[0] == quiz_js.encode()
                assert web_projects.read_file(db, notes.uid, ident, 'images/pixel.png')[0] == png
                assert web_projects.read_file(db, notes.uid, ident, 'js/label.js')[0] == b"export const label='JS-v1';\n// rename CAS continuity"
                assert web_projects.read_state(db, notes.uid, ident) == rename['state']
                assert rename['state']['data'] == {'answer': 'B'}
            assert readbacks['account_preferences']['appearance'] == 'B'
            readbacks['rename_verified'] = {'exact_html': True, 'exact_js_caller': True, 'exact_binary_blob': True, 'source_revision_continuity': True, 'state_B': True, 'manifest_matches_UI_API': True}
            (evidence / 'pg-readback.json').write_text(json.dumps(readbacks, indent=2, default=str))
        else:
            assert readbacks['zip']['state']['data'] == {}
            assert '普通笔记编辑验收' in readbacks['conversion']['content']
        assert hashes == {str(p.relative_to(dist)): hashlib.sha256(p.read_bytes()).hexdigest() for p in dist.rglob('*') if p.is_file()}
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        assert not thread.is_alive()
