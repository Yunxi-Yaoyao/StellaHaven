"""Owned HTTP/HTTPS upstream and an independent server-side OIDC relying party."""
from control import ROOT,STATE,OUT,save
import json,ssl,threading,secrets,hashlib,base64,time
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlsplit,parse_qs,urlencode
import httpx
from authlib.jose import jwt,JsonWebKey
s=json.loads(STATE.read_text());pending={};records=[]
def provider():return httpx.Client(base_url='https://127.0.0.1',headers={'Host':'stella.xiya.live'},verify=str(ROOT/'ca.pem'),trust_env=False,timeout=10)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def send(self,code,body='',headers=None):
  self.send_response(code)
  for k,v in (headers or {}).items():self.send_header(k,v)
  self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body.encode())
 def do_GET(self):
  path=urlsplit(self.path).path
  if path=='/rp/start':
   rp=json.loads((ROOT/'rp-private.json').read_text());state=secrets.token_urlsafe(32);nonce=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
   with provider() as c:
    d=c.get('/.well-known/openid-configuration');assert d.status_code==200;discovery=d.json();assert discovery['issuer']==s['origin']
   pending[state]=dict(nonce=nonce,verifier=verifier,rp=rp,discovery=discovery)
   params=dict(client_id=rp['client_id'],response_type='code',redirect_uri=rp['callback'],scope='openid profile email',state=state,nonce=nonce,code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),code_challenge_method='S256')
   return self.send(302,headers={'Location':discovery['authorization_endpoint']+'?'+urlencode(params),'Set-Cookie':'rp_state='+state+'; Path=/rp; Secure; HttpOnly; SameSite=Lax'})
  if path=='/rp/callback':
   try:
    q=parse_qs(urlsplit(self.path).query);cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''));state=q.get('state',[''])[0]
    if state not in pending or 'rp_state' not in cookie or not secrets.compare_digest(state,cookie['rp_state'].value):return self.send(400,'State rejected')
    tx=pending.pop(state);rp=tx['rp'];body=dict(grant_type='authorization_code',client_id=rp['client_id'],client_secret=rp['client_secret'],code=q['code'][0],redirect_uri=rp['callback'],code_verifier=tx['verifier'])
    with provider() as c:
     wrong=c.post('/oauth/token',data=body|{'code_verifier':'x'*64});assert wrong.status_code==400
     response=c.post('/oauth/token',data=body);assert response.status_code==200;token=response.json()
     jwks=c.get('/oauth/jwks');assert jwks.status_code==200;keys=JsonWebKey.import_key_set(jwks.json())
     options={'iss':{'essential':True,'value':s['origin']},'aud':{'essential':True,'value':rp['client_id']},'nonce':{'essential':True,'value':tx['nonce']},'exp':{'essential':True}}
     claims=jwt.decode(token['id_token'],keys,claims_options=options);claims.validate();assert claims['sub']==rp['uid']
     tampered=token['id_token'].split('.');tampered[1]=base64.urlsafe_b64encode(json.dumps(dict(claims)|{'nonce':'forged'}).encode()).decode().rstrip('=')
     try:jwt.decode('.'.join(tampered),keys).validate()
     except Exception:tamper_rejected=True
     else:raise AssertionError('modified payload signature accepted')
     try:jwt.decode(token['id_token'],keys,claims_options=options|{'nonce':{'essential':True,'value':'wrong-nonce'}}).validate()
     except Exception:nonce_rejected=True
     else:raise AssertionError('wrong nonce accepted')
     info=c.get('/oauth/userinfo',headers={'Authorization':'Bearer '+token['access_token']});assert info.status_code==200 and info.json()['sub']==claims['sub']
     replay=c.post('/oauth/token',data=body);assert replay.status_code==400
    save('rp-roundtrip',dict(browser_callback=True,state_cookie_matched=True,nonce_validated=True,s256_wrong_verifier=wrong.status_code,token=200,jwks=200,signature_verified=True,tampered_signature_rejected=tamper_rejected,wrong_nonce_rejected=nonce_rejected,issuer_audience_exp_validated=True,sub_userinfo_owner_equal=True,code_replay=replay.status_code))
    return self.send(200,'<h1 id="rp-success">Owned RP signed-in</h1><p>state, nonce, S256 and JWKS RS256 verified</p>')
   except Exception as exc:
    save('rp-failure',{'exception':type(exc).__name__});return self.send(500,'RP verification failed')
  if path=='/rp/':return self.send(200,'<h1>Owned relying party</h1><a href="/rp/start">Sign in with Stella</a>')
  authorized=self.headers.get('Authorization')==s['upstream_secret']
  record=dict(port=self.server.server_port,path=path,credential_matches=authorized,credential_present=bool(self.headers.get('Authorization')),cookie_names=sorted([x.strip().split('=')[0] for x in self.headers.get('Cookie','').split(';') if x.strip()]),origin=self.headers.get('Origin'),host=self.headers.get('Host'))
  records.append(record);save('upstream-requests',records)
  if path=='/protected' and not authorized:return self.send(401,'Header credential required')
  headers={'Cache-Control':'no-store'}
  if path=='/deny':headers['X-Frame-Options']='DENY'
  if path=='/csp':headers['Content-Security-Policy']="default-src 'self'; frame-ancestors 'none'"
  body='<html><head><title>Owned upstream '+str(self.server.server_port)+'</title></head><body style="background:white;color:black"><h1 id="owned-content">Owned upstream '+str(self.server.server_port)+' '+path+'</h1><div id="paint">Original style</div><p id="effect">Original script</p><button id="probe" onclick="fetch(\'/business\',{method:\'POST\'}).then(r=>r.text()).then(t=>document.getElementById(\'business\').textContent=t)">Read business API</button><p id="business"></p></body></html>'
  return self.send(200,body,headers)
 def do_POST(self):
  body=self.rfile.read(int(self.headers.get('Content-Length','0')))
  if urlsplit(self.path).path=='/business':
   good=self.headers.get('Origin')==('http://127.0.0.1:18081' if self.server.server_port==18081 else 'https://127.0.0.1:18443')
   records.append(dict(port=self.server.server_port,path='/business',origin=self.headers.get('Origin'),accepted=good,credential_matches=self.headers.get('Authorization')==s['upstream_secret'],cookie_names=sorted([x.strip().split('=')[0] for x in self.headers.get('Cookie','').split(';') if x.strip()])));save('upstream-requests',records)
   return self.send(200 if good else 403,'Business body OK' if good else 'Origin denied')
  return self.send(404)
servers=[]
for port in [18081,18443]:
 server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
 if port==18443:
  context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(ROOT/'tls.pem',ROOT/'tls.key');server.socket=context.wrap_socket(server.socket,server_side=True)
 servers.append(server);threading.Thread(target=server.serve_forever,daemon=True).start()
print('Owned HTTP HTTPS and RP listeners ready',flush=True)
try:
 while True:time.sleep(1)
finally:
 for server in servers:server.shutdown()
