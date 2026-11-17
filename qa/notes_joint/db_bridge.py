"""Owned DB-only fixture writes/readbacks, never business response simulation."""
import json,sys
from datetime import datetime
from test_live_http import db
v=json.loads(sys.stdin.read());op=v['op'];did=v['id']
with db() as c,c.cursor() as q:
    if op=='draft':
        q.execute('update documents set draft_content=%s,draft_updated_at=%s,draft_device=%s where id=%s returning draft_updated_at',(v['content'],datetime.now(),'joint-other-device',did));print(json.dumps({'stamp':q.fetchone()[0].isoformat()}))
    elif op=='parent':
        q.execute('update documents set parent_id=%s where id=%s',(v.get('content'),did));print('{}')
    elif op=='trash':
        q.execute('update documents set deleted_at=%s where id=%s',(datetime.now(),did));print('{}')
    elif op=='read':
        q.execute('select content,draft_content,draft_updated_at,deleted_at,parent_id from documents where id=%s',(did,));row=q.fetchone();print(json.dumps(None if row is None else dict(zip(['content','draft_content','draft_updated_at','deleted_at','parent_id'],row)),default=str))
    else:raise AssertionError('unknown operation')
