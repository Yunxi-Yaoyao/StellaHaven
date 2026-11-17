#!/usr/bin/env python3
"""Export candidate evidence from REAL routers/DTOs. Never approve old hashes."""
import ast,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT)]
from fastapi import FastAPI
from fastapi.routing import APIRoute
from app.routers.monitor import node_router,agent_router
from app.schemas import channel
from app.schemas.monitor import AgentConfig,AgentReport
OUT=ROOT/'docs/Stella-监控第五轮-20261020/channels'
OUT.mkdir(parents=True,exist_ok=True)
app=FastAPI();app.include_router(node_router);app.include_router(agent_router)
# Owned routers are enumerated directly: lazy includes must not erase routes.
routes=[r for router in (node_router,agent_router) for r in router.routes if isinstance(r,APIRoute) and r.path in ('/nodes/report-channels','/agent/entry-probe','/agent/config','/agent/report')]
operations=[]
for r in routes:
    for method in sorted(r.methods):
        operations.append(dict(method=method,path=r.path,endpoint=r.endpoint.__module__+'.'+r.endpoint.__name__,
            response_model=getattr(r.response_model,'__name__',None),
            request_model=getattr(r.body_field.field_info.annotation,'__name__',str(r.body_field.field_info.annotation)) if r.body_field else None,
            dependencies=[d.call.__module__+'.'+d.call.__name__ for d in r.dependant.dependencies]))
sources={}
for name in ('agent/stella_agent.py','app/routers/monitor.py','app/schemas/monitor.py','app/schemas/channel.py','app/services/agent_channels.py'):
    raw=(ROOT/name).read_bytes(); tree=ast.parse(raw)
    sources[name]={'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),'symbols':{}}
    for n in ast.walk(tree):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            if name=='agent/stella_agent.py' and not (n.name.startswith('_channel_') or n.name in ('Agent','_get','_post','_post_report_transaction','report','refresh_config')):continue
            sources[name]['symbols'][n.name]={'start':n.lineno,'end':n.end_lineno,
                'ast_sha256':hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest()}
models={m.__name__:m.model_json_schema() for m in (channel.ChannelWrite,channel.ChannelRead,channel.ChannelConfig,channel.ChannelReceipt,channel.ChannelProbe,channel.ChannelReportAck,AgentConfig,AgentReport)}
(OUT/'CONTRACT-REQUEST.json').write_text(json.dumps(dict(status='candidate-awaiting-parent-independent-review',operations=operations,models=models,sources=sources,
    runtime_errors={'read_report_channels':[401,503],'write_report_channels':[401,403,409,422,503],'agent_entry_probe':[401,403,503],'agent_report_receipt':[401,409,422,503]},
    important='Derived from the owned actual routers/classes/AST. Existing approved hashes and inventories untouched. Same-center deployment routes/public signing identity/DB alignment require parent release gate.'),ensure_ascii=False,indent=2)+'\n')
# Capture exact native runtime OpenAPI; the parent adds reviewed global overlays.
(OUT/'candidate-openapi.json').write_text(json.dumps(app.openapi(),ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'operations':len(operations),'sources':len(sources),'models':len(models),'approved':False}))
