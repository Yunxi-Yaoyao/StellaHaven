"""Offline activity-copy migration; synthetic files only, no application/DB imports."""
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys

TOOL=Path(__file__).resolve().parents[1]/'tools/migrate_drive_background.py'

def test_dry_run_cas_and_exact_active_copy_preserve_owner_customizations(tmp_path):
    assert TOOL.exists(), 'safe active-copy migration tool missing'
    spec=importlib.util.spec_from_file_location('migration',TOOL);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    old='ownerPrefix();\n/* stella:background-ready:v1 */\n(()=>{ const parentOrigins=["https://main.example"];\n})();\nownerSuffix();'
    module={'injection':{'active':{'enabled':True,'js':old,'css':'owner CSS','version':'old'},'draft':{'js':'unfinished'},'previous':{'js':'previous'}}}
    config={'modules':{'drive':module},'sibling':{'secret':'synthetic'}}
    source=tmp_path/'config.json';source.write_text(json.dumps(config));before=source.read_bytes()
    replacement=tmp_path/'new.js';replacement.write_text('/* stella:background-ready:v1 */\n(()=>{ const parentOrigins=["https://main.example","https://main.p.example"];\n})();')
    args=[sys.executable,str(TOOL),str(source),'--module-id','drive','--expected-config-sha256',hashlib.sha256(before).hexdigest(),'--expected-js-sha256',hashlib.sha256(old.encode()).hexdigest(),'--replacement-js',str(replacement),'--backup-dir',str(tmp_path/'private')]
    dry=subprocess.run(args,capture_output=True,text=True);assert dry.returncode==0,dry.stderr;assert source.read_bytes()==before;assert not (tmp_path/'private').exists();assert not source.with_name(source.name+'.migration.lock').exists()
    applied=subprocess.run(args+['--apply-local-file'],capture_output=True,text=True);assert applied.returncode==0,applied.stderr
    after=json.loads(source.read_text());active=after['modules']['drive']['injection']['active'];assert active['js'].startswith('ownerPrefix();');assert active['js'].endswith('ownerSuffix();');assert 'main.p.example' in active['js'];assert active['css']=='owner CSS'
    for key in ('draft','previous'):assert after['modules']['drive']['injection'][key]==module['injection'][key]
    assert after['sibling']==config['sibling'];backups=list((tmp_path/'private').iterdir());assert len(backups)==1;assert backups[0].read_bytes()==before;assert backups[0].stat().st_mode&0o777==0o600
    stale=subprocess.run(args+['--apply-local-file'],capture_output=True,text=True);assert stale.returncode!=0;assert json.loads(source.read_text())==after
    source.write_bytes(before.replace(b'ownerSuffix',b'changedCode'));custom=subprocess.run(args+['--apply-local-file'],capture_output=True,text=True);assert custom.returncode!=0;assert b'changedCode' in source.read_bytes()
