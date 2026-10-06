#!/usr/bin/env python3
"""Bounded unauthenticated probes, hashes/status only, no response/log text."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import re
import subprocess
from urllib.parse import urlsplit

MAX_BODY=1024*1024

def probe(label, base, path, resolve=None):
    import tempfile
    with tempfile.TemporaryFile() as body:
        args=['curl','--noproxy','*','--silent','--show-error','--max-time','20','--connect-timeout','5',
              '--max-filesize',str(MAX_BODY),'-H','Host: immich.xiya.live','-w','%{http_code} %{size_download} %{time_total}', '-o','/dev/fd/'+str(body.fileno())]
        if resolve: args += ['--resolve',resolve]
        r=subprocess.run(args+[base+path],pass_fds=(body.fileno(),),capture_output=True,timeout=25)
        body.seek(0);data=body.read(MAX_BODY+1)
    metrics=r.stdout.decode().split()
    return {'label':label,'path':path,'rc':r.returncode,'status':int(metrics[0]) if metrics else 0,
            'bytes':len(data),'seconds':float(metrics[-1]) if metrics else None,'sha256':hashlib.sha256(data).hexdigest()},data

def main():
    root,html=probe('local-root','http://127.0.0.1:12020','/')
    # Only public JS/CSS paths from real HTML, do not invent an asset ID.
    assets=list(dict.fromkeys(re.findall(r'["\'](/_app/[^"\'?#]+\.(?:js|css))["\']',html.decode(errors='replace'))))[:2]
    results=[root]
    for path in ['/api/server/ping']+assets:
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs=[pool.submit(probe,*args) for args in [
                ('local','http://127.0.0.1:12020',path),
                ('hk-entry','https://immich.xiya.live',path,'immich.xiya.live:443:149.104.15.68'),
                ('aws-frps','http://35.77.102.237:12020',path)]]
            results.extend(j.result()[0] for j in jobs)
    print(json.dumps({'timestamp':datetime.now(timezone.utc).isoformat(),'asset_count':len(assets),'probes':results},indent=2))
if __name__=='__main__':main()
