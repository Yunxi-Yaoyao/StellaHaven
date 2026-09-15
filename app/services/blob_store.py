"""Transactional objects with bounded adaptation memory (256 KiB chunks).
No commits here: caller must commit metadata and bytes atomically.
"""
import hashlib
import os
import re
from sqlalchemy import select, delete as sql_delete, insert, update
from app.models.blob import BlobObject, BlobChunk

CHUNK_SIZE=256*1024
class BlobTooLarge(ValueError):pass

def enabled():return os.getenv('STELLA_BLOB_STORAGE','file')=='postgres'

def validate_key(key):
    if not key or len(key)>512 or key.startswith('/') or '..' in key.split('/') or '\\' in key:
        raise ValueError('Invalid object key')

def delete(db,key):
    validate_key(key)
    db.execute(sql_delete(BlobChunk).where(BlobChunk.key==key))
    return db.execute(sql_delete(BlobObject).where(BlobObject.key==key)).rowcount

def put(db,key,source,mime,max_bytes):
    validate_key(key)
    if max_bytes<0:raise ValueError('Invalid size limit')
    # A savepoint prevents a caught size/error exception leaving a half object
    # in the outer transaction. It never commits caller business metadata.
    with db.begin_nested():
        delete(db,key)
        db.execute(insert(BlobObject).values(key=key,size=0,sha256='',mime=mime[:200]))
        total=0;number=0;digest=hashlib.sha256();pending=bytearray()
        while True:
            chunk=source.read(min(CHUNK_SIZE-len(pending),max_bytes-total+1))
            if not chunk:
                if pending:
                    db.execute(insert(BlobChunk).values(key=key,number=number,data=bytes(pending)))
                break
            total+=len(chunk)
            if total>max_bytes:raise BlobTooLarge('Object exceeds size limit')
            digest.update(chunk);pending.extend(chunk)
            if len(pending)==CHUNK_SIZE:
                db.execute(insert(BlobChunk).values(key=key,number=number,data=bytes(pending)))
                number+=1;pending.clear()
        sha=digest.hexdigest()
        db.execute(update(BlobObject).where(BlobObject.key==key).values(size=total,sha256=sha))
    return {'key':key,'size':total,'sha256':sha,'mime':mime[:200]}

def metadata(db,key):
    validate_key(key)
    row=db.execute(select(BlobObject.key,BlobObject.size,BlobObject.sha256,BlobObject.mime).where(BlobObject.key==key)).mappings().first()
    return dict(row) if row else None

def read_range(db,key,start,length):
    if start<0 or length<0:raise ValueError('Invalid range')
    end=start+length
    for number in range(start//CHUNK_SIZE,(end+CHUNK_SIZE-1)//CHUNK_SIZE):
        row=db.execute(select(BlobChunk.data).where(BlobChunk.key==key,BlobChunk.number==number)).first()
        if row is None:raise IOError('Missing object chunk')
        chunk=bytes(row[0]);offset=number*CHUNK_SIZE
        yield chunk[max(start-offset,0):min(end-offset,len(chunk))]

def response(db,key,request,filename=None,private=False):
    """Materialize in an independent short snapshot, never mutate caller state.

    REPEATABLE READ needs no row/share locks: a concurrent delete can commit
    while this snapshot reads the old chunks. Connection closes before body IO.
    """
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from fastapi.responses import Response
    from app.services.blob_cache import acquire, CachedFileResponse
    validate_key(key)
    bind = db.get_bind()
    # Bind may be a Connection in tests; do not reuse its caller transaction.
    engine = getattr(bind, 'engine', bind)
    if engine.dialect.name == 'postgresql':
        engine = engine.execution_options(isolation_level='REPEATABLE READ', postgresql_readonly=True)
    with Session(engine) as snapshot:
        row = metadata(snapshot, key)
        if row is None:
            raise HTTPException(404, 'Object not found', headers={'Cache-Control':'no-store'} if private else None)
        if not re.fullmatch(r'[0-9a-f]{64}',row['sha256']):
            raise IOError('Invalid object digest')
        etag = '"' + row['sha256'] + '"'
        headers = {'ETag': etag}
        if private:
            headers['Cache-Control'] = 'no-store'
        matches = [part.strip().removeprefix('W/') for part in request.headers.get('if-none-match','').split(',')]
        if etag in matches or '*' in matches:
            return Response(status_code=304, headers=headers)
        if request.method == 'HEAD':
            # HEAD is metadata-only, even when disk is full or object exceeds cap.
            # RFC 9110 Range is only defined for GET; ignore it on HEAD.
            from fastapi.responses import FileResponse
            template = FileResponse('', media_type=row['mime'], filename=filename, headers=headers)
            template.headers['content-length'] = str(row['size'])
            return Response(headers=dict(template.headers))
        lease = acquire(row['sha256'], row['size'], lambda: read_range(snapshot,key,0,row['size']))
    try:
        return CachedFileResponse(lease,media_type=row['mime'],filename=filename,headers=headers)
    except BaseException:
        lease.close()
        raise


def parse_range(header,size):
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',header or '')
    if not match or size<=0:raise ValueError('Unsatisfiable range')
    a,b=match.groups()
    if not a and not b:raise ValueError('Empty range')
    if a:
        start=int(a);stop=min(int(b)+1,size) if b else size
    else:
        suffix=int(b)
        if suffix<=0:raise ValueError('Invalid suffix')
        start=max(0,size-suffix);stop=size
    if start>=size or start>=stop:raise ValueError('Unsatisfiable range')
    return start,stop
