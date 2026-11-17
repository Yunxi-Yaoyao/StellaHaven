"""Resident fixture supervisor + source-restricted transparent CA TLS relay.
Only own Compose lifecycle; no production agents, routes, firewall or host probes.
"""
import subprocess,json,time,threading,socketserver,socket,select
from pathlib import Path
from relay_policy import read_client_hello
ROOT=Path(__file__).parent
PRIVATE=Path('/var/lib/stella-preview-20261018/private/final-acceptance')
NODES={'stella-live-test-a':0,'stella-live-test-b':1}
class Handler(socketserver.BaseRequestHandler):
 def handle(self):
  if self.client_address[0] not in ('192.168.160.2','192.168.160.3'):return
  try:
   hello=read_client_hello(self.request)
   with socket.create_connection(('192.168.0.103',443),timeout=5) as upstream:
    upstream.sendall(hello)
    sockets=[self.request,upstream];deadline=time.monotonic()+40
    while time.monotonic()<deadline:
     r,_,_=select.select(sockets,[],[],1)
     for src in r:
      data=src.recv(65536)
      if not data:return
      (upstream if src is self.request else self.request).sendall(data)
  except (OSError,TimeoutError):return
class Relay(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True;request_queue_size=16

def run(argv,**kw):return subprocess.run(argv,check=True,capture_output=True,**kw)
run(['docker','compose','-f',str(ROOT/'compose.yml'),'up','-d','--no-build'])
relay=Relay(('192.168.160.1',25451),Handler)
threading.Thread(target=relay.serve_forever,daemon=True).start()
print('resident relay ready; tokens private stdin/tmpfs only',flush=True)
seen={}
while True:
 for name,index in NODES.items():
  try:
   data=json.loads(run(['docker','inspect',name]).stdout)[0]
   if not data['State']['Running']:continue
   started=data['State']['StartedAt']
   if seen.get(name)==started:continue
   config=json.loads((PRIVATE/f'agent-{index}.json').read_text())
   if config['node_id']!=index+2:raise RuntimeError('owned node identity mismatch')
   # stdin, not argv/environment/image/host mount; target lives in bounded tmpfs.
   run(['docker','exec','-i',name,'python','-c',"import sys,pathlib,os;p=pathlib.Path('/run/stella');p.mkdir(mode=0o700,exist_ok=True);f=p/'identity.json';f.write_bytes(sys.stdin.buffer.read());os.chmod(f,0o600)"],input=json.dumps(config).encode())
   seen[name]=started;print('identity handed to '+name+' in tmpfs',flush=True)
  except Exception as e:print('fixture supervision retry: '+type(e).__name__,flush=True)
 time.sleep(3)
