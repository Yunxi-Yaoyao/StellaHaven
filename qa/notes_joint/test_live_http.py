"""Real TCP HTTP + independently guarded owned PG; no app dependency overrides."""
import json,secrets,time,hashlib,os
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import httpx,psycopg2,pytest
R=Path('/root/.hermes/cache/scratch/notes-joint-6b01e8e');O=Path('/opt/hermes-workstation/docs/Stella-API/remediation');S=json.loads((R/'private.json').read_text());URL='http://127.0.0.1:'+str(S['http_port'])

def db():
    inside=os.stat('/proc/self/ns/net').st_ino==os.stat('/proc/'+str(S['pid'])+'/ns/net').st_ino
    c=psycopg2.connect(host='127.0.0.1',port=5432 if inside else S['port'],dbname=S['db'],user=S['user'],password=S['password'],connect_timeout=3)
    with c.cursor() as q:
        q.execute('select current_database(),current_user,host(inet_server_addr()),inet_server_port()');assert q.fetchone()==(S['db'],S['user'],'127.0.0.1' if inside else S['ip'],5432)
        q.execute('SET search_path TO "'+S['schema']+'"')
    c.commit();return c

def ok(r,code=200):
    assert r.status_code==code,(r.status_code,r.text[:700]);return r.json() if r.content else None

def client(cookies=None):return httpx.Client(base_url=URL,headers={'Origin':URL},cookies=cookies,timeout=20,trust_env=False)

def bootstrap():
    p=R/'auth-private.json'
    if p.exists():return json.loads(p.read_text())
    password=secrets.token_urlsafe(24);management=secrets.token_urlsafe(24)
    with client() as c:
        assert ok(c.get('/auth/status'))['initialized'] is False
        owner=ok(c.post('/auth/register',json={'username':'joint-synthetic','password':password}),201)
        ok(c.post('/auth/admin/setup',json={'user_password':password,'new_password':management}))
        ok(c.post('/auth/logout'));ok(c.post('/auth/login',json={'username':'joint-synthetic','password':password,'remember':True}))
        assert ok(c.post('/auth/admin/unlock',json={'password':management}))['elevated']
        elevated=dict(c.cookies)
    with client() as c:
        ok(c.post('/auth/login',json={'username':'joint-synthetic','password':password,'remember':True}));assert not ok(c.get('/auth/security'))['elevated'];ordinary=dict(c.cookies)
    data=dict(uid=owner['id'],elevated=elevated,ordinary=ordinary,url=URL)
    p.write_text(json.dumps(data));p.chmod(0o600)
    (O/'review-notes-joint-auth.json').write_text(json.dumps(dict(register=201,setup=200,login=200,unlock=200,ordinary_elevated=False,uid=owner['id'],dependency_overrides=False),indent=2));return data

@pytest.fixture
def ctx():
    auth=bootstrap()
    with client(auth['elevated']) as admin,client(auth['ordinary']) as c:
        w=ok(admin.post('/workspaces/',json={'user_id':auth['uid'],'name':'joint-'+uuid4().hex}),201)
        for seed in ok(c.get('/documents/',params={'workspace_id':w['id']})):
            ok(c.delete('/documents/'+seed['id']+'/permanent'),204)
        yield c,w['id'],auth

def doc(c,w,parent=None):return ok(c.post('/documents/',json={'workspace_id':w,'parent_id':parent,'title':'joint-'+uuid4().hex[:8],'file_path':'/qa/'+uuid4().hex,'content':'# Joint note\n\nOriginal body'}),201)
def preview(c,w,d=None,mode='permanent',cascade=True):return ok(c.post('/documents/delete-preview',json=dict(workspace_id=w,doc_id=d,mode=mode,cascade=cascade)))
def rows(w):
    with db() as c,c.cursor() as q:q.execute('select id,parent_id,deleted_at,content,draft_content from documents where workspace_id=%s order by id',(w,));return q.fetchall()
def delete(c,d,p):return c.delete('/documents/'+d+('/permanent' if p['mode']=='permanent' else ''),params={'cascade':str(p['cascade']).lower(),'scope_token':p['scope_token']})

