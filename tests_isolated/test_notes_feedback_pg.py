"""User feedback regressions on the launcher-owned PostgreSQL only."""
import importlib
from uuid import uuid4
from sqlalchemy.orm import Session
from test_notes_review_boundaries_pg import notes
from test_api_draft_contract import env


def workspace_routes(notes):
    notes.client.app.include_router(importlib.import_module('app.routers.workspace').router)
    return f'/workspaces/{notes.wid}'


def test_feedback_workspace_force_includes_protected_templates(notes):
    from app.services.notes_templates import initialize, PREFIX
    with Session(notes.engine) as db:
        root = initialize(db, notes.wid)
    path = workspace_routes(notes)
    # Ordinary note deletion remains protected, even for the owner.
    response = notes.client.delete(f'/documents/{root}/permanent?cascade=true')
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'protected_notes_folder'
    response = notes.client.delete(path)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'not_empty'
    with Session(notes.engine) as db:
        assert db.get(notes.models.Workspace, notes.wid)
        assert db.get(notes.models.Document, root)
    response = notes.client.delete(path + '?force=true')
    assert response.status_code == 204, response.text
    assert notes.client.get(path).status_code == 404
    with Session(notes.engine) as db:
        assert db.query(notes.models.Document).filter_by(workspace_id=notes.wid).count() == 0
        assert db.get(notes.models.AppConfig, PREFIX + str(notes.wid)) is None
        assert db.get(notes.models.AppConfig, 'notes-template-usage:' + str(notes.wid)) is None


def test_feedback_workspace_foreign_and_missing_are_zero_write(notes):
    path = workspace_routes(notes)
    foreign = uuid4()
    with Session(notes.engine) as db:
        db.add(notes.models.User(id=foreign, username='foreign', display_name='foreign')); db.flush()
        other = notes.models.Workspace(user_id=foreign, name='foreign'); db.add(other); db.commit(); wid = other.id
    assert notes.client.delete(f'/workspaces/{wid}?force=true').status_code == 404
    assert notes.client.delete(f'/workspaces/{uuid4()}?force=true').status_code == 404
    with Session(notes.engine) as db:
        assert db.get(notes.models.Workspace, wid)
        assert db.get(notes.models.Workspace, notes.wid)
        assert db.get(notes.models.Document, notes.did)


def test_feedback_workspace_attachment_conflict_restores_template_identity(notes):
    from app.services.notes_templates import initialize, PREFIX
    from app.models import Attachment
    with Session(notes.engine) as db:
        root = initialize(db, notes.wid)
        other = notes.models.Workspace(id=uuid4(), user_id=notes.uid, name='external')
        db.add(other); db.flush()
        attachment = Attachment(id=uuid4(), doc_id=notes.did, filename='synthetic', mime='text/plain', size=1)
        db.add(attachment); db.flush()
        external = notes.models.Document(id=uuid4(), workspace_id=other.id, title='reference', file_path='/external',
            content='/attachments/' + str(attachment.id), content_hash='fixture')
        db.add(external)
        db.add(notes.models.AppConfig(key='notes-template-usage:' + str(notes.wid), value='[]'))
        db.commit()
        aid, external_id = attachment.id, external.id
        count = db.query(notes.models.Document).count()
    path = workspace_routes(notes)
    response = notes.client.delete(path + '?force=true')
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] in ('attachment_in_use', 'attachment_reference_conflict')
    with Session(notes.engine) as db:
        assert db.get(notes.models.Workspace, notes.wid)
        assert db.query(notes.models.Document).count() == count
        assert db.get(notes.models.Document, external_id)
        assert db.get(Attachment, aid)
        assert db.get(notes.models.AppConfig, PREFIX + str(notes.wid)).value == str(root)
        assert db.get(notes.models.AppConfig, 'notes-template-usage:' + str(notes.wid)).value == '[]'
    # Protection is still effective after the rolled-back whole-workspace attempt.
    response = notes.client.delete(f'/documents/{root}/permanent?cascade=true')
    assert response.status_code == 409 and response.json()['detail']['code'] == 'protected_notes_folder'
    notes.client.cookies.clear()
    assert notes.client.delete(path + '?force=true').status_code == 401


def test_feedback_browser_real_http_pg(notes):
    """No page.route API mocks: Chromium -> private Vite proxy -> real FastAPI/PG."""
    import os
    import socket
    import subprocess
    import threading
    import time
    from pathlib import Path
    import uvicorn
    from app.services.notes_templates import initialize
    from app.routers.notes_preferences import router
    workspace_routes(notes)
    notes.client.app.include_router(router)
    with Session(notes.engine) as db:
        db.get(notes.models.Workspace, notes.wid).name = '反馈工作区'
        db.add(notes.models.Workspace(user_id=notes.uid, name='保留工作区'))
        db.commit()
        root = initialize(db, notes.wid)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(notes.client.app, log_level='warning', lifespan='off', access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started
        import json
        child_env = {k:v for k,v in os.environ.items() if not k.startswith(('HERMES_', 'MCP_', 'UV_', 'STELLA_', 'PG')) and k not in ('NODE_ENV','VIRTUAL_ENV','DATABASE_URL')}
        evidence = Path(os.environ.get('NOTES_FEEDBACK_EVIDENCE', '/opt/hermes-workstation/docs/records/2026-10-23-stella-production-feedback/notes'))
        evidence.mkdir(parents=True, exist_ok=True)
        child_env.update(NOTES_FEEDBACK_BACKEND=f'http://127.0.0.1:{port}',
            NOTES_FEEDBACK_SEED=json.dumps({'owner':str(notes.uid),'workspace':str(notes.wid),'root':str(root)}),
            NOTES_FEEDBACK_TOKEN=notes.token, NOTES_FEEDBACK_EVIDENCE=str(evidence),
            PLAYWRIGHT_BROWSERS_PATH='/root/.cache/ms-playwright')
        node = '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'
        result = subprocess.run([node, '--test', 'tests/notes-feedback-real-pg.browser.mjs'],
            cwd=Path(__file__).resolve().parents[1] / 'frontend', env=child_env, text=True, capture_output=True, timeout=150)
        (evidence / 'browser-real-pg.log').write_text(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        with Session(notes.engine) as db:
            assert db.get(notes.models.Workspace, notes.wid) is None
            assert db.query(notes.models.Document).filter_by(workspace_id=notes.wid).count() == 0
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()
