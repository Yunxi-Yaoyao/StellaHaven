"""Independent boundary expectations. Failures remain visible in report."""
import asyncio
import pytest
from test_website_settings import upstream,api_env,checker,run_check

def test_cancel_releases_probe_and_closes_loopback_response(upstream,monkeypatch):
    import time
    root,responses,seen=upstream
    responses['/cancel']=(200,[('Content-Type','text/html')],lambda:(time.sleep(.3),b'<html/>')[1])
    closed=[]
    real=checker().proxy.open_response
    async def opened(*args,**kwargs):
        client,response=await real(*args,**kwargs)
        close=response.aclose
        async def closing():closed.append(True);await close()
        response.aclose=closing
        return client,response
    monkeypatch.setattr(checker().proxy,'open_response',opened)
    async def exercise():
        task=asyncio.create_task(checker().check_draft(checker().CheckInput(address=root+'/cancel'),parent_origin='http://stella.test'))
        for _ in range(100):
            if seen:break
            await asyncio.sleep(.01)
        await asyncio.sleep(.02);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert (await checker().check_draft(checker().CheckInput(address=root+'/after'),parent_origin='http://stella.test'))['can_save']
    asyncio.run(exercise())
    assert closed
    acquired=[]
    for _ in range(4):acquired.append(checker().PROBE_SLOTS.acquire(blocking=False))
    try:assert all(acquired)
    finally:
        for success in acquired:
            if success:checker().PROBE_SLOTS.release()

def test_full_form_edit_of_legacy_icon_remains_saveable(upstream,api_env):
    root,_,_=upstream;c,_,_,_=api_env
    old=c.post('/external-modules',json={'name':'Legacy icon','icon':'heart','browser_url':root,'mode':'iframe'}).json()
    result=c.patch('/website-settings/'+old['id'],json={'address':root,'name':'Rename only','icon':old['icon'],'visible':True,'keep_alive':False,'open_behavior':'embedded','custom':{'enabled':False,'css':'','js':'','timing':'dom_ready'}})
    assert result.status_code==200,result.text

def test_server_css_syntax_validation_rejects_missing_colon(upstream,api_env):
    root,_,_=upstream;c,_,_,_=api_env
    result=c.post('/website-settings',json={'address':root,'idempotency_key':'review-css-invalid','custom':{'enabled':True,'css':'body { color red; }'}})
    assert result.status_code==422,result.text

def test_rollback_api_has_distinct_current_draft_and_rolled_back_active(upstream,api_env):
    root,_,_=upstream;c,_,_,_=api_env
    first=c.post('/website-settings',json={'address':root,'idempotency_key':'review-first-version','custom':{'enabled':True,'css':'body{color:red}'}}).json()
    second=c.patch('/website-settings/'+first['id'],json={'address':root,'custom':{'enabled':True,'css':'body{color:blue}'}}).json()
    rolled=c.post('/external-modules/'+first['id']+'/injection/rollback').json()
    assert rolled['active']['css']=='body{color:red}'
    assert rolled['draft']['css']=='body{color:blue}'
    assert rolled['active']['version']==first['injection']['active']['version']

def test_csp_http_default_port_secure_upgrade_is_allowed():
    import httpx
    result=checker().evaluate_embedding(httpx.Headers({'content-security-policy':'frame-ancestors http://stella.test:80'}),'https://document.test/','https://stella.test')
    assert result['status']=='allowed',result
