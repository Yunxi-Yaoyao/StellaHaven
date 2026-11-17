"""Opt-in owning-test HTTP sample/schema receipts; never changes a response."""
import hashlib
import json
import os
from pathlib import Path
from starlette.routing import compile_path
from jsonschema import Draft202012Validator
from app import api_response_contracts as contracts

ROWS=[*contracts._V17_REVIEW['operations']]
TARGETS=[(r['method'],compile_path(r['path'])[0],r['path']) for r in ROWS]
TARGETS += [(method,compile_path(path)[0],path) for method,path in [('PATCH','/auth/me'),('DELETE','/homebg/{entry_id}'),('PUT','/operations/backups/client-preferences')]]
SAMPLES={}
ORIGINALS=[]


def _validate(response,request):
    matches=[(method,path) for method,pattern,path in TARGETS if method==request.method and pattern.fullmatch(request.url.path)]
    if not matches:return response
    key,=matches
    declaration=contracts.DECLARATIONS[key]
    assert str(response.status_code) in declaration['responses'],(key,response.status_code,response.text[:200])
    contract=declaration['responses'][str(response.status_code)]
    if 'application/json' not in contract.get('content',{}):
        # Observe binary status/headers without consuming the caller's stream.
        headers={k:response.headers[k] for k in ['content-type','content-length','cache-control','content-disposition','x-content-type-options','x-file-sha256','x-artifact-sha256'] if k in response.headers}
        identity=(*key,response.status_code,hashlib.sha256(json.dumps(headers,sort_keys=True).encode()).hexdigest())
        SAMPLES[identity]=dict(method=key[0],path=key[1],status=response.status_code,binary=True,headers=headers,sha256=identity[-1])
        return response
    response.read()
    body=response.json();schema=contract['content']['application/json']['schema']
    Draft202012Validator(schema).validate(body)
    raw=json.dumps(body,sort_keys=True,ensure_ascii=True)
    identity=(*key,response.status_code,hashlib.sha256(raw.encode()).hexdigest())
    SAMPLES[identity]=dict(method=key[0],path=key[1],status=response.status_code,body=body,sha256=identity[-1])
    return response


def pytest_configure(config):
    import httpx
    from fastapi import FastAPI
    from fastapi.exceptions import RequestValidationError
    from app.validation_errors import validation_exception_handler
    original_init=FastAPI.__init__
    def init(app,*args,**kwargs):
        original_init(app,*args,**kwargs)
        # Owning apps omit main.py; install its actual validation handler.
        # No auth, dependency or response body is mocked or transformed here.
        app.add_exception_handler(RequestValidationError,validation_exception_handler)
    FastAPI.__init__=init
    ORIGINALS.append((FastAPI,'__init__',original_init))
    original=httpx.Client.send
    def send(client,request,*args,**kwargs):
        response=original(client,request,*args,**kwargs)
        # Never consume a streaming iterator used by the real file transport.
        return response if kwargs.get('stream') and response.headers.get('content-type','').startswith('application/json') else _validate(response,request)
    httpx.Client.send=send
    ORIGINALS.append((httpx.Client,'send',original))


def pytest_sessionfinish(session,exitstatus):
    for klass,name,original in ORIGINALS:setattr(klass,name,original)
    output=Path(os.environ['NAV_FILES_HTTP_EVIDENCE'])
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(dict(exit_code=int(exitstatus),samples=list(SAMPLES.values()),unique_samples=len(SAMPLES),identities=[list(k) for k in SAMPLES]),ensure_ascii=False,indent=2)+'\n')
