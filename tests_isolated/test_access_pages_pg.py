"""Real disposable PG pages selector/grant lifecycle; guarded Notes fixture only."""
import json
import pytest
from uuid import uuid4
from sqlalchemy.orm import Session
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes
from test_web_project_review_pg import project


@pytest.mark.parametrize('old_target',['https://pages.p.test','https://pages.test'])
def test_old_private_and_new_default_grants_keep_exact_resource_write_and_renewal_binding(notes,project,monkeypatch,old_target):
    from app.services import web_project_runtime as runtime,access_entries
    from app.models.config import AppConfig
    from fastapi import HTTPException
    import pytest
    p='https://stella.test';l='https://stella.p.test'
    monkeypatch.setenv('STELLA_ENTRY_REGISTRY',json.dumps([{'service_id':'stella','public':p,'private':l},{'service_id':'web-project-runtime','public':'https://pages.test','private':'https://pages.p.test'}]))
    monkeypatch.setenv('STELLA_TRUSTED_ORIGINS',p+','+l)
    root,_=project
    factory=lambda:Session(notes.engine)
    with access_entries.request_snapshot(factory),factory() as db:
        old=runtime.launch(db,notes.uid,root,notes.sid,l)
    assert old['target_origin']=='https://pages.p.test'
    with factory() as db:
        # Seed the still-valid historical public-from-private topology too.
        # This is fixture state, not a newly selected public destination.
        row=db.get(AppConfig,runtime.key(old['capability']))
        stored=json.loads(row.value);stored['target']=old_target;row.value=json.dumps(stored)
        old['target_origin']=old_target
        # Exact persisted settings shape; HTTP owner/CAS application is tested
        # separately against real PG. Never touch the preview business database.
        db.add(AppConfig(key=access_entries.KEY,value=json.dumps({'owner_id':str(notes.uid),'settings':{'revision':1,'enabled':False,'public_origin':p,'private_origin':l}})));db.commit()
    for existing in [True,False]:
        with access_entries.request_snapshot(factory),factory() as db:
            grant=old if existing else runtime.launch(db,notes.uid,root,notes.sid,l)
            target=old_target if existing else 'https://pages.p.test'
            assert grant['target_origin']==target
            assert runtime.resource(db,grant['capability'],target,'index.html')[1]=='text/html; charset=utf-8'
            other='https://pages.test' if target=='https://pages.p.test' else 'https://pages.p.test'
            with pytest.raises(HTTPException):runtime.resource(db,grant['capability'],other,'index.html')
            assert runtime.authorize(db,grant['capability'],source=l)[0]['source']==l
            with pytest.raises(HTTPException):runtime.authorize(db,grant['capability'],source=p)
            renewed=runtime.renew(db,notes.uid,root,notes.sid,l,grant['capability'],grant['state']['epoch'])
            assert renewed['capability']==grant['capability']
        response=notes.client.put(l+'/web-projects/'+str(root)+'/state',headers={'Origin':l,'Cookie':'stella_at='+notes.token},json={'revision':grant['state']['revision'],'epoch':grant['state']['epoch'],'write_id':str(uuid4()),'data':{'flow':'old' if existing else 'new'},'capability':grant['capability']})
        assert response.status_code==200,response.text
        assert response.json()['data']=={'flow':'old' if existing else 'new'}
