import io
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

def test_cached_response_range_and_head_without_nfs(tmp_path,monkeypatch):
    from app.models.blob import BlobObject,BlobChunk
    from app.services.blob_store import put, response
    monkeypatch.setenv('STELLA_BLOB_CACHE',str(tmp_path/'cache'))
    e=create_engine('sqlite://',connect_args={'check_same_thread':False,'autocommit':False},poolclass=StaticPool)
    BlobObject.__table__.create(e);BlobChunk.__table__.create(e)
    payload=b'abcd'*200000
    with Session(e) as db:put(db,'x',io.BytesIO(payload),'application/octet-stream',len(payload));db.commit()
    app=FastAPI()
    @app.api_route('/file',methods=['GET','HEAD'])
    def getfile(req:Request):
        with Session(e) as db:return response(db,'x',req,filename='test.bin')
    with TestClient(app) as c:
        r=c.get('/file',headers={'Range':'bytes=262140-262148'})
        assert r.status_code==206 and r.content==payload[262140:262149]
        assert c.head('/file').headers['content-length']==str(len(payload))
        r=c.get('/file');assert r.content==payload
        assert c.get('/file',headers={'If-None-Match':r.headers['etag']}).status_code==304
        assert c.get('/file',headers={'Range':'bytes=999999999-'}).status_code==416
    assert len(list((tmp_path/'cache').glob('*.bin')))==1
