import sys,hashlib
from test_live_http import db
with db() as c,c.cursor() as q:
    key=int.from_bytes(hashlib.sha256(b'notes-reference-graph:v1').digest()[:8],'big',signed=True)
    q.execute('select pg_advisory_xact_lock(%s),pg_backend_pid()',(key,));print(q.fetchone()[1],flush=True)
    # Parent releases via pipe; bounded database lock test, no external activity.
    import select
    assert select.select([sys.stdin],[],[],10)[0], 'QA lock holder release deadline'
    sys.stdin.readline()
