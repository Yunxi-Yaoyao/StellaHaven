"""Real loopback TLS fixtures; process-local guard permits owned ports only."""
from test_agent_channels import agent,obj,policy
import threading,ssl,json
import pytest

@pytest.fixture
def tls_pair(tmp_path, monkeypatch):
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import hashes,serialization
    from datetime import datetime,timezone,timedelta
    import ipaddress,socket
    original=socket.socket.connect; ports=set()
    def connect(sock,address):
        assert address[0] in ('127.0.0.1','::1') and address[1] in ports, 'non-fixture network blocked'
        return original(sock,address)
    monkeypatch.setattr(socket.socket,'connect',connect)
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'owned fixture CA')])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1))
          .not_valid_after(now+timedelta(days=1))
          .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
          .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
          .sign(key,hashes.SHA256()))
    ca=tmp_path/'ca.pem'; ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private=tmp_path/'key.pem';private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,serialization.NoEncryption()))
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(ca,private)
    servers=[];threads=[];seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            seen.append((self.server.origin,self.path,self.headers.get('Authorization')))
            if self.server.redirect:
                self.send_response(302);self.send_header('Location',servers[1].origin+'/stolen');self.end_headers();return
            if self.server.fail:
                self.send_response(503);self.end_headers();return
            body=json.dumps(dict(center_id=self.server.pin,node_id=7,token_binding='c'*64,origin=self.server.origin)).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers()
            if self.server.trickle:
                import time
                try:
                    for byte in body:self.wfile.write(bytes([byte]));self.wfile.flush();time.sleep(.02)
                except (BrokenPipeError,ConnectionResetError,ssl.SSLError):pass
            else:self.wfile.write(body)
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.append((self.server.origin,self.path,body))
            if self.server.hold is not None:self.server.hold.wait(3)
            if self.server.fail:
                self.connection.shutdown(2);self.connection.close();return
            raw=b'{"ok":true}'
            self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    for _ in range(2):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        assert server.server_port not in (25436,24532,25451)
        ports.add(server.server_port);server.origin='https://127.0.0.1:'+str(server.server_port)
        server.fail=False;server.redirect=False;server.pin='a'*64
        server.hold=None
        server.trickle=False
        server.socket=context.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        servers.append(server);threads.append(thread)
    try:yield servers,seen,ssl.create_default_context(cafile=str(ca))
    finally:
        for s in servers:s.shutdown();s.server_close()
        for t in threads:t.join(2)

@pytest.mark.parametrize('stdlib',[False,True])
@pytest.mark.parametrize('wrong_identity_first',[False,True])
def test_auto_current_recovery_confirms_and_caches_without_switch_or_dwell(tls_pair,tmp_path,monkeypatch,stdlib,wrong_identity_first):
    servers,seen,context=tls_pair
    if stdlib:monkeypatch.setattr(agent,'httpx',None)
    a=obj(servers[0].origin);a._ssl_context=context
    a._channel_cache_path=lambda:tmp_path/'recovered.json'
    cfg=policy([s.origin for s in servers],'auto')
    servers[0].fail=True
    a._channel_apply(cfg)
    assert a._channel_state=='failed' and a._channel_error=='probe_failed'
    switched=a._channel_switched_at
    servers[0].fail=False;servers[1].fail=True
    # A valid TLS response with the wrong center must not clear failure.
    if wrong_identity_first:
        servers[0].pin='d'*64
        a._channel_tick(now=switched+1)
        assert a._channel_state=='failed' and a._channel_error=='probe_failed'
        servers[0].pin='a'*64
    a._channel_tick(now=max(switched+1,a._channel_next_probe+1))
    assert a._channel_state=='applied' and a._channel_error is None
    assert a.url==servers[0].origin and a._channel_switched_at==switched
    restored=obj(servers[0].origin);restored._channel_cache_path=a._channel_cache_path
    restored._channel_load()
    assert restored._channel_policy==cfg and restored._channel_state=='applied'
    assert restored._channel_error is None and restored.url==servers[0].origin
    receipt=a._channel_receipt()
    assert receipt['state']=='applied' and receipt['error'] is None
    assert all(p=='/agent/entry-probe' for _,p,_ in seen)


