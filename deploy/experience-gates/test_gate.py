"""Adversarial gate tests; these synthetic receipt objects are unit fixtures only."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
CONTRACT = json.loads((HERE / 'contract.json').read_text())
SHA = 'a' * 40

def receipt(kind='synthetic-process'):
    result = dict(schema=CONTRACT['schema'], kind=kind, commit=SHA, harness_commit=SHA,
                  dirty=False, status='passed', errors=[], checks=[dict(id=i, status='passed',
                  expected='passed', attempts=1, errors=[], evidence='unit-fixture-only') for i in CONTRACT[kind]])
    if kind == 'production-readback':
        result['environment'] = dict(host='Nyarch', cache='normal', route_mocks=False, ordinary_session=True, diagnostic_recording=False)
        result['performance'] = {key: [1, 2, 3, 4, 5] for key in CONTRACT['performance']}
    return result

class ReceiptGateTests(unittest.TestCase):
    def setUp(self):
        target = HERE / 'check_receipt.py'
        self.assertTrue(target.is_file(), 'mandatory exact-commit receipt checker is absent')
        spec = importlib.util.spec_from_file_location('receipt_gate', target)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.validate = module.validate

    def test_complete_exact_commit_passes(self):
        self.assertEqual(self.validate(receipt(), SHA, 'synthetic-process'), [])

    def test_fail_closed_for_all_non_success_shapes(self):
        cases = {}
        for field, value in [('commit','b'*40), ('harness_commit','b'*40), ('dirty',True), ('status','blocked'), ('errors',['runner died'])]:
            r=receipt();r[field]=value;cases[field]=r
        for value in ['skipped','flaky','failed','timedOut','interrupted','unexpected','blocked']:
            r=receipt();r['checks'][0]['status']=value;cases[value]=r
        for field,value in [('attempts',2),('expected','failed'),('errors',['bad assertion']),('evidence','')]:
            r=receipt();r['checks'][0][field]=value;cases[field]=r
        for field in ['schema','checks','commit','harness_commit','dirty','status','errors']:
            r=receipt();del r[field];cases['missing '+field]=r
        r=receipt();r['checks'].pop();cases['missing core']=r
        r=receipt();r['checks'].append(copy.deepcopy(r['checks'][0]));cases['duplicate core']=r
        r=receipt();r['checks'].append(dict(id='extra',status='passed'));cases['unreviewed test']=r
        for name,r in cases.items():
            with self.subTest(name=name):self.assertTrue(self.validate(r,SHA,'synthetic-process'))

    def test_ci_build_cannot_bypass_experience_gate(self):
        import re
        config = (HERE.parents[1] / '.gitlab-ci.yml').read_text()
        job = re.search(r'^experience-gate:\n(.*?)(?=^\S)', config, re.M | re.S).group(1)
        self.assertIn('extends: .branch-validation', job)
        self.assertIn('allow_failure: false', job)
        self.assertNotIn('when: manual', job)
        self.assertIn('npm run test:experience', job)
        build = re.search(r'^build-images:\n(.*?)(?=^\S)', config, re.M | re.S).group(1)
        needs = re.search(r'^  needs: (.+)$', build, re.M).group(1)
        self.assertIn('"experience-gate"', needs)

    def test_bad_expected_commit_is_not_normalized(self):
        for value in ['a'*7, ' '+SHA, 'A'*40, '', None]:
            with self.subTest(value=value):self.assertTrue(self.validate(receipt(),value,'synthetic-process'))

    def test_production_requires_raw_budgeted_normal_cache_samples(self):
        r=receipt('production-readback');self.assertEqual(self.validate(r,SHA,'production-readback'),[])
        for key,limit in CONTRACT['performance'].items():
            for samples in [[1]*4,[1]*6,[1,1,1,1,limit['max_ms']+1],[limit['median_ms']+1]*5,[0]*5,[float('nan')]*5]:
                bad=copy.deepcopy(r);bad['performance'][key]=samples
                with self.subTest(key=key,samples=samples):self.assertTrue(self.validate(bad,SHA,'production-readback'))
        for field,value in [('route_mocks',True),('cache','disabled'),('host','other'),('ordinary_session',False),('diagnostic_recording',True)]:
            bad=copy.deepcopy(r);bad['environment'][field]=value
            with self.subTest(field=field):self.assertTrue(self.validate(bad,SHA,'production-readback'))
        bad=copy.deepcopy(r);del bad['performance'];self.assertTrue(self.validate(bad,SHA,'production-readback'))
        self.assertTrue(self.validate(receipt(),SHA,'production-readback'))

if __name__ == '__main__': unittest.main()
