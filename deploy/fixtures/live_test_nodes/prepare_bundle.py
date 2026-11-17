"""Build the token-free fixture bundle from real candidate code/local binaries."""
from pathlib import Path
import hashlib,json,re,shutil,subprocess
ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]
BUNDLE=ROOT/'bundle'

def prepare():
    (BUNDLE/'runtime/lib').mkdir(parents=True,exist_ok=True)
    (BUNDLE/'bin').mkdir(exist_ok=True)
    provenance={}
    for name in ('mtr','mtr-packet','ping'):
        binary=shutil.which(name)
        if not binary:raise RuntimeError('required genuine local binary missing: '+name)
        source=Path(binary);shutil.copy2(source,BUNDLE/'runtime'/name)
        provenance[str(source)]=hashlib.sha256(source.read_bytes()).hexdigest()
        output=subprocess.check_output(['ldd',str(source)],text=True)
        for library in re.findall(r'(?:=>\s*)?(/[^\s]+)',output):
            path=Path(library)
            if path.is_file():shutil.copy2(path,BUNDLE/'runtime/lib'/path.name)
        wrapper=BUNDLE/'bin'/name
        wrapper.write_text('#!/bin/sh\nexec /fixture/runtime/lib/ld-linux-x86-64.so.2 --library-path /fixture/runtime/lib /fixture/runtime/'+name+' "$@"\n')
        wrapper.chmod(0o755)
    for name in ('worker.py','fixture_policy.py'):shutil.copy2(ROOT/name,BUNDLE/name)
    shutil.copy2(REPO/'agent/stella_agent.py',BUNDLE/'stella_agent.py')
    provenance['candidate_agent_sha256']=hashlib.sha256((BUNDLE/'stella_agent.py').read_bytes()).hexdigest()
    (ROOT/'binary-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    print(json.dumps(provenance,indent=2))
if __name__=='__main__':prepare()