@pytest.mark.parametrize('stdlib',[False,True])
def test_real_tls_probe_private_ca_pin_and_no_redirect_token(tls_pair,stdlib,monkeypatch):
    servers,seen,context=tls_pair
    if stdlib:monkeypatch.setattr(agent,'httpx',None)
    a=obj(servers[0].origin);a._ssl_context=context
    cfg=policy([s.origin for s in servers],'auto')
    sample=a._channel_probe(servers[0].origin,cfg)
    assert sample['ok'] and sample['duration_ms']>0
    assert seen[-1][2]=='Bearer fixture-channel-token'
    print('real TLS readiness:',sample)
    servers[0].pin='d'*64
    assert not a._channel_probe(servers[0].origin,cfg)['ok']
    servers[0].redirect=True
    count=len(seen)
    assert not a._channel_probe(servers[0].origin,cfg)['ok']
    assert len(seen)==count+1 and not any(p=='/stolen' for _,p,_ in seen)
    a._ssl_context=ssl.create_default_context()
    assert not a._channel_probe(servers[1].origin,cfg)['ok']

def test_cached_auto_can_switch_with_dead_config_and_one_unknown_post(tls_pair,tmp_path):
    from collections import deque
    servers,seen,context=tls_pair
    a=obj(servers[0].origin);a._ssl_context=context
    a._channel_cache_path=lambda:tmp_path/'approved-cache.json'
    cfg=policy([s.origin for s in servers],'auto')
    a._channel_apply(cfg)
    assert a._channel_policy==cfg
    a.queue=deque();a.monitors_version=0
    a._check_components=lambda:{};a._os_info=lambda:{};a._storage_info=lambda:[]
    servers[0].fail=True
    a.report([],[])
    assert len([r for r in seen if r[1]=='/agent/report'])==1 and len(a.queue)==1
    a.report([],[])
    assert len([r for r in seen if r[1]=='/agent/report'])==1 and len(a.queue)==2
    restored=obj(servers[0].origin);restored._ssl_context=context
    restored._channel_cache_path=a._channel_cache_path;restored._channel_load()
    assert restored._channel_policy==cfg
    base=restored._channel_switched_at
    for i in range(3):restored._channel_tick(now=base+61+i*31)
    assert restored.url==servers[1].origin
    restored._post('/agent/job-result',json_body={'owned':True})
    assert seen[-1][0]==servers[1].origin
    a._channel_cache_path().write_text('{"body":"tampered","mac":"bad"}')
    other=obj(servers[0].origin);other._channel_cache_path=a._channel_cache_path;other._channel_load()
    assert other._channel_policy is None and other.url==servers[0].origin


def test_fixed_is_not_automatic_and_legacy_origin_stays_until_validated(tls_pair,tmp_path):
    servers,seen,context=tls_pair
    a=obj(servers[1].origin);a._ssl_context=context;a._channel_cache_path=lambda:tmp_path/'fixed.json'
    cfg=policy([servers[0].origin])
    servers[0].fail=True
    a._channel_apply(cfg)
    assert a.url==servers[1].origin and a._channel_state=='failed'
    assert a._channel_receipt() is None  # legacy URL is not a newly confirmed target
    a._channel_tick(now=a._channel_switched_at+61)
    assert a.url==servers[1].origin
    servers[0].fail=False
    a._channel_tick(now=a._channel_next_probe+1)
    assert a.url==servers[0].origin
    count=len(seen)
    a._channel_tick(now=a._channel_next_probe+31)
    assert len(seen)==count  # applied default/fixed has no candidate measurements


