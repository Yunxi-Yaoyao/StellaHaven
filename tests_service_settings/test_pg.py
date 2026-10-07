"""Disposable PG: real locks, rollback, OIDC SELECT-only, legacy interop."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from tests_builtin.pg_fixture import pg_engine, pg_db
from tests_service_settings.test_api import payload
from app.models.config import AppConfig
from app.services import service_settings as service, builtin_injection as builtin, integrations as store
from app.services.integrations_injection import InjectionInput

ACTOR='00000000-0000-4000-8000-000000000001'


def test_concurrent_sites_preserve_nav_registry_connections_and_versions(pg_db,pg_engine):
    config=store.empty_state();config['targets']['quota']={'headers':{'Authorization':'SYNTHETIC-PRIVATE'}}
    pg_db.add(AppConfig(key=store.KEY,value=json.dumps(config)));pg_db.commit()
    barrier=Barrier(2)
    def write(site):
        with Session(pg_engine) as db:
            barrier.wait(5)
            return service.save(db,site,payload(site)|{'custom':{'enabled':True,'js':'window.'+site+'=1;'}},ACTOR)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(write,['drive','gallery']))
    with Session(pg_engine) as fresh:
        assert store.state(fresh)['targets']==config['targets']
        for result in results:
            assert service.read(fresh,result['site'])==result
            assert service.save(fresh,result['site'],payload(result['site'])|{'custom':{'enabled':True,'js':'window.'+result['site']+'=1;'}},ACTOR)==result
        assert [e['id'] for e in store.navigation(fresh)['entries']]==[b['id'] for b in store.BUILTINS]


def test_legacy_draft_rollback_interoperates_without_overwriting_other_site(pg_db):
    draft=InjectionInput(enabled=True,css='body{color:blue}')
    builtin.validate_draft(pg_db,'drive',draft);old=builtin.apply(pg_db,'drive',ACTOR)
    saved=service.save(pg_db,'drive',payload()|{'custom':{'enabled':True,'css':'body{color:red}'}},ACTOR)
    assert saved['injection']['previous']['version']==old['active']['version']
    builtin.validate_draft(pg_db,'drive',draft.model_copy(update={'css':'body{color:green}'}))
    restored=builtin.rollback(pg_db,'drive',ACTOR)
    projection=service.read(pg_db,'drive')['injection']
    assert projection['active']['version']==old['active']['version']
    assert projection['draft']['css']=='body{color:green}'
    assert projection['active']==restored['active']


def test_pg_fault_rolls_back_every_slot_including_new_version(pg_db,pg_engine,monkeypatch):
    service.save(pg_db,'drive',payload(),ACTOR)
    def snapshot():
        with Session(pg_engine) as db:return {r.key:r.value for r in db.query(AppConfig).all()}
    before=snapshot()
    original=service.record_change
    def fail(*args,**kw):original(*args,**kw);raise RuntimeError('synthetic fail after audit flush')
    monkeypatch.setattr(service,'record_change',fail)
    with pytest.raises(RuntimeError,match='synthetic fail'):
        service.save(pg_db,'drive',payload()|{'name':'never committed','custom':{'enabled':True,'js':'window.new=1;'}},ACTOR)
    assert snapshot()==before


def test_read_refreshes_retained_navigation_and_connection_rows(pg_db,pg_engine):
    service.save(pg_db,'drive',payload(),ACTOR)
    retained=[pg_db.get(AppConfig,k) for k in (store.KEY,'external_drive_connection')]
    data=payload()|{'name':'Fresh worker name'}
    data['connection']['service_url']='http://127.0.0.2:5244/fresh'
    with Session(pg_engine) as other:
        written=service.save(other,'drive',data,ACTOR)
    assert service.read(pg_db,'drive')==written
    assert retained


def test_oidc_pg_summary_has_no_lazy_shared_state_writes(pg_db,pg_engine,monkeypatch):
    from app.services import ha_state
    monkeypatch.setenv('STELLA_SHARED_STATE','postgres')
    ha_state.state_table.create(pg_engine,checkfirst=True)
    def no_legacy():raise AssertionError('legacy/shared-state mutator forbidden')
    monkeypatch.setattr(ha_state,'_engine',no_legacy)
    sql=[]
    def capture(conn,cursor,statement,*args):sql.append(statement)
    event.listen(pg_engine,'before_cursor_execute',capture)
    try:
        assert not service.read(pg_db,'gallery')['oidc']['client_registered']
        assert all(s.lstrip().upper().startswith('SELECT') for s in sql),sql
    finally:event.remove(pg_engine,'before_cursor_execute',capture)
    assert pg_db.execute(select(ha_state.state_table.c.key)).all()==[]
    pg_db.execute(ha_state.state_table.insert().values(key='oidc.clients',payload={'immich':{'client_secret':'SYNTHETIC-HIDDEN','redirect_uris':['app.immich:///oauth-callback']},'other':{'secret':'SYNTHETIC-OTHER'}}));pg_db.commit()
    output=service.read(pg_db,'gallery')
    assert output['oidc']['client_registered']
    assert output['oidc']['redirect_uris']==['app.immich:///oauth-callback']
    assert 'SYNTHETIC' not in json.dumps(output)
