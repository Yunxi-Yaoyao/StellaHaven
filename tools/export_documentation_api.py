#!/usr/bin/env python3
"""Export real route/schema metadata, with no lifespan, network or live configuration.

Runs a clean child from an empty cwd; only this checkout's modules are importable.
The child forbids socket connects, process launches and private data reads. It
never invokes a route or database dependency. No values are fetched from users.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def export(output):
    scratch=Path(os.environ.get('TMPDIR','/root/.hermes/cache/scratch'))
    with tempfile.TemporaryDirectory(prefix='stella-doc-schema-',dir=scratch) as cwd:
        env={'PATH':'/usr/bin:/bin','HOME':cwd,'TMPDIR':str(scratch),
             'PYTHONPATH':str(ROOT),'PYTHONDONTWRITEBYTECODE':'1',
             'POSTGRES_HOST':'127.0.0.1','POSTGRES_PORT':'9','POSTGRES_USER':'documentation_fixture',
             'POSTGRES_PASSWORD':'DOCUMENTATION_PLACEHOLDER','POSTGRES_DB':'documentation_fixture',
             'STELLA_SECRET_KEY':'documentation-placeholder-signing-key-not-production',
             'STELLA_BLOB_STORAGE':'postgres','STELLA_TRUSTED_ORIGINS':'http://testserver'}
        result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--child'],env=env,cwd=cwd,capture_output=True,text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        doc=json.loads(result.stdout)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(doc['coverage'],ensure_ascii=False))

def child():
    # Strict audit guard is installed before any Stella import.
    def guard(event,args):
        if event in {'socket.connect','socket.getaddrinfo','subprocess.Popen','os.system'}:
            raise RuntimeError('Documentation export forbids network/process execution: '+event)
        if event=='open' and isinstance(args[0],(str,bytes)):
            p=Path(os.fsdecode(args[0])).resolve()
            if p.name=='.env' or '/.credentials/' in str(p) or '/secrets/' in str(p):
                raise RuntimeError('Documentation export forbids private configuration reads')
            # Source-local data may not supply secrets either. Imports may mkdir
            # empty resource directories but cannot read a preexisting data file.
            if p.is_relative_to(ROOT/'data'):
                raise RuntimeError('Documentation export forbids all data reads/writes')
    sys.addaudithook(guard)
    # Native DBAPI clients (e.g. psycopg2) need not emit Python socket audit
    # events. Fail before any SQLAlchemy engine can call its DBAPI connector.
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    def forbid_database_connect(*args, **kwargs):
        raise RuntimeError('Documentation export forbids database connections')

    event.listen(Engine, 'do_connect', forbid_database_connect)
    from main import app
    from tests_isolated.test_api_openapi_contract import static_inventory
    # Use the real mounted FastAPI application's schema generator, exactly as
    # its OpenAPI endpoint does. An HTTP request also runs host-dispatch/access
    # middleware, which reads installation settings even without lifespan.
    # Schema export needs neither that request stack nor any database bootstrap.
    schema=app.openapi()
    records,_,excluded=static_inventory()
    expected={(m,p) for m,p,_,_ in records}
    methods={'get','post','put','patch','delete','head','options','trace'}
    actual={(m.upper(),p) for p,items in schema['paths'].items() for m in items if m in methods}
    assert expected==actual,{'missing':sorted(expected-actual),'extra':sorted(actual-expected)}
    operations=[{'method':m,'path':p,'endpoint':e} for m,p,e,_ in records]
    # WS is not part of OpenAPI. Record the actual mounted declaration separately.
    websockets=[]
    for file in sorted((ROOT/'app/routers').glob('*.py')):
        tree=ast.parse(file.read_text())
        for node in ast.walk(tree):
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
            for deco in node.decorator_list:
                if isinstance(deco,ast.Call) and isinstance(deco.func,ast.Attribute) and deco.func.attr=='websocket':
                    websockets.append({'path':ast.literal_eval(deco.args[0]),'source':str(file.relative_to(ROOT)),'handler':node.name})
    source_files=[ROOT/'main.py',*sorted((ROOT/'app').rglob('*.py')),*sorted((ROOT/'app').glob('api_response*.json'))]
    digest=hashlib.sha256()
    for file in source_files:
        digest.update(str(file.relative_to(ROOT)).encode()+b'\0'+file.read_bytes())
    print(json.dumps({'provenance':{'kind':'isolated-runtime-openapi','lifespan_started':False,'network_calls':0,'backend_source_sha256':digest.hexdigest()},
          'coverage':{'http_operations':len(actual),'missing':[],'extra':[],'websocket_declarations':len(websockets),'exclusions':excluded},
          'schema':schema,'operations':operations,'websockets':websockets},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--child',action='store_true')
    args=parser.parse_args()
    if args.child:child()
    elif args.output:export(args.output)
    else:parser.error('--output is required')
