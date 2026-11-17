"""Owned disposable PG fixture for built-App browser acceptance. No passwords."""
import json,os
from pathlib import Path
from uuid import uuid4
from app.database import sessionLocal
from app.models.user import User, AuthSession
from app.models.config import AppConfig
from app.models.native_nav import NavState
from app.schemas.native_nav import NavData
from app.services.admin_security import STATE_KEY
from app.routers.auth import _create_session
from starlette.requests import Request
from starlette.responses import Response
assert os.environ['POSTGRES_PORT']=='33070' and os.environ['POSTGRES_DB']=='navqa'
origin='https://127.0.0.1:33171'
with sessionLocal() as db:
    # Own database, remove only prior synthetic fixture identities, never other rows.
    old=db.query(User).filter(User.username.in_(['native-nav-browser','native-nav-browser-other'])).all()
    for user in old: db.delete(user)
    db.commit()
    uid,other=uuid4(),uuid4()
    a=User(id=uid,username='native-nav-browser',display_name='原生导航验收',home_bg='/assets/default-background.webp')
    b=User(id=other,username='native-nav-browser-other',display_name='隔离对照')
    db.add_all([a,b]);row=db.get(AppConfig,STATE_KEY)
    if row: row.value=json.dumps({'owner_id':str(uid)})
    else: db.add(AppConfig(key=STATE_KEY,value=json.dumps({'owner_id':str(uid)})))
    db.commit()
    request=Request({'type':'http','scheme':'https','server':('127.0.0.1',33171),'path':'/auth/login','headers':[(b'host',b'127.0.0.1:33171')],'query_string':b'','client':('127.0.0.1',19999)})
    response=Response();_create_session(db,a,request,response,False);db.commit()
    cookies=[]
    from http.cookies import SimpleCookie
    for header in response.headers.getlist('set-cookie'):
        parsed=SimpleCookie();parsed.load(header)
        for key,v in parsed.items(): cookies.append({'name':key,'value':v.value,'domain':'127.0.0.1','path':v['path'] or '/','secure':bool(v['secure']),'httpOnly':bool(v['httponly']),'sameSite':v['samesite'].capitalize() or 'Lax'})
    out=Path(os.environ['NAV_QA_STATE']);out.write_text(json.dumps({'cookies':cookies,'origins':[]}));out.chmod(0o600)
    Path(os.environ['NAV_QA_STATE']+'.identity').write_text(json.dumps({'owner':str(uid),'other':str(other)}))
    db.add(NavState(owner_id=uid,revision=0,data=NavData().model_dump(mode='json'),mutation_id='',mutation_hash=''));db.commit()
print('synthetic owner/session initialized in dedicated navqa PostgreSQL')
