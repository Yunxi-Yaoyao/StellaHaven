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

def response(db,key,request,filename=None):
    """Materialize immutable local cache under a DB share lock; bounded RAM.

    This is a primary-only app path (the share lock is not valid on PG replicas).
    Business ownership must be checked by the caller before invoking it.
    FileResponse handles HTTP ranges from cache without holding DB open.
    """
    from pathlib import Path
    import tempfile
    from fastapi import HTTPException
    from fastapi.responses import FileResponse, Response
    validate_key(key)
    row=db.execute(select(BlobObject.key,BlobObject.size,BlobObject.sha256,BlobObject.mime).where(BlobObject.key==key).with_for_update(read=True)).mappings().first()
    if row is None:raise HTTPException(404,'Object not found')
    if not re.fullmatch(r'[0-9a-f]{64}',row['sha256']):
        raise IOError('Invalid object digest')
    etag='"'+row['sha256']+'"'
    matches=[part.strip().removeprefix('W/') for part in request.headers.get('if-none-match','').split(',')]
    if etag in matches or '*' in matches:return Response(status_code=304,headers={'ETag':etag})
    cache=Path(os.getenv('STELLA_BLOB_CACHE','data/blob-cache')).resolve()
    cache.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=cache/(row['sha256']+'.bin')
    if target.is_symlink():
        raise IOError('Unsafe cache entry')
    if not target.exists() or target.stat().st_size!=row['size']:
        fd,name=tempfile.mkstemp(prefix='.fill-',dir=cache)
        try:
            digest=hashlib.sha256();total=0
            with os.fdopen(fd,'wb') as out:
                for chunk in read_range(db,key,0,row['size']):
                    out.write(chunk);digest.update(chunk);total+=len(chunk)
                out.flush();os.fsync(out.fileno())
            if total!=row['size'] or digest.hexdigest()!=row['sha256']:raise IOError('Object integrity mismatch')
            os.replace(name,target)
        finally:
            Path(name).unlink(missing_ok=True)
    return FileResponse(target,media_type=row['mime'],filename=filename,headers={'ETag':etag})


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
