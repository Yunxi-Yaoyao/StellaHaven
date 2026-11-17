"""Bounded save contract; full original negative controls run separately."""
import copy
import json
import pytest
from tests_website_settings.test_website_settings import api_env, upstream


def test_read_revision_blocks_cross_window_stale_edit(api_env, upstream):
    c, factory, _, _ = api_env
    root, _, seen = upstream
    created=c.post('/website-settings',json=dict(address=root+'/cas',idempotency_key='cas-create-0001')).json()
    mid=created['id']
    detail=c.get('/external-modules/'+mid)
    assert detail.headers.get('etag') == '"'+str(created['navigation']['revision'])+'"'
    revision=int(detail.headers['etag'].strip('"'))
    first=dict(address=root+'/cas',name='Window B',expected_revision=revision,idempotency_key='cas-edit-window-b')
    saved=c.patch('/website-settings/'+mid,json=first)
    assert saved.status_code==200,saved.text
    assert c.patch('/website-settings/'+mid,json=first).json()==saved.json()
    seen.clear()
    denied=c.patch('/website-settings/'+mid,json=first|dict(name='Stale A',idempotency_key='cas-edit-window-a'))
    assert denied.status_code==409,denied.text
    assert seen==[]
    assert c.get('/external-modules/'+mid).json()['name']=='Window B'


def test_summary_runtime_hash_ignores_drafts_and_background(api_env, upstream):
    from app.services import integrations as store
    c,f,_,_=api_env;root,_,_=upstream
    mid=c.post('/website-settings',json=dict(address=root,idempotency_key='summary-hash-create')).json()['id']
    def summary(): return next(m for m in c.get('/navigation').json()['modules'] if m['id']==mid)
    initial=summary();assert len(initial['runtime_revision'])==64
    with f() as db:
        with store.edit(db) as config:
            config['modules'][mid]['injection']['draft']={'css':'SYNTHETIC-PRIVATE-CODE'}
            config['modules'][mid]['background']='home'
    changed=summary()
    assert changed['runtime_revision']==initial['runtime_revision']
    assert changed['background']=='home'
    assert 'SYNTHETIC-PRIVATE-CODE' not in json.dumps(changed)
    with f() as db:
        with store.edit(db) as config:
            config['modules'][mid]['injection']['active']={'enabled':False,'css':'SYNTHETIC-PRIVATE-CODE'}
    assert summary()['runtime_revision']!=initial['runtime_revision']
    with f() as db:
        with store.edit(db) as config: config['modules'][mid].pop('background')
    assert 'background' not in summary()


def test_local_code_rechecks_entry_revision_before_commit(api_env,upstream,monkeypatch):
    from app.services import access_entries
    c,_,_,_=api_env;root,_,_=upstream
    created=c.post('/website-settings',json=dict(address=root+'/entry-revision',idempotency_key='entry-revision-create')).json()
    monkeypatch.setattr(access_entries,'current',lambda:dict(revision=1))
    monkeypatch.setattr(access_entries,'read',lambda db:dict(revision=2))
    result=c.patch('/website-settings/'+created['id'],json=dict(address=root+'/entry-revision',custom=dict(enabled=False,css='body{}')))
    assert result.status_code==409,result.text
    assert c.get('/external-modules/'+created['id']).json()['injection']['active'] is None


@pytest.mark.parametrize('transport',['proxy','direct'])
def test_code_only_retains_authority_without_probe(api_env, upstream,monkeypatch,transport):
    from app.services import website_settings as service
    c,_,_,_=api_env;root,_,seen=upstream
    body=dict(address=root+'/code',idempotency_key='code-local-create-'+transport,
        connection=dict(transport=transport,injection_delivery='proxy' if transport=='proxy' else 'loader'),custom=dict(enabled=True,css='body{color:blue}'))
    created=c.post('/website-settings',json=body);assert created.status_code==201,created.text
    async def forbidden(*a,**k): raise AssertionError('Unchanged code save must not fetch upstream')
    monkeypatch.setattr(service,'check_draft',forbidden)
    seen.clear()
    saved=c.patch('/website-settings/'+created.json()['id'],json=dict(address=root+'/code',custom=dict(enabled=True,css='body{color:red}',js='document.title="safe";'),idempotency_key='code-local-edit-'+transport))
    assert saved.status_code==200,saved.text
    assert saved.json()['check']['access']['status']=='unknown'
    assert saved.json()['check']['embedding']['reason_code']=='code_only'
    assert saved.json()['injection']['active']['css']=='body{color:red}'
    assert not seen
    rejected=c.patch('/website-settings/'+created.json()['id'],json=dict(address=root+'/code',custom=dict(enabled=True,css='body{',js='function(')))
    assert rejected.status_code==422,rejected.text