def test_inflight_report_origin_receipt_is_atomically_fenced_from_switch(tls_pair,tmp_path):
    servers,seen,context=tls_pair
    a=obj(servers[0].origin);a._ssl_context=context;a._channel_cache_path=lambda:tmp_path/'fence.json'
    a._channel_apply(policy([s.origin for s in servers],'auto'))
    hold=threading.Event();servers[0].hold=hold
    error=[]
    def send():
        try:a._post('/agent/report',json_body={'metrics':[]})
        except Exception as exc:error.append(str(exc))
    report=threading.Thread(target=send);report.start()
    import time
    deadline=time.monotonic()+2
    while not any(p=='/agent/report' for _,p,_ in seen) and time.monotonic()<deadline:time.sleep(.01)
    assert report.is_alive()
    cfg=policy([s.origin for s in servers],'fixed',revision=2);cfg['selected_entry_id']='private'
    switch=threading.Thread(target=lambda:a._channel_apply(cfg));switch.start()
    try:
        assert a.url==servers[0].origin
        recorded=next(body for _,p,body in seen if p=='/agent/report')
        assert recorded['channel_receipt']['origin']==servers[0].origin
    finally:hold.set();report.join(3);switch.join(3)
    assert not report.is_alive() and not switch.is_alive() and not error
    assert a.url==servers[1].origin
    a._get('/agent/tasks')
    assert seen[-1][0]==servers[1].origin
    assert a._last_report_transaction['entry_id']=='public'
    assert a._last_report_transaction['duration_ms']>0
    assert a._last_report_transaction['sampled_at']


def test_background_readiness_does_not_block_report_sampling(tls_pair,tmp_path):
    servers,seen,context=tls_pair
    a=obj(servers[0].origin);a._ssl_context=context;a._channel_cache_path=lambda:tmp_path/'background.json'
    a._channel_apply(policy([s.origin for s in servers],'auto'))
    probing,release,completed=threading.Event(),threading.Event(),threading.Event()
    def probe(origin,cfg):
        probing.set();release.wait(3)
        return dict(ok=True,duration_ms=10,sampled_at='fixture')
    a._channel_probe=probe
    background=threading.Thread(target=a._channel_tick);background.start()
    assert probing.wait(1)
    def report():a._post('/agent/report',json_body={'metrics':[]});completed.set()
    foreground=threading.Thread(target=report);foreground.start()
    try:assert completed.wait(.5),'background readiness held the heartbeat origin lock'
    finally:release.set();background.join(3);foreground.join(3)


def test_failed_new_default_does_not_revoke_installed_tls_config_source(tls_pair,tmp_path):
    servers,seen,context=tls_pair
    a=obj(servers[1].origin);a._ssl_context=context;a._channel_cache_path=lambda:tmp_path/'legacy-config.json'
    servers[0].fail=True
    a._channel_apply(policy([servers[0].origin]))
    assert a.url==servers[1].origin and a._channel_state=='failed'
    fixed=policy([s.origin for s in servers],'fixed',revision=2);fixed['selected_entry_id']='private'
    a._channel_apply(fixed)
    assert a._channel_policy==fixed and a._channel_state=='applied'


@pytest.mark.parametrize('stdlib',[False,True])
def test_trickling_readiness_is_bounded_by_total_body_budget(tls_pair,stdlib,monkeypatch):
    servers,seen,context=tls_pair
    if stdlib:monkeypatch.setattr(agent,'httpx',None)
    a=obj(servers[0].origin);a._ssl_context=context
    servers[0].trickle=True
    sample=a._channel_probe(servers[0].origin,policy([s.origin for s in servers],'auto'))
    assert not sample['ok'] and sample['duration_ms']<5500,sample


def test_resolver_stall_has_one_outstanding_probe_and_bounded_admission(tls_pair):
    servers,seen,context=tls_pair
    a=obj(servers[0].origin);a._ssl_context=context
    release=threading.Event();calls=[]
    def blocked(origin,cfg):
        calls.append(origin);release.wait(6)
        return dict(ok=True,duration_ms=1,sampled_at='fixture')
    a._channel_probe_transaction=blocked
    try:
        first=a._channel_probe(servers[0].origin,policy([s.origin for s in servers],'auto'))
        assert not first['ok'] and first['duration_ms']<5000
        second=a._channel_probe(servers[1].origin,policy([s.origin for s in servers],'auto'))
        assert not second['ok'] and second['duration_ms']<500
        assert calls==[servers[0].origin]
    finally:release.set()