def test_real_owner_origin_foreign_boundaries(ctx):
    c,w,a=ctx;d=doc(c,w);p=preview(c,w,d['id']);assert not ok(c.get('/auth/security'))['elevated']
    before=rows(w)
    for path in ['/documents/'+d['id'],'/documents/'+d['id']+'/permanent']:
        assert c.delete(path,headers={'Origin':'https://outside.invalid'},params={'scope_token':p['scope_token']}).status_code==403
    assert c.post('/documents/delete-preview',headers={'Origin':'https://outside.invalid'},json={'workspace_id':w,'doc_id':d['id'],'mode':'permanent'}).status_code==403
    assert rows(w)==before
    f,fw,fd=[str(uuid4()) for _ in range(3)]
    with db() as conn,conn.cursor() as q:
        q.execute("insert into users(id,username,display_name,password_hash,avatar_url,email,email_verified,avatar_history,home_bg,is_admin,is_active) values(%s,%s,'foreign','','','',false,'[]','',false,true)",(f,'foreign-'+f))
        q.execute("insert into workspaces(id,user_id,name) values(%s,%s,'foreign')",(fw,f))
        q.execute("insert into documents(id,workspace_id,title,file_path,content_hash,content,is_folder,visibility,is_pinned,is_favorite,status) values(%s,%s,'private','/foreign','h','retain',false,'private',false,false,'draft')",(fd,fw))
    assert c.post('/documents/delete-preview',json={'workspace_id':fw,'doc_id':fd,'mode':'permanent'}).status_code==404
    assert c.delete('/documents/'+fd+'/permanent',params={'scope_token':p['scope_token']}).status_code==404
    assert c.post('/documents/trash/empty',params={'workspace_id':fw,'scope_token':p['scope_token']}).status_code==404
    with db() as conn,conn.cursor() as q:q.execute('select content from documents where id=%s',(fd,));assert q.fetchone()==('retain',)
    ok(delete(c,d['id'],p),204);assert rows(w)==[]

def test_scope_protocol_expiry_mode_and_empty_replay(ctx):
    c,w,a=ctx;d=doc(c,w);child=doc(c,w,d['id']);ok(c.delete('/documents/'+child['id']),204)
    p=preview(c,w,d['id']);assert p['descendant_count']==1 and p['target_ids']==sorted([d['id'],child['id']])
    before=rows(w)
    wrong=dict(p,cascade=False);r=delete(c,d['id'],wrong);assert r.status_code==409 and r.json()['detail']['code']=='delete_scope_changed';assert rows(w)==before
    expired=dict(p,scope_token='v1.1.'+p['scope_token'].split('.')[2]);r=delete(c,d['id'],expired);assert r.status_code==409 and rows(w)==before
    p=preview(c,w,d['id'],cascade=False);ok(delete(c,d['id'],p),204);assert rows(w)[0][1] is None
    p=preview(c,w,mode='empty-trash');assert p['target_ids']==[child['id']]
    ok(c.post('/documents/trash/empty',params={'workspace_id':w,'scope_token':p['scope_token']}));assert rows(w)==[]
    new=doc(c,w);ok(c.delete('/documents/'+new['id']),204);before=rows(w)
    r=c.post('/documents/trash/empty',params={'workspace_id':w,'scope_token':p['scope_token']});assert r.status_code==409 and rows(w)==before

def test_http_waiter_rechecks_scope_after_actual_pg_lock(ctx):
    c,w,a=ctx;d=doc(c,w);p=preview(c,w,d['id']);new=str(uuid4());key=int.from_bytes(hashlib.sha256(b'notes-reference-graph:v1').digest()[:8],'big',signed=True)
    with db() as holder,holder.cursor() as h,ThreadPoolExecutor(1) as pool:
        h.execute('select pg_advisory_xact_lock(%s),pg_backend_pid()',(key,));blocker=h.fetchone()[1]
        fut=pool.submit(delete,c,d['id'],p)
        try:
            deadline=time.monotonic()+5;proof=None
            while time.monotonic()<deadline:
                with db() as observer,observer.cursor() as q:
                    q.execute("select pid,wait_event_type,query,pg_blocking_pids(pid) from pg_stat_activity where datname=current_database() and wait_event_type='Lock' and %s=ANY(pg_blocking_pids(pid))",(blocker,));v=q.fetchall()
                if v:proof=v;break
                time.sleep(.02)
            assert proof and all('pg_advisory_xact_lock' in x[2] for x in proof)
            h.execute("insert into documents(id,workspace_id,parent_id,title,file_path,content_hash,content,is_folder,visibility,is_pinned,is_favorite,status) values(%s,%s,%s,'late-child','/late','h','keep',false,'private',false,false,'draft')",(new,w,d['id']))
        finally:holder.commit()
        r=fut.result(10)
    assert r.status_code==409 and r.json()['detail']['code']=='delete_scope_changed';assert len(rows(w))==2
    (O/'review-notes-joint-http-lock.json').write_text(json.dumps(dict(blocker=blocker,waiters=proof,response=r.json(),rows_retained=2),indent=2))

