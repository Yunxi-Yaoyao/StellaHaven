"""Integration tests use only a private SQLite schema; PG exercises separately."""
import io
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

@pytest.fixture
def db():
    from app.models.blob import BlobObject, BlobChunk
    e=create_engine('sqlite://',connect_args={'autocommit':False})
    BlobObject.__table__.create(e);BlobChunk.__table__.create(e)
    with Session(e) as s:yield s
    e.dispose()

def test_store_chunks_size_hash_and_rollback(db):
    from app.services.blob_store import put, metadata, read_range, CHUNK_SIZE
    payload=b'abcd'*(CHUNK_SIZE//2)
    info=put(db,'attachments/one',io.BytesIO(payload),'application/octet-stream',len(payload))
    assert info['size']==len(payload)
    assert b''.join(read_range(db,'attachments/one',0,len(payload)))==payload
    assert b''.join(read_range(db,'attachments/one',CHUNK_SIZE-2,6))==payload[CHUNK_SIZE-2:CHUNK_SIZE+4]
    db.rollback()
    assert metadata(db,'attachments/one') is None

def test_overlimit_and_delete(db):
    from app.services.blob_store import put, delete, metadata, BlobTooLarge
    with pytest.raises(BlobTooLarge):put(db,'attachments/too',io.BytesIO(b'12345'),'text/plain',4)
    db.rollback()
    assert metadata(db,'attachments/too') is None
    put(db,'attachments/ok',io.BytesIO(b'12'),'text/plain',4)
    db.commit();delete(db,'attachments/ok');db.commit()
    assert metadata(db,'attachments/ok') is None

def test_object_overwrite_stays_in_callers_transaction(db):
    from app.services.blob_store import put, metadata, read_range
    put(db,'config/x',io.BytesIO(b'old'),'text/plain',8);db.commit()
    put(db,'config/x',io.BytesIO(b'new'),'text/plain',8)
    db.rollback()
    assert b''.join(read_range(db,'config/x',0,3))==b'old'

def test_range_headers_contract():
    from app.services.blob_store import parse_range
    assert parse_range('bytes=2-4',10)==(2,5)
    assert parse_range('bytes=-3',10)==(7,10)
    assert parse_range('bytes=7-',10)==(7,10)
    for text in ['bytes=10-','bytes=4-1','bytes=0-1,4-5','bytes=-0']:
        with pytest.raises(ValueError):parse_range(text,10)
