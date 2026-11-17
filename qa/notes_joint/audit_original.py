"""Preserve original RED; isolate F9 kwargs break from exception-wrapping defect."""
import hashlib,json,subprocess,os
from pathlib import Path
O=Path('/opt/hermes-workstation/docs/Stella-API/remediation');A=Path('/root/.hermes/cache/scratch/notes-joint-6b01e8e/application');original=O/'review-lifecycle-harness/test_review_lifecycle.py'
s=original.read_text();h=hashlib.sha256(original.read_bytes()).hexdigest()
assert 'retry=notes.client.delete' in s and s.index('retry=notes.client.delete')<s.index('assert db.get(Tag,tid) is not None')
assert 'assert isinstance(exc,IntegrityError)' in s
assert s.count('def interleave(db,data):')==1 and s.count('return original(db,data)')==1
variant=s.replace('def interleave(db,data):','def interleave(db,data,**kwargs):').replace('return original(db,data)','return original(db,data,**kwargs)')
p=A/'tests_isolated/test_original_kwargs_only.py';p.write_text(variant)
e={k:os.environ[k] for k in ['PATH','TZ','LANG'] if k in os.environ};e.update(HOME=str(A.parent/'home'),TMPDIR=str(A.parent/'tmp'),PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',STELLA_BLOB_STORAGE='postgres')
with (O/'review-notes-joint-original-kwargs-only.log').open('w') as f:r=subprocess.run(['/opt/Yunxi-workstation/Stella/.venv/bin/python','-m','pytest','--noconftest','-q','tests_isolated/test_original_kwargs_only.py::test_stale_tag_precheck_rechecks_deleted_target','--junitxml='+str(O/'review-notes-joint-original-kwargs-only.xml')],cwd=A,env=e,stdout=f,stderr=subprocess.STDOUT)
assert hashlib.sha256(original.read_bytes()).hexdigest()==h
(O/'review-notes-joint-original-harness-audit.json').write_text(json.dumps(dict(original_sha256=h,unchanged=True,f8_retry_line=96,f8_rollback_assertion_lines=[99,101],f9_hook_lines=[110,118,119,120,121],kwargs_only_variant_exit=r.returncode,correction='Independent probes require fresh-session rollback BEFORE retry, successful cleanup AFTER retry, controlled HTTPException only and no orphan rows.'),indent=2))
print('Original retained; kwargs-only diagnostic exit',r.returncode)
