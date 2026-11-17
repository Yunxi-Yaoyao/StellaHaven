"""Scoped integrated feedback metadata; no application/database imports."""
import importlib.util
from collections import Counter
import sys
from pathlib import Path
import pytest
from test_api_response_contract import response_module
from test_api_openapi_contract import static_inventory, source_shaped_app
ROOT=Path(__file__).resolve().parents[1]


def test_public_qa_scripts_logout_exact_owned_session_in_finally():
    for name in ['pages-real-20261019.mjs','external-runtime-20261019.mjs']:
        source=(ROOT/'qa'/name).read_text()
        assert 'captureOwnSession' in source
        assert 'logoutOwnSession' in source.split('finally{try{',1)[-1]


def standalone(file,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/file)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m


def test_feedback_exact_operations_and_source_gate():
    c=response_module()
    actual=static_inventory()[0]
    assert c.validate_response_sources(ROOT,actual)==[]
    new={(r['method'],r['path'],r['endpoint']) for r in c._FEEDBACK['operations']}
    expected={('GET', '/alerts/incidents/{incident_id}', 'app.routers.alerts.incident_detail'),
              ('PUT', '/monitors/groups/{group_id}', 'app.routers.monitor.update_monitor_group'),
              ('GET', '/mtr-tasks/{task_id}', 'app.routers.task.get_mtr'),
              ('POST', '/monitors/groups', 'app.routers.monitor.create_monitor_group'),
              ('GET', '/notifications/{notification_id}', 'app.routers.alerts.notification_detail'),
              ('GET', '/alerts/incidents', 'app.routers.alerts.incident_list'),
              ('POST', '/mtr-jobs', 'app.routers.task.create_mtr_job'),
              ('DELETE', '/monitors/groups/{group_id}', 'app.routers.monitor.dissolve_monitor_group'),
              ('GET', '/monitors/groups', 'app.routers.monitor.list_monitor_groups'),
              ('GET', '/web-projects/workspace/{workspace_id}/identities', 'app.routers.web_projects.identities')}
    assert new == expected
    assert new <= {(m,p,e) for m,p,e,_ in actual}
    assert Counter((m,p,e) for m,p,e,_ in actual)==Counter((r['method'],r['path'],r['endpoint']) for r in c.INVENTORY)
    assert len(c.INVENTORY)==len({(r['method'],r['path']) for r in c.INVENTORY})
    assert c.validate_response_sources(ROOT,[*actual,('GET','/feedback-unknown','app.routers.monitor.list_monitor_groups',None)])


def test_feedback_backup_and_group_models_are_exact_serialization():
    c=response_module();b=standalone('app/schemas/backups.py','feedback_backup_schema_test')
    for name in ['Job','Status']:
        assert c.MODELS['Backup'+name]==getattr(b,name).model_json_schema(mode='serialization')
    m=standalone('app/schemas/monitor.py','feedback_monitor_schema_test')
    assert c.MODELS['MonitorGroupRead']==m.MonitorGroupRead.model_json_schema(mode='serialization')
    assert c.MODELS['MtrTaskRead']['properties']['job_id']==m.MtrTaskRead.model_json_schema(mode='serialization')['properties']['job_id']


def test_feedback_context_is_honestly_incomplete_and_shapes_keep_new_fields():
    c=response_module()
    for key in [('GET','/notifications'),('GET','/notifications/{notification_id}'),('GET','/alerts/incidents/{incident_id}')]:
        assert c.DECLARATIONS[key]['status']=='incomplete'
        assert 'unvalidated internal JSONB' in c.DECLARATIONS[key]['reason']
    from app.public_website import PublicModule
    for field in ['private_address','entry_policy']:
        assert c.MODELS['PublicModule']['properties'][field]==PublicModule.model_json_schema(mode='serialization')['properties'][field]
    app,_=source_shaped_app()
    from app.openapi_contract import install_openapi_contract
    install_openapi_contract(app)
    op=app.openapi()['paths']['/mtr-jobs']['post']
    assert op['x-stella-auth-type']=='cookie-access'
    assert op['x-stella-elevation']=='none'
    assert {'201','400','409','422','401','403','503'} <= set(op['responses'])
    delete=app.openapi()['paths']['/monitors/groups/{group_id}']['delete']
    assert 'content' not in delete['responses']['204']
    assert delete['x-stella-elevation']=='none'
    assert 'app.routers.auth.admin_user' in next(r[3] for r in static_inventory()[0] if r[:2]==('DELETE','/monitors/groups/{group_id}'))
