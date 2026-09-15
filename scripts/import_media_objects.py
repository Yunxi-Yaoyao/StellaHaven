#!/usr/bin/env python3
"""Explicit offline file→PG import; source untouched, one transaction, no overwrite.

Run only during a verified write-stop window after DB/files backup. Dry-run by
 default. Never imports fixed model packs, SQLite databases or external services.
"""
import argparse,json,pathlib,sys,hashlib,mimetypes
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine,text,select,insert
from sqlalchemy.orm import Session
from app.models.attachment import Attachment
from app.models.user import User
from app.models.config import AppConfig
from app.models.blob import BlobObject
from app.services.blob_store import put

def safe_file(root,relative):
    if relative.startswith('/') or '..' in pathlib.PurePosixPath(relative).parts:raise RuntimeError('unsafe source path')
    p=root/relative
    if p.is_symlink() or root not in p.resolve().parents or not p.is_file():raise RuntimeError('missing or unsafe source object')
    return p

def inventory(db,root):
    objects={}
    def add(key,path,mime,limit):
        p=safe_file(root,path)
        if p.stat().st_size>limit:raise RuntimeError('source object exceeds supported limit')
        objects[key]=(p,mime,limit)
    for a in db.execute(select(Attachment)).scalars():
        key='attachments/'+str(a.id)
        add(key,key,a.mime,25*1024*1024)
        if objects[key][0].stat().st_size != a.size:
            raise RuntimeError('attachment size mismatch')
    for user in db.execute(select(User)).scalars():
        urls=set(json.loads(user.avatar_history or '[]'))
        if user.avatar_url:urls.add(user.avatar_url)
        for url in urls:
            if not url.startswith('/assets/avatars/'):continue
            name=url.removeprefix('/assets/avatars/')
            add('avatars/'+name,'assets/avatars/'+name,mimetypes.guess_type(name)[0] or 'application/octet-stream',10*1024*1024)
    index=root/'assets/homebg/index.json'
    entries=json.loads(index.read_text()) if index.exists() else []
    for entry in entries:
        name=entry['file'];add('homebg/'+name,'assets/homebg/'+name,mimetypes.guess_type(name)[0] or 'application/octet-stream',80*1024*1024)
        # Existing generated derivatives are referenced from .media.json by URL.
        sidecar=root/'assets/homebg'/('.'+name+'.media.json')
        if sidecar.exists():
            media=json.loads(sidecar.read_text());entry['media']=media
            refs=[media.get('poster'),media.get('thumbnail'),*media.get('variants',{}).values()]
            for url in refs:
                if isinstance(url,str) and url.startswith('/assets/homebg/'):
                    n=url.removeprefix('/assets/homebg/');add('homebg/'+n,'assets/homebg/'+n,mimetypes.guess_type(n)[0] or 'application/octet-stream',80*1024*1024)
    return objects,entries

def main():
    p=argparse.ArgumentParser();p.add_argument('--dsn-file',required=True);p.add_argument('--source',required=True);p.add_argument('--confirm-database',required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
    source=pathlib.Path(args.source).resolve()
    if not source.is_dir():raise RuntimeError('source directory missing')
    engine=create_engine(pathlib.Path(args.dsn_file).read_text().strip(),pool_pre_ping=True)
    with Session(engine) as db:
        actual=db.execute(text('SELECT current_database()')).scalar_one()
        if actual!=args.confirm_database:raise RuntimeError('database confirmation mismatch')
        if db.execute(text('SELECT pg_is_in_recovery()')).scalar_one():raise RuntimeError('target is not writable primary')
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('stella-media-import-v1',0))"))
        objects,entries=inventory(db,source)
        if db.execute(select(BlobObject.key).limit(1)).first():raise RuntimeError('refusing nonempty target blob store')
        if db.get(AppConfig,'homebg_index') is not None:raise RuntimeError('refusing existing background index')
        summary={'objects':len(objects),'bytes':sum(v[0].stat().st_size for v in objects.values()),'backgrounds':len(entries),'applied':False}
        if args.apply:
            for key,(path,mime,limit) in objects.items():
                with path.open('rb') as f:info=put(db,key,f,mime,limit)
                expected=hashlib.sha256()
                with path.open('rb') as f:
                    for block in iter(lambda:f.read(256*1024),b''):expected.update(block)
                if info['sha256']!=expected.hexdigest():raise RuntimeError('source changed while importing')
            db.add(AppConfig(key='homebg_index',value=json.dumps(entries,ensure_ascii=False)));db.commit();summary['applied']=True
            # Read back the exact committed row totals, not just commit success.
            count=db.execute(text('SELECT count(*) FROM blob_objects')).scalar_one()
            if count!=len(objects):raise RuntimeError('committed object count mismatch')
        else:db.rollback()
        print(json.dumps(summary))
    engine.dispose()

if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit('Import refused/failed: '+type(exc).__name__)
