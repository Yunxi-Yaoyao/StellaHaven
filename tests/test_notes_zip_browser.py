"""Opt-in real Chromium + HTTP API + isolated PostgreSQL acceptance.
Run after frontend build: STELLA_LIVE_BROWSER=1 uv run pytest tests/test_notes_zip_browser.py -q -s
No production data or real account is used. Browser dependencies belong to frontend.
"""
import os
import socket
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('STELLA_LIVE_BROWSER') != '1', reason='opt-in local Chromium acceptance')


def test_real_browser_zip_template_roundtrip(db_session, monkeypatch, tmp_path):
    from sqlalchemy.orm import sessionmaker
    from tests.conftest import OWNER_USERNAME, OWNER_PASSWORD
    engine = db_session.get_bind()
    TestingSessionLocal = sessionmaker(bind=engine)
    from app.database import get_db
    from app.models.user import User
    from app.models.workspace import Workspace
    from app.models.document import Document
    from app.security import hash_password
    from app.routers import attachment
    from main import app
    import uvicorn
    assert (engine.url.database or '').startswith('stella_test'), 'Never run browser fixture against live DB'
    password = OWNER_PASSWORD
    storage = tmp_path / 'attachments'
    storage.mkdir()
    monkeypatch.setattr(attachment, 'STORAGE', storage)
    with TestingSessionLocal() as db:
        user = db.query(User).filter_by(username=OWNER_USERNAME).one()
        ws = Workspace(id=uuid4(), user_id=user.id, name='导入联调工作区')
        db.add(ws)
        db.flush()
        old = Document(id=uuid4(), workspace_id=ws.id, title='保留原文', content='原文不覆盖', content_hash='', file_path='/existing.md')
        db.add(old)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        ws_id = str(ws.id)
    def isolated_db():
        with TestingSessionLocal() as session:
            yield session
    overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = isolated_db
    archive = tmp_path / 'notes.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('知识库/README.md', '# 目录说明\n\n[精确文章](子目录/同名.md#验证)\n\n![样图](media/图.png)')
        z.writestr('知识库/子目录/同名.md', '# 验证\n\n正确的同名文章\n\n[目录](../README.md)')
        z.writestr('知识库/另一目录/同名.md', '# 另一篇\n\n不能串到这里')
        z.writestr('知识库/说明.txt', '# 保持普通文本')
        import base64
        z.writestr('知识库/media/图.png', base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aP1cAAAAASUVORK5CYII='))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', 'http://testserver,'+origin)
    from app.routers.integrations_host import IntegrationsHostMiddleware
    for middleware in app.user_middleware:
        if middleware.cls is IntegrationsHostMiddleware:
            monkeypatch.setitem(middleware.kwargs, 'main_origin', origin)
    monkeypatch.setattr(app, 'middleware_stack', None)
    # The cloned browser script writes screenshots only to this test's scratch.
    frontend = Path(__file__).resolve().parents[1] / 'frontend'
    script = tmp_path / 'notes-live.mjs'
    (tmp_path / 'node_modules').symlink_to((frontend / 'node_modules').resolve(), target_is_directory=True)
    source = (frontend / 'tests/notes-zip-live.mjs').read_text().replace('/tmp/stella-notes-live-', str(tmp_path / 'stella-notes-live-'))
    source = source.replace("const dialog=page.getByRole('dialog');await dialog.getByRole('button',{name:'预览 ZIP',exact:true}).click();", "const dialog=page.getByRole('dialog');const previewResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/documents/import/zip/preview');await dialog.getByRole('button',{name:'预览 ZIP',exact:true}).click();const previewResult=await previewResponse;assert.equal(previewResult.status(),200,await previewResult.text());")
    chromium = os.getenv('STELLA_TEST_CHROMIUM')
    if chromium:
        assert Path(chromium).is_file()
        source = source.replace("executablePath:'/usr/sbin/google-chrome-stable'", 'executablePath:'+__import__('json').dumps(chromium))
    script.write_text(source)
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started
        env = {**os.environ, 'STELLA_LIVE_URL': f'http://127.0.0.1:{port}', 'STELLA_LIVE_ZIP': str(archive), 'STELLA_LIVE_WS': ws_id, 'STELLA_LIVE_USER': user.username, 'STELLA_LIVE_PASSWORD': password}
        result = subprocess.run(['node', str(script)], cwd=Path(__file__).resolve().parents[1] / 'frontend', env=env, capture_output=True, text=True, timeout=90)
        print(result.stdout)
        assert result.returncode == 0, result.stderr + result.stdout
        with TestingSessionLocal() as db:
            assert db.query(Document).filter_by(workspace_id=ws.id, title='保留原文').one().content == '原文不覆盖'
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(overrides)
