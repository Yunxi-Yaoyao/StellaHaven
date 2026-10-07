"""Opt-in parent-owned disposable PG, strict receipt + identity guards.

No prod config or implicit DB target. Preserve the legacy fixtures' default
Docker guards; this alternative owns only a random schema and bounded relay.
"""
import json
import os
import select
import socket
import socketserver
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL


@contextmanager
def guarded_engine():
    assert not any(k in os.environ for k in ('PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGUSER','PGPASSWORD','PGSERVICE','PGSERVICEFILE','PGOPTIONS'))
    receipt=json.loads(Path(os.environ['STELLA_SERVICE_TEST_PG_RECEIPT']).read_text())
    assert receipt['fixture_only'] is True and receipt['production_data_copied'] is False and receipt['tmpfs_data'] is True
    assert receipt['container'].startswith('stella-service-settings-test-pg-')
    assert receipt['loopback_port']==37632 and receipt['identity']=='stella_test|stalla|5432'
    info=json.loads(subprocess.check_output(['docker','inspect',receipt['container']]))[0]
    assert info['Id']==receipt['container_id'] and info['State']['Running']
    assert info['HostConfig']['PortBindings']['5432/tcp']==[{'HostIp':'127.0.0.1','HostPort':'37632'}]
    assert '/var/lib/postgresql' in info['HostConfig']['Tmpfs']
    ip=info['NetworkSettings']['Networks'][receipt['network']]['IPAddress']
    import ipaddress
    assert ipaddress.ip_address(ip).is_private
    values={line.partition('=')[0]:line.partition('=')[2] for line in Path(os.environ['STELLA_SERVICE_TEST_PG_ENV']).read_text().splitlines() if '=' in line}
    assert (values['POSTGRES_USER'],values['POSTGRES_DB'])==('stalla','stella_test')
    relay=None;thread=None;engine=None
    # Internal Docker networks may record PortBindings without actually exposing
    # the port. Relay solely to the inspected disposable container, never another
    # DB/service. Binding conflicts fail closed rather than finding a new target.
    if not info['NetworkSettings']['Ports'].get('5432/tcp'):
        class Relay(socketserver.BaseRequestHandler):
            def handle(self):
                with socket.create_connection((ip,5432),timeout=3) as target:
                    self.request.settimeout(5);target.settimeout(5)
                    sockets=[self.request,target]
                    while True:
                        ready,_,_=select.select(sockets,[],[],5)
                        if not ready: continue
                        for stream in ready:
                            data=stream.recv(65536)
                            if not data:return
                            (target if stream is self.request else self.request).sendall(data)
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address=True
            daemon_threads=True
            block_on_close=True
        relay=Server(('127.0.0.1',37632),Relay)
        thread=threading.Thread(target=relay.serve_forever,daemon=True);thread.start()
    schema='service_settings_'+uuid4().hex
    url=URL.create('postgresql+psycopg2',username='stalla',password=values['POSTGRES_PASSWORD'],host='127.0.0.1',port=37632,database='stella_test')
    assert (url.host,url.port,url.username,url.database,url.query)==('127.0.0.1',37632,'stalla','stella_test',{})
    try:
        engine=create_engine(url,connect_args={'connect_timeout':3,'options':f'-c search_path={schema} -c stella.test_isolation=service-settings-only'})
        def identity(dbapi):
            with dbapi.cursor() as cur:
                cur.execute("select current_database(),current_user,host(inet_server_addr()),inet_server_port(),current_setting('stella.test_isolation')")
                assert cur.fetchone()==('stella_test','stalla',ip,5432,'service-settings-only')
            dbapi.rollback()
        @event.listens_for(engine,'checkout')
        def guard(dbapi,record,proxy):identity(dbapi)
        with engine.begin() as conn:
            assert conn.execute(text('select current_database(),current_user')).one()==('stella_test','stalla')
            conn.execute(text('CREATE SCHEMA '+schema))
        try:
            yield engine
        finally:
            with engine.begin() as conn:
                assert conn.execute(text('select current_database(),current_user')).one()==('stella_test','stalla')
                conn.execute(text('DROP SCHEMA '+schema+' CASCADE'))
            with engine.connect() as conn:
                assert conn.execute(text('select count(*) from pg_namespace where nspname=:name'),{'name':schema}).scalar_one()==0
            print('PG_SCHEMA_CLEANUP='+schema)
    finally:
        if engine:engine.dispose()
        if relay:relay.shutdown();relay.server_close()
        if thread:thread.join(5);assert not thread.is_alive()
