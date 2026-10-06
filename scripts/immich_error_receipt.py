#!/usr/bin/env python3
"""Print only fixed event categories/timestamps, never raw query-bearing logs."""
import collections
from datetime import datetime, timezone
import json
import pathlib
import re
import subprocess

def main():
    f=pathlib.Path('/var/log/nginx/error.log')
    errors=[]
    if f.exists():
        with f.open('rb') as h:
            h.seek(max(0,f.stat().st_size-262144))
            errors=[x for x in h.read().decode(errors='replace').splitlines() if 'immich.xiya.live' in x]
    categories=['Connection reset by peer','upstream timed out','connect() failed','upstream prematurely closed connection','upstream sent invalid','too big header']
    receipt={'timestamp':datetime.now(timezone.utc).isoformat(), 'timezone':str(datetime.now().astimezone().tzinfo),
        'errors':{'count':len(errors),'first':errors[0][:19] if errors else None,'last':errors[-1][:19] if errors else None,
                  'categories':{c:sum(c in x for x in errors) for c in categories},
                  'static_immutable':sum('/_app/immutable/' in x for x in errors)}}
    logs={}
    for unit in ['frps','frpc@hk']:
        args=['journalctl','-u',unit,'--since','2026-10-06 01:31:30','--until','2026-10-06 01:33:30','--no-pager','-o','json']
        r=subprocess.run(args,capture_output=True,text=True,timeout=30)
        counter=collections.Counter(); stamps=[]
        fixed=['write timeout','i/o deadline','i/o timeout','login to server success','client exit success','heartbeat timeout',
               'listener is closed','use of closed network connection','get work connection','connection reset','connection closed',
               'new proxy','user connection','start proxy success','control writer','control reader','EOF','immich']
        total=0
        for line in r.stdout.splitlines():
            try: row=json.loads(line)
            except ValueError: continue
            message=row.get('MESSAGE','');total+=1
            if ('immich' not in message and not any(x in message for x in ['login','heartbeat','control','client exit','write timeout','EOF','i/o'])):continue
            for marker in fixed:
                if marker.lower() in message.lower():counter[marker]+=1
            if len(stamps)<20 and ('error' in message.lower() or 'fail' in message.lower() or 'timeout' in message.lower() or 'EOF' in message):
                stamps.append(datetime.fromtimestamp(int(row['__REALTIME_TIMESTAMP'])/1000000,timezone.utc).isoformat())
        logs[unit]={'rc':r.returncode,'total_lines':total,'categories':dict(counter),'error_timestamps':stamps}
    receipt['correlation_window']=logs
    print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
