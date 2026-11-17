#!/usr/bin/env python3
"""Exercise candidate CI plus exact changed legacy contracts in an owned tree.
No live pipeline, token, Docker daemon operation, production probes or source edit.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BASE=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()

def replace_once(text,old,new):
    assert text.count(old)==1, f'baseline contract drift: {old[:80]}'
    return text.replace(old,new,1)

def contracts(tree):
    patches=[]
    rel='deploy/local-ha/tests/test_ci.py'; p=tree/rel; old=p.read_text(); new=old
    new=replace_once(new,'''        self.assertIn('$CI_COMMIT_BRANCH == "master"', rules[0]['if'])
        self.assertIn('$CI_COMMIT_REF_PROTECTED == "true"', rules[0]['if'])
        self.assertIn('$STELLA_DEPLOY_TARGET == "k3s"', rules[0]['if'])
        self.assertEqual(rules[-1], {'when': 'never'})''','''        self.assertEqual(rules, [{'when': 'never'}])''')
    new=replace_once(new,"self.assertEqual(ci['local-ha-live-readonly']['rules'][0]['when'], 'manual')","self.assertEqual(ci['local-ha-live-readonly']['rules'], [{'when': 'never'}])")
    start=new.index('    def test_latest_shell_guard_matrix(self):'); end=new.index('    def test_readonly_inventory_and_current_primary_guards',start)
    new=new[:start]+'''    def test_latest_shell_guard_matrix(self):
        ci = yaml.safe_load((ROOT.parents[1] / '.gitlab-ci.yml').read_text())
        self.assertEqual(ci['build-images']['script'], ['sh deploy/ci/runner-isolation/build-rootless.sh'])
        script = (ROOT.parents[1] / 'deploy/ci/runner-isolation/build-rootless.sh').read_text()
        self.assertNotIn(':latest', script)
        self.assertNotIn('SHORT_SHA', script)
        self.assertIn('$CI_COMMIT_SHA', script)
        self.assertIn('buildctl-daemonless.sh build', script)
        self.assertNotIn('docker build', script)
        self.assertNotIn('--network=host', script)

'''+new[end:]
    p.write_text(new); patches.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
    rel='deploy/local-ha/tests/test_production_release.py'; p=tree/rel; old=p.read_text(); new=old
    new=replace_once(new,"self.assertEqual(job['rules'][0]['when'],'on_success')","self.assertEqual(job['rules'][0]['when'],'manual')")
    new=replace_once(new,"self.assertIn('$STELLA_AUTO_DEPLOY == \"true\"',job['rules'][0]['if'])","self.assertIn('$STELLA_RUNNER_ISOLATION_READY == \"true\"',job['rules'][0]['if'])\n        self.assertNotIn('STELLA_AUTO_DEPLOY', job['rules'][0]['if'])\n        self.assertFalse(job['rules'][0]['allow_failure'])")
    new=replace_once(new,"self.assertEqual(job['rules'][1]['when'],'manual')","self.assertEqual(job['rules'][1], {'when': 'never'})")
    new=replace_once(new,"ci['build-images']['artifacts']['reports']['dotenv']","ci['build-image-receipt']['artifacts']['reports']['dotenv']")
    p.write_text(new); patches.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
    rel='deploy/local-ha/tests/test_preview_release.py'; p=tree/rel; old=p.read_text(); new=old
    new=replace_once(new,"self.assertEqual(job['rules'][0]['when'], 'manual')","self.assertEqual(job['rules'], [{'when': 'never'}])")
    new=replace_once(new,"self.assertIn('feature/local-ha-20260915', job['rules'][0]['if'])","self.assertEqual(job['tags'], ['stella-isolated-deploy'])")
    p.write_text(new); patches.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
    return ''.join(patches)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--out',required=True,type=Path); parser.add_argument('--base',default=BASE,help='Exact pre-activation commit to archive'); args=parser.parse_args(); out=args.out.resolve()
    base=subprocess.check_output(['git','-C',str(ROOT),'rev-parse',args.base+'^{commit}'],text=True).strip()
    assert shutil.disk_usage(os.environ['TMPDIR']).free>2*1024**3, 'space reserve; do not prune'
    receipt={'scope':'offline candidate CI/contract fixture only','base':base,'results':[]}
    with tempfile.TemporaryDirectory(prefix='stella-runner-candidate-',dir=os.environ['TMPDIR']) as tmp:
        temp=Path(tmp); tree=temp/'tree'; tree.mkdir(); archive=temp/'source.tar'
        subprocess.run(['git','-C',str(ROOT),'archive','--format=tar','--output',str(archive),base],check=True)
        with tarfile.open(archive) as tar: tar.extractall(tree,filter='data')
        shutil.copytree(HERE,tree/'deploy/ci/runner-isolation',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copyfile(out/'config/candidate.gitlab-ci.yml',tree/'.gitlab-ci.yml')
        (out/'activation-contract-tests.patch').write_text(contracts(tree))
        receipt['controller_unchanged']={name:hashlib.sha256((tree/'deploy/local-ha'/name).read_bytes()).hexdigest()==hashlib.sha256((ROOT/'deploy/local-ha'/name).read_bytes()).hexdigest() for name in ['node_production.py','production_release.py']}
        assert all(receipt['controller_unchanged'].values())
        commands=[('candidate-local-ha.log',[sys.executable,'-m','unittest','discover','-s','deploy/local-ha/tests','-v']),
                  ('candidate-activation-tests.log',[sys.executable,'deploy/ci/runner-isolation/test_candidate.py']),
                  ('candidate-experience-contract.log',[sys.executable,'deploy/experience-gates/test_gate.py']),
                  ('candidate-validate-pack.log',[sys.executable,'deploy/local-ha/production_release.py','--validate-pack'])]
        for filename,cmd in commands:
            proc=subprocess.run(cmd,cwd=tree,capture_output=True,text=True,timeout=120)
            (out/filename).write_text(proc.stdout+proc.stderr)
            receipt['results'].append({'log':filename,'exit_code':proc.returncode})
        receipt['status']='PASS' if all(x['exit_code']==0 for x in receipt['results']) else 'FAIL'
    receipt['owned_tree_removed']=not tree.exists()
    (out/'candidate-activation-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))
    if receipt['status']!='PASS': raise SystemExit(1)
if __name__=='__main__': main()
