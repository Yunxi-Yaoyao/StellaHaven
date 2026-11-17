"""F02 actual production-built Vue + TLS/HTTP + isolated PG, not production main/login."""
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from uuid import uuid4
from sqlalchemy.orm import Session
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes
ROOT = Path(__file__).resolve().parents[1]
NODE = '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'

def test_notes_timeline_contract_real(notes, monkeypatch, tmp_path):
    import uvicorn
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    import app.database as database
    from app.models import DocumentVersion
    monkeypatch.setattr(database, 'sessionLocal', lambda: Session(notes.engine), raising=False)
    evidence = Path(os.environ['NOTES_TIMELINE_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=True)
    app = notes.client.app
    for name in ('workspace', 'notes_preferences', 'notes_tools', 'web_projects', 'project_files', 'detached_sources', 'attachment', 'tag', 'doc_tag', 'document_link', 'document_version'):
        app.include_router(importlib.import_module('app.routers.' + name).router)
    version = uuid4()
    association_key = 'note-node:' + str(notes.did)
    association_value = json.dumps({'node_id': 12345})
    with Session(notes.engine) as db:
        doc = db.get(notes.models.Document, notes.did)
        doc.content = '# F02普通笔记\n\n真实历史保留正文'
        doc.draft_content = None
        doc.draft_updated_at = None
        db.add(notes.models.AppConfig(key=association_key, value=association_value))
        db.add(DocumentVersion(id=version, doc_id=notes.did, content='F02旧版本保留', diff='', version_no=1))
        db.commit()
    def retained():
        with Session(notes.engine) as db:
            v = db.get(DocumentVersion, version)
            return {'association': db.get(notes.models.AppConfig, association_key).value,
                    'version': {'id': str(v.id), 'content': v.content, 'version_no': v.version_no}}
    before = retained()
    dist = ROOT / 'frontend/dist'
    hashes = {str(p.relative_to(dist)): hashlib.sha256(p.read_bytes()).hexdigest() for p in dist.rglob('*') if p.is_file()}
    assert 'index.html' in hashes
    app.mount('/static', StaticFiles(directory=dist / 'static'), name='built-static')
    @app.get('/avatar.png', include_in_schema=False)
    def avatar():
        return FileResponse(dist / 'avatar.png')
    @app.get('/favicon.svg', include_in_schema=False)
    def favicon():
        return FileResponse(dist / 'favicon.svg')
    @app.get('/notes', include_in_schema=False)
    def built_app():
        return FileResponse(dist / 'index.html')
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    source = f'https://stella.test:{port}'
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY', json.dumps([{'service_id': 'stella', 'public': source}]))
    key, cert = tmp_path / 'key.pem', tmp_path / 'cert.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=stella.test', '-addext', 'subjectAltName=DNS:stella.test', '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
    pub = x509.load_pem_x509_certificate(cert.read_bytes()).public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning', lifespan='off', ssl_keyfile=str(key), ssl_certfile=str(cert), proxy_headers=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    spec = dict(source=source, port=port, token=notes.token, spki=base64.b64encode(hashlib.sha256(pub).digest()).decode(), evidence=str(evidence), doc=str(notes.did), workspace=str(notes.wid))
    (evidence/'boundary.json').write_text(json.dumps({'dist_sha256':hashes,'scope':'full built Vue; real routers/current_user; synthetic owner/session; get_db override; no production main/login/migrations'},indent=2))
    thread.start()
    try:
        deadline = time.monotonic() + 8
        while not server.started and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started
        result = subprocess.run([NODE, str(ROOT/'frontend/tests/notes-timeline-contract-pg.mjs')], env={**os.environ,'STELLA_TIMELINE_FIXTURE':json.dumps(spec)}, capture_output=True, text=True, timeout=100)
        (evidence/'browser.stdout.log').write_text(result.stdout)
        (evidence/'browser.stderr.log').write_text(result.stderr)
        print(result.stdout)
        after = retained()
        fresh = notes.client.get('/notes-tools/documents/'+str(notes.did)+'/node')
        assert fresh.status_code == 200 and fresh.json() == {'node_id':12345}
        (evidence/'pg-readback.json').write_text(json.dumps({'before':before,'after':after,'exact_equal':before==after,'fresh_http_association':fresh.json()},indent=2))
        assert before == after
        assert result.returncode == 0, result.stderr
        browser = json.loads((evidence/'results.json').read_text())
        assert browser['passed']
        assert hashes == {str(p.relative_to(dist)):hashlib.sha256(p.read_bytes()).hexdigest() for p in dist.rglob('*') if p.is_file()}
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        assert not thread.is_alive()
