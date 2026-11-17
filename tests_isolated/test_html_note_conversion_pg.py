"""Actual PostgreSQL transaction + HTTP conversion and attachment readback."""
import io,zipfile,base64
from uuid import uuid4
from sqlalchemy.orm import Session
from test_api_draft_contract import env
from test_notes_review_boundaries_pg import notes

def test_html_conversion_http_preview_commit_retry_and_source_preserved(notes):
 from app.services import blob_store
 from app.models.attachment import Attachment
 image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
 raw=io.BytesIO()
 with zipfile.ZipFile(raw,'w') as z:
  z.writestr('book/page.html','<h1>阅读</h1><img src="../images/a.png"><script>window.test=1</script>')
  z.writestr('images/a.png',image)
 data=raw.getvalue();files={'file':('book.zip',data,'application/zip')};target={'workspace_id':str(notes.wid),'encoding':'auto'}
 preview=notes.client.post('/documents/import/html/preview',files=files,data=target)
 assert preview.status_code==200,preview.text
 assert preview.json()['converted_count']==1 and 'script' in preview.json()['documents'][0]['losses']
 ident=str(uuid4());payload={**target,'import_id':ident}
 first=notes.client.post('/documents/import/html',files=files,data=payload);assert first.status_code==200,first.text
 retry=notes.client.post('/documents/import/html',files=files,data=payload);assert retry.status_code==200 and retry.json()['reused']
 assert [d['id'] for d in first.json()['documents']]==[d['id'] for d in retry.json()['documents']]
 with Session(notes.engine) as db:
  doc=db.query(notes.models.Document).filter(notes.models.Document.title=='page').one()
  assert '# 阅读' in doc.content and '/attachments/' in doc.content and 'window.test' not in doc.content
  attachments=db.query(Attachment).all()
  copies=[a for a in attachments if a.filename=='images/a.png'];assert len(copies)==1
  assert b''.join(blob_store.read_range(db,'attachments/'+str(copies[0].id),0,copies[0].size))==image
  original=next(a for a in attachments if a.filename.startswith('stella-original-'))
  assert b''.join(blob_store.read_range(db,'attachments/'+str(original.id),0,original.size))==data
