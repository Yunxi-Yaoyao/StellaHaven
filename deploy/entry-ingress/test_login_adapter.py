"""Real loopback nginx -> owned HTTP upstream; no production DNS or service edits."""
import importlib.util,json,os,socket,subprocess,tempfile,threading,time,urllib.request,sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('adapter',HERE/'render_login_adapter.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
PUBLIC='https://stella.example/oauth/authorize';PRIVATE='https://stella.p.example/oauth/authorize'
query='redirect_uri=https%3A%2F%2Frp.p.example%2Fcallback&state=exact%2Bstate&nonce=keep&code_challenge=verbatim_-challenge&code_challenge_method=S256&client_id=generic&response_type=code'
body=json.dumps({'url':PUBLIC+'?'+query,'issuer':'https://stella.example','note':'leave https://stella.example alone'},separators=(',',':')).encode()
class Upstream(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  self.rfile.read(int(self.headers.get('Content-Length','0')));self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def do_GET(self):self.do_POST()
u=ThreadingHTTPServer(('127.0.0.1',0),Upstream);thread=threading.Thread(target=u.serve_forever,daemon=True);thread.start()
rule=dict(service_id='synthetic-rp',path='/api/oauth/authorize',upstream='http://127.0.0.1:'+str(u.server_port),public_authorization=PUBLIC,private_authorization=PRIVATE,response_key='url')
for bad in [dict(rule,path='/api/../secret'),dict(rule,upstream='http://169.254.169.254:80'),dict(rule,private_authorization='https://evil.test/?x=1'),dict(rule,response_key="x'; return 200; #")]:
 try:m.render(bad)
 except ValueError:pass
 else:raise AssertionError('invalid input accepted')
client=urllib.request.build_opener(urllib.request.ProxyHandler({}));baseline='--baseline' in sys.argv
with tempfile.TemporaryDirectory(prefix='stella-entry-nginx-',dir='/root/.hermes/cache/scratch') as tmp:
 d=Path(tmp);s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close()
 block='' if baseline else m.render(rule)
 conf=f'pid {d}/nginx.pid; error_log {d}/error.log; events{{worker_connections 64;}} http{{access_log off; client_body_temp_path {d}/body; proxy_temp_path {d}/proxy; server{{listen 127.0.0.1:{port}; {block} location / {{ proxy_pass {rule["upstream"]}; }} }} }}'
 (d/'nginx.conf').write_text(conf);subprocess.run(['nginx','-p',tmp+'/', '-c',str(d/'nginx.conf'),'-t'],check=True,capture_output=True)
 proc=subprocess.Popen(['nginx','-p',tmp+'/', '-c',str(d/'nginx.conf'),'-g','daemon off;'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 try:
  for _ in range(40):
   try:
    with socket.create_connection(('127.0.0.1',port),timeout=.2):break
   except OSError:time.sleep(.05)
  with client.open(urllib.request.Request(f'http://127.0.0.1:{port}/api/oauth/authorize',data=b'{}',headers={'Content-Type':'application/json'}),timeout=5) as r:
   result=json.load(r);headers=dict(r.headers)
  assert result['url']==PRIVATE+'?'+query,result['url']
  assert result['issuer']=='https://stella.example' and result['note']=='leave https://stella.example alone'
  with client.open(f'http://127.0.0.1:{port}/unrelated',timeout=5) as r:unchanged=r.read()
  assert unchanged==body
  assert headers.get('Cache-Control')=='no-store'
  print(json.dumps({'real_nginx':True,'redirect_only':True,'query_bytes_unchanged':True,'issuer_unchanged':True,'unrelated_endpoint_unchanged':True,'invalid_rules_rejected':4}))
 finally:
  proc.terminate();proc.wait(timeout=10);u.shutdown();u.server_close();thread.join(5)
