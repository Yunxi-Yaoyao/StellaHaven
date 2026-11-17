"""Redact disposable session cookies from our own evidence, preserving assertions."""
import json,zipfile,io
from pathlib import Path
R=Path('/root/.hermes/cache/scratch/notes-joint-6b01e8e');O=Path('/opt/hermes-workstation/docs/Stella-API/remediation');p=R/'auth-private.json';a=json.loads(p.read_text());values={str(v).encode() for k in ['ordinary','elevated'] for v in a[k].values()};changed=[]
def redact(b):
    for value in values:b=b.replace(value,b'<disposable-session-redacted>')
    return b
paths=[]
for top in O.glob('review-notes-joint*'):
    paths.extend([top] if top.is_file() else [x for x in top.rglob('*') if x.is_file()])
for f in paths:
    if f.suffix=='.zip':
        data=f.read_bytes();src=zipfile.ZipFile(io.BytesIO(data));out=io.BytesIO();count=0
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                old=src.read(item.filename);new=redact(old);count+=old!=new;dst.writestr(item,new)
        if count:f.write_bytes(out.getvalue());changed.append(str(f))
    elif f.suffix in {'.log','.json','.xml','.md','.txt'}:
        old=f.read_bytes();new=redact(old)
        if new!=old:f.write_bytes(new);changed.append(str(f))
p.unlink()
assert not p.exists() and not (R/'private.json').exists()
(O/'review-notes-joint-redaction.json').write_text(json.dumps(dict(changed_files=changed,scope='Only exact disposable auth cookie bytes; business responses, statuses, assertions and screenshots unchanged',private_cookie_state_absent=True,private_db_state_absent=True),indent=2))
print('Disposable cookies redacted; private cookie and DB state absent')
