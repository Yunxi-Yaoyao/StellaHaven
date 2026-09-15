import io
from uuid import uuid4
import pytest
from sqlalchemy import select

@pytest.fixture
def pg_doc(client,monkeypatch,tmp_path):
    monkeypatch.setenv('STELLA_BLOB_STORAGE','postgres')
    monkeypatch.setenv('STELLA_BLOB_CACHE',str(tmp_path/'cache'))
    from app.routers import attachment
    monkeypatch.setattr(attachment,'STORAGE',tmp_path/'legacy');attachment.STORAGE.mkdir()
    u=client.post('/users/',json={'username':'pgblob_'+uuid4().hex[:12],'display_name':'test'}).json()
    w=client.post('/workspaces/',json={'user_id':u['id'],'name':'pgblobs'}).json()
    d=client.post('/documents/',json={'title':'blob','file_path':'/blob.md','workspace_id':w['id'],'content':''}).json()
    return d['id'],attachment.STORAGE

def test_pg_attachment_no_file_and_delete(client,pg_doc,db_session):
    from app.models.blob import BlobObject
    doc,path=pg_doc
    payload=b'test-content'*50000
    r=client.post('/attachments/'+doc,files={'file':('test.bin',io.BytesIO(payload),'application/octet-stream')})
    assert r.status_code==200
    ident=r.json()['id'];url=r.json()['url']
    assert not (path/ident).exists()
    assert db_session.execute(select(BlobObject.size).where(BlobObject.key=='attachments/'+ident)).scalar_one()==len(payload)
    assert client.get(url).content==payload
    rr=client.get(url,headers={'Range':'bytes=262140-262150'})
    assert rr.status_code==206 and rr.content==payload[262140:262151]
    docdata=client.get('/documents/'+doc).json()
    r=client.put('/documents/'+doc,json={'updated_at':docdata['updated_at'],'content':'no attachment'})
    assert r.status_code==200
    assert client.get(url).status_code==404
    assert db_session.get(BlobObject,'attachments/'+ident) is None


def test_pg_upload_idempotency_same_content_and_conflict(client,pg_doc):
    doc,_=pg_doc
    headers={'Idempotency-Key':'synthetic-request-id'}
    first=client.post('/attachments/'+doc,headers=headers,files={'file':('a.bin',b'abc','application/octet-stream')})
    again=client.post('/attachments/'+doc,headers=headers,files={'file':('a.bin',b'abc','application/octet-stream')})
    assert first.status_code==again.status_code==200
    assert first.json()['id']==again.json()['id']
    conflict=client.post('/attachments/'+doc,headers=headers,files={'file':('a.bin',b'different','application/octet-stream')})
    assert conflict.status_code==409
