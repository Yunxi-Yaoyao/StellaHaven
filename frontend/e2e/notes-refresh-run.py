"""Isolated Node 24 commands; receipts stay in this checkout."""
import os, sys, pathlib, subprocess, json, hashlib
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/Stella-API/remediation/notes-e2e-refresh-20261016'
OUT.mkdir(parents=True,exist_ok=True)
env=dict(os.environ)
removed=[]
for k in list(env):
    if k in ('NODE_ENV','VIRTUAL_ENV','UV_PROJECT_ENVIRONMENT') or any(x in k for x in ('HERMES','BROKER','BRIDGE','MCP')):
        removed.append(k);env.pop(k)
env['PATH']='/root/.local/share/fnm/node-versions/v24.21.0/installation/bin:'+env['PATH']
env['STELLA_NOTES_PRODUCT_BUILD']='1'
env['STELLA_TEST_URL']='http://127.0.0.1:15186'
name=sys.argv[1]
art=OUT/name;art.mkdir(exist_ok=True)
for key in ('NOTES_ARTIFACTS','STELLA_SERVICE_ARTIFACTS','NOTES_REFRESH_ARTIFACTS'):env[key]=str(art)
env['PLAYWRIGHT_JUNIT_OUTPUT_FILE']=str(OUT/(name+'.xml'))
env['PLAYWRIGHT_JSON_OUTPUT_NAME']=str(OUT/(name+'.json'))
(OUT/'environment.json').write_text(json.dumps({'removed_keys':removed,'node':subprocess.check_output(['node','--version'],env=env,text=True).strip(),'root':str(ROOT)},indent=2))
if name=='install':
    paths=subprocess.check_output(['git','ls-files','frontend/src','app','frontend/package.json','frontend/package-lock.json'],cwd=ROOT,text=True).splitlines()
    (OUT/'product-before.json').write_text(json.dumps({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},indent=2))
with (OUT/(name+'.log')).open('w') as log:
    result=subprocess.run(sys.argv[2:],cwd=ROOT/'frontend',env=env,stdout=log,stderr=subprocess.STDOUT)
print(json.dumps({'name':name,'exit_code':result.returncode,'log':str(OUT/(name+'.log'))}))
sys.exit(result.returncode)
