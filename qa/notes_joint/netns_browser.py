"""Run Chromium and its exact HTTP/PG harness inside owned egress-denied netns."""
import os,sys,json,subprocess,shutil
from pathlib import Path
from control import ROOT,REPO,OUT,STATE,PY,env,inspect,cmd,save
s=json.loads(STATE.read_text());m=inspect(s['id']);assert m['Config']['Labels']['stella.audit']==s['label'] and m['Id']==s['id']
pre=['nsenter','-t',str(s['pid']),'-n']
if sys.argv[1]=='relay':
    for port in [18080,s['http_port']]:cmd(pre+['iptables','-I','OUTPUT','1','-o','lo','-p','tcp','--dport',str(port),'-j','ACCEPT'])
    save('browser-netns',dict(id=s['id'],pid=s['pid'],bindings=m['NetworkSettings']['Ports'],rules=cmd(pre+['iptables','-S','OUTPUT']),browser='Chromium inside same owned network namespace; external egress DROP',relay='raw TCP only: loopback random port to real Uvicorn 18080, no HTTP rewriting or Vite proxy'))
    os.execvpe('nsenter',pre+[PY,str(REPO/'qa/notes_joint/relay.py')],env())
elif sys.argv[1]=='run':
    # Health and denied egress probes executed before the browser suite.
    code="import socket,httpx; r=httpx.get('http://127.0.0.1:"+str(s['http_port'])+"/auth/status',trust_env=False);assert r.status_code==200,r.status_code;s=socket.socket();s.settimeout(.2)\ntry:s.connect(('203.0.113.1',443))\nexcept OSError: print('external egress blocked; app HTTP ready')\nelse:raise AssertionError('egress allowed')"
    print(cmd(pre+[PY,'-c',code]))
    if not (OUT/'review-notes-joint-browser/host-final-traces').exists():
        for x in ['log','xml']:shutil.copy2(OUT/('review-notes-joint-browser.'+x),OUT/('review-notes-joint-browser-host-final.'+x))
        shutil.copytree(OUT/'review-notes-joint-browser/traces',OUT/'review-notes-joint-browser/host-final-traces')
    for f in ['joint.spec.ts','joint.config.ts']:shutil.copy2(REPO/'qa/notes_joint'/f,ROOT/'application/frontend/e2e'/f)
    with (OUT/'review-notes-joint-browser.log').open('w') as f:r=subprocess.run(pre+[shutil.which('node'),'node_modules/@playwright/test/cli.js','test','--config','e2e/joint.config.ts'],cwd=ROOT/'application/frontend',env=env(),stdout=f,stderr=subprocess.STDOUT,timeout=300)
    print('namespace browser exit',r.returncode);sys.exit(r.returncode)
