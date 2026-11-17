"""Regenerate ONLY reviewed entry monitoring DTO/source additions, offline.

Do not accept unrelated auth/source drift here; the owning lane must review it.
"""
import ast, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests_isolated')]
from pydantic import TypeAdapter
from app.schemas.monitor import NodeRead,NodeDetail,AgentConfig
from app.schemas.control_channel import EntryDefinition
from app import api_response_contracts as contracts
from test_api_openapi_contract import static_inventory

FILES=['app/services/backup_projection.py','agent/stella_agent.py','app/models/node.py','app/routers/monitor.py','app/schemas/monitor.py','app/schemas/public_node.py','app/schemas/control_channel.py','app/services/node.py','app/services/monitor.py','app/services/node_monitor_policy.py','app/services/entry_monitoring.py','app/services/entry_targets.py']
changed=set(FILES)
sources={}
for symbol,row in contracts.SOURCE_EVIDENCE.items():
    if row['file'] in changed:
        sources[symbol]={**row,'sha256':hashlib.sha256((ROOT/row['file']).read_bytes()).hexdigest()}
        tree=ast.parse((ROOT/row['file']).read_text())
        name=symbol.rsplit('.',1)[-1]
        node=next((n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==name),None)
        if node is not None:sources[symbol].update(line=node.lineno,end_line=node.end_lineno)
for file in FILES:
    symbol=file+':entry-monitoring-review'
    sources[symbol]=dict(file=file,sha256=hashlib.sha256((ROOT/file).read_bytes()).hexdigest(),line=1,end_line=len((ROOT/file).read_text().splitlines()),symbol=symbol)
endpoint='app.routers.monitor.entry_monitoring_summary'
fn=next(n for n in ast.parse((ROOT/'app/routers/monitor.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='entry_monitoring_summary')
sources[endpoint]=dict(file='app/routers/monitor.py',sha256=hashlib.sha256((ROOT/'app/routers/monitor.py').read_bytes()).hexdigest(),line=fn.lineno,end_line=fn.end_lineno,symbol=endpoint)
row=dict(method='GET',path='/nodes/entry-monitoring',endpoint=endpoint,status_code='200',model='list[EntryDefinition]',sources=[endpoint,*[f+':entry-monitoring-review' for f in FILES]],error_statuses=['401','422'],request_validation=False)
models={}
for name,model in [('NodeRead',NodeRead),('NodeDetail',NodeDetail),('list[NodeRead]',list[NodeRead]),('AgentConfig',AgentConfig),('list[EntryDefinition]',list[EntryDefinition])]:
    value=TypeAdapter(model).json_schema(mode='serialization')
    if 'JsonValue' in value.get('$defs',{}):value['$defs']['JsonValue']=contracts.JSON_VALUE
    if 'PublicRecord' in value.get('$defs',{}):value['$defs']['PublicRecord']['additionalProperties']=False
    models[name]=value
    if name in ('NodeRead','NodeDetail','list[NodeRead]'):
        models[name+' excluding token']=value
additions={o['endpoint']:[f+':entry-monitoring-review' for f in FILES] for o in contracts.INVENTORY if o['endpoint'].startswith('app.routers.monitor.')}
result=dict(review='Bounded automatic management ICMP and previous completed actual report transaction; no production rollout. See docs/entry-monitoring-candidate.md.',sources=sources,operations=[row],source_additions=additions,models=models)
(ROOT/'app/api_response_entry_monitoring.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('Frozen scoped sources',len(sources),'models',len(models),'new operations',1)
