"""Actual auth lifecycle, ordinary browser cookies and owned RP registration."""
from control import ROOT,STATE,save
import json,secrets,httpx
s=json.loads(STATE.read_text());origin=s['origin']
def client():return httpx.Client(base_url='https://127.0.0.1',headers={'Host':'stella.xiya.live','Origin':origin},verify=str(ROOT/'ca.pem'),trust_env=False,timeout=20)
def ok(r,code=200):
 assert r.status_code==code,(r.status_code,r.text[:300]);return r.json() if r.content else None
p=ROOT/'auth-private.json'
if not p.exists():
 password=secrets.token_urlsafe(24);management=secrets.token_urlsafe(24)
 with client() as c:
  assert ok(c.get('/auth/status'))['initialized'] is False
  owner=ok(c.post('/auth/register',json={'username':'website-owned','password':password}),201)
  ok(c.post('/auth/admin/setup',json={'user_password':password,'new_password':management}));ok(c.post('/auth/logout'))
  ok(c.post('/auth/login',json={'username':'website-owned','password':password,'remember':True}));assert ok(c.post('/auth/admin/unlock',json={'password':management}))['elevated'];elevated=dict(c.cookies)
 with client() as c:
  ok(c.post('/auth/login',json={'username':'website-owned','password':password,'remember':True}));assert not ok(c.get('/auth/security'))['elevated'];ordinary=dict(c.cookies)
 a=dict(uid=owner['id'],elevated=elevated,ordinary=ordinary,url=origin,password=password,management=management)
 p.write_text(json.dumps(a));p.chmod(0o600)
else:
 a=json.loads(p.read_text())
 for kind in ['ordinary','elevated']:
  with client() as c:
   ok(c.post('/auth/login',json={'username':'website-owned','password':a['password'],'remember':True}))
   if kind=='elevated':assert ok(c.post('/auth/admin/unlock',json={'password':a['management']}))['elevated']
   a[kind]=dict(c.cookies)
 p.write_text(json.dumps(a))
with client() as c:
 c.cookies.update(a['elevated']);assert ok(c.post('/auth/admin/unlock',json={'password':a['management']}))['elevated']
 callback='https://127.0.0.1:18443/rp/callback';cid='owned-'+secrets.token_hex(8)
 reg=ok(c.post('/auth/provider/clients',json=dict(client_id=cid,name='Owned browser RP',enabled=True,redirect_uris=[callback],scopes=['openid','profile','email'],generate_secret=True)),201)
 assert 'client_secret' not in ok(c.get('/auth/provider/clients/'+cid))
 (ROOT/'rp-private.json').write_text(json.dumps(dict(client_id=cid,client_secret=reg['client_secret'],callback=callback,uid=a['uid'])));(ROOT/'rp-private.json').chmod(0o600)
with client() as c:
 c.cookies.update(a['ordinary']);assert not ok(c.get('/auth/security'))['elevated'];assert c.get('/auth/provider/clients').status_code==403
save('auth',dict(real_register_setup_login_unlock=True,ordinary_elevated=False,ordinary_provider_management=403,client_secret_readback_absent=True,production_accounts_touched=False))
print('Real ordinary/admin sessions and owned RP registered')
