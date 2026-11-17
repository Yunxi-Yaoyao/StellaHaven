"""Read-only yaya-nav SQLite -> owner-local transfer + lossless navigation rows.

Never opens auth tables, writes the source DB, fetches URLs or edits the old tree.
Output contains PRIVATE bookmarks. Keep it outside Git, under a new 0700 directory.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat


def dumps(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def asset_bytes(root,source):
    parts=PurePosixPath(source.removeprefix('./')).parts
    if not parts or parts[0]!='files' or any(p in {'..','.'} for p in parts):
        raise ValueError('asset must be beneath the legacy files root')
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        file=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            before=os.fstat(file)
            if not stat.S_ISREG(before.st_mode) or before.st_size>3*1024**2:raise ValueError('unsupported asset size/type')
            content=b''
            while len(content)<=3*1024**2:
                chunk=os.read(file,65536)
                if not chunk:break
                content+=chunk
            after=os.fstat(file)
            if (before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('asset changed while exporting')
            if len(content)!=before.st_size:raise ValueError('asset changed while exporting')
            return content
        finally:os.close(file)
    finally:os.close(fd)


def extract(database, state_root, owner, effective_defaults=None):
    if not isinstance(owner,int) or owner<1:raise ValueError('explicit positive legacy owner ID required')
    # mode=ro still sees the WAL. Do not use immutable=1 on a live database.
    conn=sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
    conn.row_factory=sqlite3.Row
    try:
        conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
        def rows(table,order,deleted=True):
            where=' AND deleted_at IS NULL' if deleted else ''
            return [dict(r) for r in conn.execute(f'SELECT * FROM {table} WHERE user_id=?{where} ORDER BY {order}',(owner,))]
        groups=rows('item_icon_group','sort,id');items=rows('item_icon','sort,id')
        configs=rows('user_config','user_id',False);files=rows('file','id')
        if not groups and not configs:raise ValueError('owner has no navigation data')
        if len(configs)>1 or len(groups)>100 or len(items)>2000 or len(files)>100:raise ValueError('legacy data exceeds supported limits')
        group_ids={g['id'] for g in groups}
        if any(i['item_icon_group_id'] not in group_ids for i in items):raise ValueError('orphan card requires explicit repair in source')
        icons=[]
        for g in groups:
            children=[{'title':i['title'],'url':i['url'] or '', 'lanUrl':i['lan_url'] or '', 'description':i['description'] or '', 'icon':json.loads(i['icon_json']) if i['icon_json'] else None,'sort':i['sort'],'openMethod':i['open_method']} for i in items if i['item_icon_group_id']==g['id']]
            icons.append({'title':g['title'],'description':g['description'] or '', 'icon':g['icon'] or '', 'style':json.loads(g['style_json']) if g['style_json'] else None,'sort':g['sort'],'children':children})
        listing={'version':1,'appName':'Stella-Nav-Config','exportTime':'','appVersion':'legacy-readonly-extractor','icons':icons}
        listing['md5']=hashlib.md5(dumps(listing).encode()).hexdigest()
        assets=[];raw_assets=[];total=0
        for f in files:
            content=asset_bytes(state_root,f['src']);total+=len(content)
            if total>30*1024**2:raise ValueError('legacy assets exceed 30 MiB')
            # MIME is validated again by the platform header parser on preflight.
            ext=Path(f['src']).suffix.lower()
            mime={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.gif':'image/gif'}.get(ext)
            if not mime:raise ValueError('unsupported asset: preserve original and resolve before import')
            source='/'+f['src'].removeprefix('./').lstrip('/')
            asset={'source':source,'name':f['file_name'] or Path(f['src']).name,'mime':mime,'size':len(content),'sha256':sha(content),'base64':base64.b64encode(content).decode(),'category':f.get('purpose') or 'uncategorized'}
            assets.append(asset);raw_assets.append({'record':f,'sha256':sha(content),'base64':asset['base64']})
        config=configs[0] if configs else {}
        transfer={'appName':'Stella-Nav-Transfer','version':1,'list':listing,'userConfig':{'panel':json.loads(config.get('panel_json') or '{}'),'searchEngine':json.loads(config.get('search_engine_json') or '{}')},'assets':assets}
        original={'format':'Stella-Legacy-Nav-Original','version':1,'groups':groups,'items':items,'user_configs':configs,'assets':raw_assets,'counts':{'groups':len(groups),'items':len(items),'assets':len(files)}}
        if effective_defaults is not None:
            if set(effective_defaults)!={'panel','searchEngine','assets','provenance'}:raise ValueError('invalid effective defaults manifest')
            config=transfer['userConfig']
            config['panel']={**effective_defaults['panel'],**config['panel']}
            search=config['searchEngine']
            # Match normalizeSearchConfig: absent/empty list uses builtin engines.
            if not search.get('searchEngineList'):search={**effective_defaults['searchEngine'],**search,'searchEngineList':effective_defaults['searchEngine']['searchEngineList']}
            config['searchEngine']=search
            assets.extend(effective_defaults['assets'])
            original['effective_defaults']=effective_defaults
        return transfer,original
    finally:conn.rollback();conn.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True);parser.add_argument('--state-root',type=Path,required=True)
    parser.add_argument('--owner',type=int,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--effective-defaults',type=Path,help='pinned source-derived defaults and builtin media, not device storage')
    args=parser.parse_args()
    defaults=json.loads(args.effective_defaults.read_text()) if args.effective_defaults else None
    transfer,original=extract(args.database,args.state_root,args.owner,defaults)
    # Exclusive new directory; never overwrite earlier evidence or source state.
    args.output.mkdir(mode=0o700,parents=False,exist_ok=False)
    receipt={'counts':original['counts'],'files':{},'source_mode':'SQLite mode=ro + query_only + one read transaction','authentication_exported':False}
    for name,value in [('original-navigation.json',original),('transfer.json',transfer)]:
        content=dumps(value).encode();file=args.output/name
        fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(content)
        receipt['files'][name]={'bytes':len(content),'sha256':sha(content)}
    (args.output/'receipt.json').write_text(dumps(receipt));(args.output/'receipt.json').chmod(0o600)
    print(dumps(receipt))

if __name__=='__main__':main()