def test_real_http_f9_lock_wait_rechecks_committed_missing_target(ctx):
    c,w,a=ctx;d=doc(c,w);tag=ok(c.post('/tags/',json={'name':'joint-race-'+uuid4().hex,'user_id':a['uid']}),201)
    pair={'doc_id':d['id'],'tag_id':tag['id']};key=int.from_bytes(hashlib.sha256(b'notes-reference-graph:v1').digest()[:8],'big',signed=True)
    with db() as holder,holder.cursor() as h,ThreadPoolExecutor(1) as pool:
        h.execute('select pg_advisory_xact_lock(%s),pg_backend_pid()',(key,));blocker=h.fetchone()[1]
        fut=pool.submit(c.post,'/doc-tags/',json=pair)
        try:
            deadline=time.monotonic()+5;proof=None
            while time.monotonic()<deadline:
                with db() as observer,observer.cursor() as q:
                    q.execute("select pid,wait_event_type,query,pg_blocking_pids(pid) from pg_stat_activity where datname=current_database() and wait_event_type='Lock' and %s=ANY(pg_blocking_pids(pid))",(blocker,));found=q.fetchall()
                if found:proof=found;break
                time.sleep(.02)
            assert proof and all('pg_advisory_xact_lock' in row[2] for row in proof)
            h.execute('DELETE FROM documents WHERE id=%s',(d['id'],));h.execute('DELETE FROM tags WHERE id=%s',(tag['id'],))
        finally:holder.commit()
        response=fut.result(10)
    assert response.status_code==404
    with db() as conn,conn.cursor() as q:
        q.execute('select count(*) from doc_tags where doc_id=%s or tag_id=%s',(d['id'],tag['id']));assert q.fetchone()[0]==0
    (O/'review-notes-joint-http-f9-lock.json').write_text(json.dumps(dict(blocker=blocker,waiters=proof,response=response.status_code,orphan_relations=0,deletion='guarded holder SQL deletes unreferenced synthetic rows; original service purge races separately covered by unchanged PG suite'),indent=2))


def test_real_http_f8_rollback_before_retry(ctx):
    c,w,a=ctx;d=doc(c,w);tag=ok(c.post('/tags/',json={'name':'joint-'+uuid4().hex,'user_id':a['uid']}),201)
    pair={'doc_id':d['id'],'tag_id':tag['id']};ok(c.post('/doc-tags/',json=pair),201)
    (R/'fault.json').write_text('{"orphan_failure":true}')
    try:assert c.delete('/doc-tags/',params=pair).status_code==500
    finally:(R/'fault.json').unlink()
    def snapshot():
        with db() as conn,conn.cursor() as q:
            q.execute('select count(*) from doc_tags where doc_id=%s and tag_id=%s',(d['id'],tag['id']));link=q.fetchone()[0]
            q.execute('select count(*) from tags where id=%s',(tag['id'],));return link,q.fetchone()[0]
    assert snapshot()==(1,1)
    with client(a['ordinary']) as retry:
        ok(retry.delete('/doc-tags/',params=pair),204)
    assert snapshot()==(0,0)
    assert c.delete('/doc-tags/',params=pair).status_code==404

def test_metadata_draft_and_exact_consumption_with_newer_slot(ctx):
    c,w,a=ctx;d=doc(c,w)
    def setdraft(body):
        with db() as conn,conn.cursor() as q:
            q.execute('update documents set draft_content=%s,draft_updated_at=%s,draft_device=%s where id=%s returning draft_updated_at',(body,datetime.now(),'other-device',d['id']));return q.fetchone()[0].isoformat()
    stamp=setdraft('adopt me');ok(c.put('/documents/'+d['id'],json={'updated_at':d['updated_at'],'title':'metadata only'}))
    assert ok(c.get('/documents/'+d['id']+'/draft'))['content']=='adopt me'
    fresh=ok(c.get('/documents/'+d['id']));receipt={'draft_updated_at':stamp,'content_hash':hashlib.sha256(b'adopt me').hexdigest()}
    saved=ok(c.put('/documents/'+d['id'],json={'updated_at':fresh['updated_at'],'content':'adopt me','consumed_draft':receipt}))
    assert c.get('/documents/'+d['id']+'/draft').status_code==404
    setdraft('newer other device');ok(c.put('/documents/'+d['id'],json={'updated_at':saved['updated_at'],'content':'accepted old','consumed_draft':receipt}))
    assert ok(c.get('/documents/'+d['id']+'/draft'))['content']=='newer other device'

if __name__=='__main__':bootstrap();print('Real register/setup/login/unlock completed; ordinary browser cookies stored privately')
