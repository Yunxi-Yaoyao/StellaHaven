"""Numeric, no-DNS fixture scope; no URLs, shell expansion or host targets."""
HOSTS=frozenset({'192.168.160.2','192.168.160.3'})
def allowed(kind,target):
 if not isinstance(target,str):return False
 if kind in ('ping','icmp'):return target in HOSTS
 if kind=='tcp':return target in {h+':'+str(p) for h in HOSTS for p in (8080,8081)}
 return False

def mtr_params(params):
 p=params or {}
 return {'count':min(10,max(1,int(p.get('count',5)))),
         'max_hops':min(4,max(1,int(p.get('max_hops',4)))),
         'psize':min(128,max(28,int(p.get('psize',64)))),
         'interval':min(2.0,max(1.0,float(p.get('interval',1.0))))}
