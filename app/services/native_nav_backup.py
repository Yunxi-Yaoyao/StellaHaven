"""New settings domain adapter. Does not project sessions, notes or other domains."""
import io
from uuid import UUID
from sqlalchemy import inspect,select
from app.models.native_nav import NavState,NavAsset
from app.models.user import User
from app.schemas.native_nav import NavData
from app.services.backup_archive import InvalidArchive
from app.services.native_nav_package import dimensions,sha,references
from app.services.native_nav_budget import check_config_budget

PREFIX='resources/native-nav/'
MAX_DOMAIN_BYTES=64*1024**2


def export_domain(db, entries):
    if not inspect(db.get_bind()).has_table('nav_states'): return []
    records=[];total=0
    for row in db.scalars(select(NavState).order_by(NavState.owner_id)):
        data=NavData.model_validate(row.data).model_dump(mode='json')
        assets=[]
        for a in db.scalars(select(NavAsset).where(NavAsset.owner_id==row.owner_id).order_by(NavAsset.id)):
            total+=a.size
            if total>MAX_DOMAIN_BYTES: raise InvalidArchive('native navigation domain limit')
            key=PREFIX+str(row.owner_id)+'/'+str(a.id)
            entries[key]=io.BytesIO(a.content)
            assets.append({'id':str(a.id),'name':a.name,'mime':a.mime,'size':a.size,'sha256':sha(a.content),'entry':key,'category':a.category})
        records.append({'owner_id':str(row.owner_id),'data':data,'assets':assets})
    return records


def validate_domain(records, archive, manifest):
    """Fully validate bytes and references before starting any restore writes."""
    if not isinstance(records,list) or len(records)>10000: raise InvalidArchive('native navigation domain limit')
    owners=set();ids=set();required=set();plans=[];domain_total=0
    try:
        for record in records:
            if set(record)!={'owner_id','data','assets'}: raise ValueError()
            owner=UUID(record['owner_id'])
            if owner in owners: raise ValueError()
            owners.add(owner)
            data=NavData.model_validate(record['data']).model_dump(mode='json')
            check_config_budget(data)
            assets=record['assets']
            if not isinstance(assets,list) or len(assets)>100: raise ValueError()
            total=0;rows=[];refs=set()
            for a in assets:
                if set(a) not in ({'id','name','mime','size','sha256','entry'}, {'id','name','mime','size','sha256','entry','category'}): raise ValueError()
                category=a.get('category','uncategorized')
                if category not in {'uncategorized','icon','background','logo','other'}: raise ValueError()
                aid=UUID(a['id'])
                if aid in ids or a['entry']!=PREFIX+str(owner)+'/'+str(aid): raise ValueError()
                ids.add(aid);required.add(a['entry']);refs.add('/nav-assets/'+str(aid))
                if not isinstance(a['name'],str) or not 1<=len(a['name'])<=120 or type(a['size']) is not int or not 0<a['size']<=3*1024**2: raise ValueError()
                if manifest['entries'].get(a['entry'])!={'bytes':a['size'],'sha256':a['sha256']}: raise ValueError()
                domain_total+=a['size']
                if domain_total>MAX_DOMAIN_BYTES: raise ValueError()
                content=archive.read(a['entry'])
                if sha(content)!=a['sha256'] or dimensions(content)[0]!=a['mime']: raise ValueError()
                total+=len(content)
                if total>30*1024**2: raise ValueError()
                rows.append({k:a[k] for k in ('name','mime','size')}|{'id':aid,'content':content,'owner_id':owner,'category':category})
            if not set(references(data))<=refs: raise ValueError()
            plans.append((owner,data,rows))
        if {k for k in manifest['entries'] if k.startswith(PREFIX)}!=required: raise ValueError()
        return plans
    except Exception:
        raise InvalidArchive('invalid native navigation settings') from None


def restore_domain(db,plans):
    from app.routers.native_nav import lock
    for owner,data,assets in sorted(plans,key=lambda p:str(p[0])):
        if db.get(User,owner) is None: raise InvalidArchive('native navigation owner missing')
        row=lock(db,owner)
        # Prevent UUID collision from ever overwriting another owner's bytes.
        for a in assets:
            old=db.get(NavAsset,a['id'])
            if old is not None and old.owner_id!=owner: raise InvalidArchive('native navigation asset owner conflict')
        modules={c['module_id'] for g in data['groups'] for c in g['items'] if c.get('module_id')}
        if modules:
            from app.services.integrations import state
            if not modules<=set(state(db)['modules']): raise InvalidArchive('native navigation module missing')
        for old in db.scalars(select(NavAsset).where(NavAsset.owner_id==owner)): db.delete(old)
        db.flush()
        for a in assets: db.add(NavAsset(**a))
        row.data=data;row.revision+=1;row.mutation_id='';row.mutation_hash=''
        db.flush()
