"""Deterministic concurrent-save schedule on synthetic SQLite and loopback."""
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from tests_service_settings.test_api import api

def test_check_never_sends_new_credentials_to_previous_saved_destination(api,monkeypatch):
    client,factory,_,_=api
    from app.models.config import AppConfig
    from app.services import external_services as external
    old_url='http://127.0.0.3:5244/old'
    new_url='http://127.0.0.4:5244/new'
    old={'browser_url':old_url,'upstream_url':old_url,'auth_mode':'token','token':'SYNTHETIC-OLD-TOKEN'}
    new={'browser_url':new_url,'upstream_url':new_url,'auth_mode':'token','token':'SYNTHETIC-NEW-TOKEN'}
    with factory() as db:
        db.add(AppConfig(key='external_drive_connection',value=json.dumps(old)));db.commit()
    actual_load=external.load
    reads=[]
    def scheduled_load(db,site):
        result=actual_load(db,site)
        reads.append({'endpoint':external.endpoint(result,''),'token':result.token})
        if len(reads)==1:
            # Interpose another completed settings write exactly after endpoint
            # authorization's load, before merge reloads the saved credential.
            with factory() as writer:
                writer.get(AppConfig,'external_drive_connection').value=json.dumps(new)
                writer.commit()
        return result
    monkeypatch.setattr(external,'load',scheduled_load)
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append({'path':self.path,'authorization':self.headers.get('Authorization')})
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"code":200}')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.3',5244),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        response=client.post('/service-settings/drive/check',json={'connection':{'service_url':old_url,'auth_mode':'token','token':None,'clear_token':False}})
    finally:
        server.shutdown();server.server_close();thread.join(3)
    evidence={'response_status':response.status_code,'response':response.json(),'saved_loads':reads,'requests_received_by_old_destination':requests}
    # Synthetic evidence is emitted only to the owning test log.
    print(json.dumps(evidence))
    assert not any(req['authorization']=='SYNTHETIC-NEW-TOKEN' for req in requests),'New destination credential was transmitted to the prior saved endpoint after authorization read raced with merge read'


def test_original_presentation_preserves_native_color_scheme():
    from app.services import builtin_injection as b
    html='<html><head><meta name="color-scheme" content="light dark"></head><body></body></html>'
    out=b.transform_html(html,'drive',appearance={'theme':'original','simplified':False})
    assert '<meta name="color-scheme" content="light dark">' in out
    assert '<meta name="color-scheme" content="normal">' not in out
