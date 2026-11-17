"""Persistent isolated Agent runtime. Tokens exist only in /run tmpfs + memory.
Never calls full Agent.run(), inventory, upgrades or command/network admin.
"""
import json,os,time,sys,threading,subprocess,socketserver
from pathlib import Path
os.environ['PATH']='/fixture/bin:'+os.environ['PATH'];os.environ['MTR_PACKET']='/fixture/bin/mtr-packet'
os.chdir('/fixture');sys.path.insert(0,'/fixture')
import stella_agent as mod
from fixture_policy import allowed,mtr_params

def event(**data):print(json.dumps({'at':time.time(),**data},ensure_ascii=False),flush=True)
class Target(socketserver.BaseRequestHandler):
 def handle(self):self.request.sendall(b'HTTP/1.0 200 OK\r\nContent-Length: 24\r\n\r\nStella owned test target\n')
class Server(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True
threading.Thread(target=Server(('0.0.0.0',8080),Target).serve_forever,daemon=True).start()
p=Path('/run/stella/identity.json')
while not p.exists():time.sleep(.5)
c=json.loads(p.read_text());p.unlink();a=mod.Agent(c['url'],c.pop('token'));Path('/run/stella/ready').touch()
original_popen=subprocess.Popen
class Tee:
 def __init__(self,s):self.s=s
 def readline(self,*args):
  v=self.s.readline(*args)
  if v:event(tool_stdout=v.rstrip())
  return v
 def __getattr__(self,n):return getattr(self.s,n)
def popen(argv,*args,**kw):
 event(exec_argv=argv);p=original_popen(argv,*args,**kw)
 if p.stdout and isinstance(argv,list) and argv[0]=='mtr':p.stdout=Tee(p.stdout)
 return p
subprocess.Popen=popen
post=a._post
def observe(path,json_body=None,**kw):
 r=post(path,json_body=json_body,**kw)
 if path!='/agent/report' and not path.endswith('/live'):event(http_post=path,status=kw.get('status'),body=json_body,response=r)
 return r
a._post=observe
apply=a._apply_monitors
seen=set()
def apply_scoped(monitors):
 clean=[]
 for m in monitors:
  if allowed(m.get('type'),m.get('target')):
   m=dict(m);m['interval']=max(60,m['interval']);m['timeout']=min(2,max(1,m['timeout']));clean.append(m)
  elif m['id'] not in seen:seen.add(m['id']);event(blocked_monitor_id=m['id'],reason='outside owned target policy; no probe or sample')
 apply(clean)
a._apply_monitors=apply_scoped
stream=a._mtr_stream
mtr_lock=threading.Lock()
def scoped_stream(target,protocol='icmp',params=None,live_cb=None):
 if not allowed(protocol,target):raise RuntimeError('Fixture scope: only numeric owned targets, ICMP or TCP 8080/8081')
 p=mtr_params(params)
 with mtr_lock:return stream(target,protocol,p,live_cb=live_cb)
a._mtr_stream=scoped_stream
# Deny rather than execute all remote shell/install/net/WG/Docker/IP/admin tasks.
reason='测试节点容器：此工具需经授权的真实宿主Agent；本fixture不读写宿主网络、WG、防火墙、Docker或运行命令'
def deny_net(t):a._post(f"/agent/net-tasks/{t['id']}/result",status='failed',json_body={'error':reason})
def deny_command(t):a._post(f"/agent/commands/{t['id']}/result",json_body={'status':'failed','stdout':'','stderr':reason,'exit_code':-1})
def deny_component(t):a._post(f"/agent/component-installs/{t['id']}/result",status='failed',json_body={'error':reason})
def deny_iperf(t):a._post(f"/agent/iperf-tasks/{t['id']}/result",status='failed',json_body={'error':'测试节点仅支持有界MTR/Ping/TCP；打流需单独授权'})
a._run_net_task=deny_net;a._run_command=deny_command;a._run_component_install=deny_component;a._run_iperf=deny_iperf
a._run_uninstall=lambda: a._post('/agent/uninstall/result',status='failed',error='常驻容器fixture请由其独立Compose服务管理；不会伪报宿主卸载成功')
components={'mtr':{'installed':True,'version':a._comp_version('/fixture/bin/mtr',['--version'])}}
components['monitoring']={**a._monitoring_capability(),'scope':'container','targets':['192.168.160.2','192.168.160.3']}
components['monitoring']['test_targets']=[
 {'type':'ping','target':'192.168.160.3','description':'A → B 的 Ping / ICMP MTR'},
 {'type':'tcp','target':'192.168.160.3:8080','description':'真实开放的受控容器服务 / TCP MTR'},
 {'type':'tcp','target':'192.168.160.3:8081','description':'明确关闭的容器端口；失败不代表丢包率'}]
def heartbeat():
 while True:
  try:
   # Only namespace-scoped NIC deltas. /proc CPU/memory may reflect host; OMIT.
   a._post('/agent/report',json_body={'metrics':a.collect_metrics(),'sys_metrics':[],'agent_version':mod.AGENT_VERSION,'interfaces':a.list_interfaces(),'components':components,'os_info':{'os_name':'测试节点容器 · 仅容器网络空间；非宿主机'}})
   a.refresh_config()
  except Exception as e:event(heartbeat_error_type=type(e).__name__)
  time.sleep(10)
def probes():
 while True:
  try:a.run_due_probes()
  except Exception as e:event(probe_error_type=type(e).__name__)
  time.sleep(2)
# interfaces_info name adapted only to exact candidate method below if needed.
threading.Thread(target=heartbeat,daemon=True).start();threading.Thread(target=probes,daemon=True).start()
event(started=True,node_id=c['node_id'],mode='persistent isolated test node',allowed_targets=['192.168.160.2','192.168.160.3'],heartbeat_seconds=10,minimum_monitor_interval=60)
while True:
 try:a.poll_and_execute()
 except Exception as e:event(poll_error_type=type(e).__name__)
 time.sleep(2)
