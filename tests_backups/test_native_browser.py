"""True native stream crosses 30s without buffering in frontend JS."""
import asyncio
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time


def test_actual_native_browser_download_over_30s_with_real_management_auth(engine, tmp_path, monkeypatch):
    from fastapi import FastAPI
    import uvicorn
    from app.routers.auth import router as auth_router
    from app.routers.backups import router
    from app.services.backup_center import BackupCenter
    from app.services.request_security import MainSiteSecurityMiddleware
    front_socket = socket.socket()
    front_socket.bind(('127.0.0.1', 0))
    frontend_port = front_socket.getsockname()[1]
    front_socket.close()
    origin = f'http://127.0.0.1:{frontend_port}'
    monkeypatch.setenv('STELLA_MAIN_ORIGIN', origin)
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS', origin)
    center = BackupCenter(engine, tmp_path / 'data', key=b'native-download-fixture')
    store = center.store()
    store.path.mkdir(parents=True, mode=0o700)
    # This is transport input, not fabricated all-database recovery evidence.
    payload = tmp_path / 'synthetic-32MiB-resource'
    with payload.open('wb') as f:
        for _ in range(128):
            f.write(os.urandom(256 * 1024))
    with payload.open('rb') as f:
        record = store.create('all', {'database.dump': io.BytesIO(b'PGDMP-transport-fixture-not-a-real-database'),
                                     'files/assets/synthetic.bin': f}, warnings=['synthetic native transport fixture only'])
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(router)
    app.state.backup_center = center
    app.add_middleware(MainSiteSecurityMiddleware)
    server_requests = []
    class SlowNativeBody:
        async def __call__(self, scope, receive, send):
            if scope.get('path', '').endswith('/download'):
                server_requests.append({'method':scope.get('method'), 'path':scope['path']})
            if scope.get('method') != 'GET' or not scope.get('path', '').endswith('/download'):
                return await app(scope, receive, send)
            started = time.monotonic()
            sent = 0
            async def slow(message):
                nonlocal sent
                if message['type'] == 'http.response.body' and message.get('body'):
                    sent += len(message['body'])
                    delay = sent / (1024 * 1024) - (time.monotonic() - started)
                    if delay > 0:
                        await asyncio.sleep(delay)
                await send(message)
            return await app(scope, receive, slow)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    backend = f'http://127.0.0.1:{sock.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(SlowNativeBody(), log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(.02)
    assert server.started
    root = Path(__file__).resolve().parents[1]
    report_dir = root.parent / 'docs/Stella-界面改版执行-20261017/backup-native-download'
    report_dir.mkdir(exist_ok=True)
    cfg = tmp_path / 'browser-config.json'
    cfg.write_text(json.dumps({'frontend_port':frontend_port, 'backend':backend, 'id':record['id'],
                              'bytes':record['bytes'], 'sha256':record['sha256'],
                              'destination':str(tmp_path / 'browser-saved.zip'),
                              'report':str(report_dir / 'actual-native-stream.json'),
                              'chrome':'/opt/google/chrome/chrome'}))
    env = dict(os.environ)
    node = '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node'
    env['PATH'] = str(Path(node).parent) + ':' + env['PATH']
    try:
        p = subprocess.run([node, str(root / 'tests_backups/native_download.browser.mjs'), str(cfg)],
                           capture_output=True, text=True, env=env, timeout=110)
        (report_dir / 'actual-native-browser.log').write_text(p.stdout + p.stderr)
        assert p.returncode == 0, p.stdout + p.stderr
        evidence = json.loads((report_dir / 'actual-native-stream.json').read_text())
        evidence['actual_asgi_requests'] = server_requests
        (report_dir / 'actual-native-stream.json').write_text(json.dumps(evidence, indent=2))
        assert [r['method'] for r in server_requests] == ['HEAD', 'GET']
        assert evidence['elapsed_ms'] > 30000 and evidence['bytes'] == record['bytes']
        assert evidence['sha256'] == record['sha256'] and not evidence['blob_buffered']
    finally:
        server.should_exit = True
        thread.join(5)
        center.stop()
        assert not thread.is_alive()
