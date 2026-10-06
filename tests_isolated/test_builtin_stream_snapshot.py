"""Actual host dispatch and slow HTML body; never use production DB or servers."""
import asyncio,json,socket,threading,time
from concurrent.futures import ThreadPoolExecutor
import pytest,uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from tests_isolated.test_integration_security_hotfix import integration_env
from app.models.config import AppConfig
from app.services import integrations as store,builtin_injection as builtin

@pytest.fixture
def upstream():
    app=FastAPI(); release=threading.Event();seen=[]
    @app.get('/')
    async def html():
        seen.append(('GET',''))
        async def body():
            yield b'<!doctype html><html><head></head><body>'
            await asyncio.to_thread(release.wait,10)
            yield b'slow fixture</body></html>'
        return StreamingResponse(body(),media_type='text/html')
    sock=socket.socket();sock.bind(('127.0.0.1',0));server=uvicorn.Server(uvicorn.Config(app,log_level='error'));thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+5
    while not server.started and time.monotonic()<deadline:time.sleep(.01)
    assert server.started
    try:yield f'http://127.0.0.1:{sock.getsockname()[1]}/',seen,release
    finally:release.set();server.should_exit=True;thread.join(5);sock.close();assert not thread.is_alive()

@pytest.fixture
def integration_env(monkeypatch,upstream):
    # Reuse actual auth/host fixture while preserving its two-field server contract.
    from tests_isolated.test_integration_security_hotfix import integration_env as fixture
    gen=fixture.__wrapped__(monkeypatch,upstream[:2])
    try:yield next(gen)
    finally:
        try:next(gen)
        except StopIteration:pass


def test_builtin_snapshot_releases_db_before_slow_html_body(integration_env,upstream,monkeypatch):
    c,factory,app,uid,sid,mid,origin,cookie,seen=integration_env
    with factory() as db:
        row=db.get(AppConfig,store.KEY);cfg=json.loads(row.value);cfg['modules'][mid]['adapter']='openlist';row.value=json.dumps(cfg)
        state=builtin.empty_state();state['drive']['active']=builtin.default_active('drive')|{'enabled':True,'css':'body{--snapshot-proof:1}','js':'','version':'snapshot-test-active'}
        db.add(AppConfig(key=builtin.KEY,value=json.dumps(state)));db.commit()
    read=threading.Event();captured=[];original=builtin.read
    def observe(db,site):
        result=original(db,site);captured.append(db);read.set();return result
    monkeypatch.setattr(builtin,'read',observe)
    pool=ThreadPoolExecutor(max_workers=1);future=pool.submit(c.get,origin+'/',headers={'Cookie':cookie})
    try:
        assert read.wait(5),'no published injection read'
        time.sleep(.1)
        assert not future.done(),'upstream body unexpectedly finished'
        assert captured[0] is not None
        assert not captured[0].in_transaction(),'injection DB held while slow upstream body is pending'
    finally:upstream[2].set()
    try:
        response=future.result(timeout=10);assert response.status_code==200,response.text;assert 'snapshot-test-active' in response.text and 'snapshot-proof' in response.text
    finally:pool.shutdown(wait=True)
