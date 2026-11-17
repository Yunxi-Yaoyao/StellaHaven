"""One file per process, exact original function reexports, event receipts."""
import sys,json,ast,hashlib,importlib,inspect
from pathlib import Path
from control import ROOT,OUT,OLD
import guard
import pytest
file=sys.argv[1];label=sys.argv[2] if len(sys.argv)>2 else 'attempt1'
full_owning='--full-owning' in sys.argv
if full_owning:sys.argv.remove('--full-owning')
mode='main' if file.startswith('tests/') or file.endswith(('test_current_contracts.py','test_current_browser_contract.py')) else 'pg'
if mode=='main':import main_fixtures
else:import pg_fixtures
original=guard.APP/file
if file.endswith(('test_notes_zip_browser.py','test_current_browser_contract.py')):
 import os
 os.environ['STELLA_LIVE_BROWSER']='1'
 os.environ['STELLA_TEST_CHROMIUM']='/usr/sbin/google-chrome-stable'
if file in {'tests_isolated/test_monitor_performance_pg.py','tests_isolated/test_operations_audit_pg.py'}:
 import app.services
module=importlib.import_module(Path(file).stem if file.startswith('qa/') else file[:-3].replace('/','.'))
wrapper=ROOT/'wrappers'/('test_'+file.replace('/','_'))
lines=['# Original IDs re-exported; approved historical assertions migrated; fixture adapters explicit.','from '+module.__name__+' import *']
if mode=='main':lines+=['from main_fixtures import db_session, client']
else:lines+=['from pg_fixtures import *']
if file.endswith(('test_notes_zip_browser.py','test_current_browser_contract.py')):lines+=['from browser_fixture import browser_socket']
if file=='tests_ha/test_blob_cache_http.py':lines+=['from blob_fixture import live']
if file in {'tests/test_flat_import_retry.py','tests/test_notes_zip_integration.py'}:lines+=['from main_fixtures import workspace_id']
wrapper.write_text('\n'.join(lines)+'\n')
known={c['id']:c for suite in json.loads((OLD/'backend-final-inventory.json').read_text())['suites'] for c in suite['cases']}
events=[];collection=[];fixtures=[]
class Receipt:
 @pytest.hookimpl(tryfirst=True)
 def pytest_fixture_setup(self,fixturedef,request):
  source=inspect.getsourcefile(fixturedef.func) or ''
  pinned={'test_browser_sessions_pg.py':{'pg'},'test_owner_admin_security_pg.py':{'pg_security'},'test_monitor_performance_pg.py':{'engine'},'test_notes_review_boundaries_pg.py':{'notes'},'test_traffic_query_fastpath.py':{'pg'},'test_blob_cache_http.py':{'live'},'test_migration_lock.py':{'db'},'test_shared_state.py':{'pg'}}
  assert not source.endswith('/tests/conftest.py'), 'original conftest forbidden'
  assert fixturedef.argname not in pinned.get(Path(source).name,set()), 'original pinned fixture forbidden'
  fixtures.append({'name':fixturedef.argname,'source':source})
 def pytest_collection_modifyitems(self,config,items):
  selected=[];deselected=[]
  for item in items:
   case=file[:-3].replace('/','.')+'::'+item.name
   prior=known.get(case)
   # Only the two setup errors from the already-run unit suite.
   if not full_owning and (file=='tests/test_external_services_unit.py' or mode=='pg') and prior and prior['status']=='passed':deselected.append(item);continue
   selected.append(item)
   collection.append(dict(nodeid=item.nodeid,original_id=case,prior=prior,function_file=inspect.getsourcefile(item.obj),function_sha256=hashlib.sha256(inspect.getsource(item.obj).encode()).hexdigest()))
  items[:]=selected
  config.hook.pytest_deselected(items=deselected)
 def pytest_runtest_logreport(self,report):
  events.append(dict(nodeid=report.nodeid,when=report.when,outcome=report.outcome,subtest=hasattr(report,'context'),longrepr=str(report.longrepr) if report.failed else ''))
 def pytest_sessionfinish(self,session,exitstatus):
  if file.endswith(('test_notes_zip_browser.py','test_current_browser_contract.py')):
   import shutil
   for image in (ROOT/'tmp').rglob('stella-notes-live-*.png'):
    dest=OUT/'screenshots'/label/file.replace('/','_')/image.name
    dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(image,dest)
  (OUT/(label+'-'+file.replace('/','_')+'-events.json')).write_text(json.dumps(dict(collection=collection,events=events,fixtures=fixtures,exitstatus=exitstatus),indent=2))
name=label+'-'+file.replace('/','_')
(OUT/(name+'-harness.json')).write_text(json.dumps({'source_head':guard.s['head'],'namespace':guard.os.readlink('/proc/self/ns/net'),'original_pinned_target_fixture_called':False,'process_mode':mode,'harness_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')}},indent=2))
rc=pytest.main([str(wrapper),'--noconftest','-q','--tb=short','--junitxml='+str(OUT/(name+'.xml')),*sys.argv[3:]],plugins=[Receipt()])
sys.exit(rc)
