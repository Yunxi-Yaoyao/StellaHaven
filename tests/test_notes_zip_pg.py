import io
import zipfile
from uuid import uuid4

def test_zip_uses_pg_blob_and_idempotent_receipt(client,db_session,tmp_path,monkeypatch):
    from app.routers import attachment
    from app.models.blob import BlobObject
    monkeypatch.setenv('STELLA_BLOB_STORAGE','postgres')
    monkeypatch.setenv('STELLA_BLOB_CACHE',str(tmp_path/'cache'))
    legacy=tmp_path/'legacy';legacy.mkdir();monkeypatch.setattr(attachment,'STORAGE',legacy)
    ws=client.post('/workspaces/',json={'user_id':str(uuid4()),'name':'zip-pg'}).json()['id']
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        z.writestr('note.md','![image](image.png)');z.writestr('image.png',b'image-bytes')
    body={'workspace_id':ws,'import_id':str(uuid4())}
    r=client.post('/documents/import/zip',data=body,files={'file':('notes.zip',stream.getvalue(),'application/zip')})
    assert r.status_code==200,r.text
    atts=client.get('/attachments/',params={'workspace_id':ws}).json()
    assert len(atts)==1 and client.get(atts[0]['url']).content==b'image-bytes'
    assert not list(legacy.iterdir())
    assert db_session.get(BlobObject,'attachments/'+atts[0]['id']) is not None
    repeat=client.post('/documents/import/zip',data=body,files={'file':('notes.zip',stream.getvalue(),'application/zip')})
    assert repeat.status_code==200 and repeat.json()['reused']
