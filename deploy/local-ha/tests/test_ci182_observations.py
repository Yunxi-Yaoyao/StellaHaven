"""CI182 timing evidence stays frozen and cannot certify excess demand as green."""
import hashlib
import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]

class CI182FrozenInputs(unittest.TestCase):
    def test_successful_whole_commands_exclude_failed_and_censored_commands(self):
        raw = (ROOT / 'deploy/ci/ci182-backend-timings.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '02b3ad37b256a398295c7b0f4bd2dc5cfd651abcc8efe186da16573001ff335f')
        data = json.loads(raw)
        self.assertEqual(data['source_commit'], '5787c955074ae520c9f3f885b10002b44b0a57f1')
        self.assertEqual(data['pipeline_id'], 182)
        self.assertEqual(len(data['successful_command_seconds']), 106)
        for failed in ('tests_isolated/test_dual_entry.py', 'tests_isolated/test_access_runtime.py', 'tests_generic_templates', 'tests_node_files/test_pipeline.py', 'tests_isolated/test_entry_lifecycle_v11.py'):
            self.assertNotIn(failed, data['successful_command_seconds'])
        for row in data['observations']:
            self.assertTrue(math.isfinite(row['seconds']) and row['seconds'] > 0)
            self.assertIn('passed', row['summary'])
            self.assertNotIn('failed', row['summary'])
            self.assertEqual(len(row['trace_sha256']), 64)

    def test_copy_cohort_has_complete_equal_original_cases_and_exact_source_bindings(self):
        from test_backend_capacity import planner
        import xml.etree.ElementTree as ET
        manifest = json.loads((ROOT/'deploy/ci/copy-capacity-timings.json').read_text())
        expected = {'refresh_timeout_evidence','v11_integration','source_metadata_v13','nav_files_evidence','current_overlay_v13','ci167_evidence','v6_integration','completion','contract'}
        self.assertEqual(set(manifest['observations']), {'tests_isolated/test_api_response_'+name+'.py' for name in expected})
        import runpy
        successor = runpy.run_path(str(ROOT/'deploy/ci/capacity_successor.py'))
        successor['validate_sources'](ROOT)
        for source, digest in manifest['changed_source_sha256'].items():
            self.assertEqual(hashlib.sha256(successor['historical_source'](ROOT,source)).hexdigest(), digest, source)
        versions = manifest['copy_dependency_versions']
        self.assertEqual(versions['final_identity_source_sha256'],hashlib.sha256((ROOT/'tests_isolated/evidence_graph_copy.py').read_bytes()).hexdigest())
        timed_source = ROOT/'docs/private-remediation/copy-capacity-final/timed-copy-dependency.py.txt'
        self.assertEqual(versions['timed_source_sha256'],hashlib.sha256(timed_source.read_bytes()).hexdigest())
        hardened = json.loads((ROOT/versions['identity_hardening_evidence']).read_text())
        self.assertTrue(hardened['semantic_equivalence_on_complete_real_snapshot'])
        self.assertTrue(hardened['metaclass_negative_red_current_green'])
        self.assertEqual(hardened['whole_command_weight_factor_applied'],1.0)
        self.assertEqual(len(versions['final_identity_whole_replayed']),4)
        m = planner()
        for command,row in manifest['observations'].items():
            receipt = ROOT/row['receipt']
            self.assertEqual(hashlib.sha256(receipt.read_bytes()).hexdigest(),row['receipt_sha256'])
            after = json.loads(receipt.read_text())
            if 'baseline_collection_receipt' in row:
                before = json.loads((ROOT/row['baseline_collection_receipt']).read_text())
                name = Path(command).stem.removeprefix('test_api_response_')
                frozen = ROOT/'docs/private-remediation/copy-capacity-final'/(name+'-ci182-source.py.txt')
                self.assertEqual(hashlib.sha256(frozen.read_bytes()).hexdigest(),before['source_sha256'])
                if name == 'completion':
                    self.assertEqual(frozen.read_bytes(),successor['historical_source'](ROOT,command))
                else:
                    import ast
                    old = ast.parse(frozen.read_bytes());new = ast.parse(successor['historical_source'](ROOT,command))
                    for tree in (old,new):
                        tree.body = [node for node in tree.body if not isinstance(node,ast.FunctionDef) or node.name != 'response_module']
                    self.assertEqual(ast.dump(old),ast.dump(new))
                remote = before['prior_full_CI182_observation']
                self.assertIn(remote,m._CI182_TIMINGS['observations'])
                self.assertIn(str(row['original_case_count'])+' passed',remote['summary'])
                self.assertEqual(row['baseline_trace_sha256'],remote['trace_sha256'])
                self.assertIn('collection-only',before['execution_kind'])
                self.assertEqual(row['before_seconds'],remote['seconds'])
                variants = ('after',)
            else:
                before = json.loads(receipt.with_name(receipt.name.replace('-after.json','-before.json')).read_text())
                variants = ('before','after')
            self.assertEqual(after['returncode'],0)
            self.assertEqual(before['returncode'],0)
            self.assertEqual(after['cases'],before['cases'])
            self.assertEqual(len(after['cases']),row['original_case_count'])
            self.assertEqual(hashlib.sha256(json.dumps(after['cases']).encode()).hexdigest(),row['case_ids_sha256'])
            for variant in variants:
                xml = receipt.with_name(receipt.name.replace('-after.json','-'+variant+'.xml'))
                suite = ET.parse(xml).getroot().find('testsuite')
                self.assertIsNotNone(suite)
                self.assertEqual([suite.get(k) for k in ('failures','errors','skipped')],['0','0','0'])
                original = before if variant == 'before' else after
                self.assertEqual([[case.get('classname'),case.get('name')] for case in suite.iter('testcase')],original['cases'])
                log = xml.with_suffix('.log')
                self.assertEqual(hashlib.sha256(log.read_bytes()).hexdigest(),original['log_sha256'])
            prior = m._CI182_TIMINGS['successful_command_seconds'].get(command)
            if prior is not None:
                self.assertGreaterEqual(row['old_weight'],math.ceil(1.05*prior))
            else:
                prior = m._CI182_TIMINGS['new_local_successful_command_seconds'][command]
                self.assertGreaterEqual(row['old_weight'],math.ceil(1.20*prior+5))
            self.assertEqual(row['completed_seconds'],after['seconds'])
            current = m._V23_TIMINGS['observations'][command]['completed_seconds']
            optimized = m._DERIVATION_TIMINGS['observations'].get(command) if command in m._DERIVATION_TIMINGS['modeled_replacements'] else None
            expected_weight = math.ceil(1.20*optimized['completed_seconds']+5) if optimized else max(math.ceil(1.20*after['seconds']+5),math.ceil(1.20*current+5))
            self.assertEqual(m.estimated_seconds([command]),expected_weight)
        # Every unmeasured old CI182 floor remains active, including local ones.
        for local,source in ((False,m._CI182_TIMINGS['successful_command_seconds']),
                             (True,m._CI182_TIMINGS['new_local_successful_command_seconds'])):
            for command,seconds in source.items():
                if command not in manifest['observations']:
                    owned = local or command in m._OWNED_TIMINGS['completed_seconds']
                    self.assertGreaterEqual(m.estimated_seconds([command]),math.ceil((1.20 if owned else 1.05)*seconds+(5 if owned else 0)))
        import gzip
        snapshot = gzip.decompress((ROOT/'docs/private-remediation/copy-capacity-final/snapshot-equivalence.json.gz').read_bytes())
        self.assertEqual(hashlib.sha256(snapshot).hexdigest(),'68ea43be4e1ddf773fbe1f56cc81cf6d109be578536b9bcd6e34b684f91bcd65')
        payload = json.loads(snapshot)
        self.assertEqual(len(payload['whole_default_schema']['paths']),257)
        self.assertEqual(len(payload['DECLARATIONS']),326)
        for variant in ('before','after'):
            summary = json.loads((ROOT/'docs/private-remediation/copy-capacity-final'/('snapshot-'+variant+'-summary.json')).read_text())
            self.assertTrue(summary['fresh_mutation_independent'])
            self.assertEqual(summary['combined_sha256'],hashlib.sha256(snapshot).hexdigest())
            if variant == 'before': baseline = summary
            else:
                for key in ('schema_sha256','declarations_sha256','combined_sha256','paths','declarations'):
                    self.assertEqual(summary[key],baseline[key])

    def test_v23_successor_separates_frozen_sources_and_rejects_unknown_current_bytes(self):
        import runpy
        import tempfile
        import os
        successor = runpy.run_path(str(ROOT/'deploy/ci/capacity_successor.py'))
        successor['validate_sources'](ROOT)
        manifest = successor['load']()
        frozen = json.loads((ROOT/'deploy/ci/copy-capacity-timings.json').read_text())
        retired = successor['load_derivation']()['retired_v23_sources']
        self.assertEqual(set(manifest['historical_sources']) | (set(retired) & set(frozen['changed_source_sha256'])), {
            p for p, h in frozen['changed_source_sha256'].items()
            if hashlib.sha256((ROOT/p).read_bytes()).hexdigest() != h})
        for path, row in manifest['historical_sources'].items():
            self.assertEqual(row['historical_sha256'], frozen['changed_source_sha256'][path])
            self.assertEqual(hashlib.sha256(successor['historical_source'](ROOT,path)).hexdigest(), row['historical_sha256'])
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            for path in successor['load_derivation']()['current_source_sha256']:
                target = root/path; target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((ROOT/path).read_bytes())
            successor['validate_sources'](root)
            for path in successor['load_derivation']()['current_source_sha256']:
                target = root/path; original = target.read_bytes()
                target.write_bytes(original+b'\ncorrupt-capacity-source')
                with self.assertRaises(AssertionError,msg=path):
                    successor['validate_sources'](root)
                target.write_bytes(original)
        for path in manifest['observations']:
            self.assertIn(path,manifest['current_source_sha256'])

    def test_v23_whole_command_receipts_and_larger_prior_completed_weights(self):
        from test_backend_capacity import planner
        import xml.etree.ElementTree as ET
        import runpy
        import tempfile
        import os
        from unittest.mock import patch
        m = planner()
        data = m._V23_TIMINGS
        self.assertEqual(len(data['observations']),19)
        for command,row in data['observations'].items():
            if command in m._COPY_TIMINGS['observations']:
                old = m._COPY_TIMINGS['observations'][command]
                old_cases = json.loads((ROOT/old['receipt']).read_text())['cases']
                current_xml = ET.parse(ROOT/row['xml']).getroot()
                current_cases = [[c.get('classname'),c.get('name')] for c in current_xml.iter('testcase')]
                self.assertTrue(set(map(tuple,old_cases)).issubset(set(map(tuple,current_cases))),command)
            for key in ('log','xml'):
                self.assertEqual(hashlib.sha256((ROOT/row[key]).read_bytes()).hexdigest(),row[key+'_sha256'])
            xml = ET.parse(ROOT/row['xml']).getroot()
            cases = [[c.get('classname'),c.get('name')] for c in xml.iter('testcase')]
            self.assertEqual(len(cases),row['case_count'])
            self.assertEqual(len(cases),len(set(map(tuple,cases))))
            self.assertEqual(hashlib.sha256(json.dumps(cases).encode()).hexdigest(),row['cases_sha256'])
            for suite in xml.iter('testsuite'):
                self.assertEqual([suite.get(k) for k in ('failures','errors','skipped')],['0','0','0'])
            self.assertEqual(row['argv'][-1],command)
            if command in m._DERIVATION_TIMINGS['modeled_replacements']:
                replacement = m._DERIVATION_TIMINGS['observations'][command]
                self.assertEqual(m.estimated_seconds([command]),math.ceil(1.20*replacement['completed_seconds']+5))
            else:
                self.assertGreaterEqual(m.estimated_seconds([command]),math.ceil(1.20*row['completed_seconds']+5))
        successor = runpy.run_path(str(ROOT/'deploy/ci/capacity_successor.py'))
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            path = Path(tmp)/'v23-capacity-timings.json'
            original = (ROOT/'deploy/ci/v23-capacity-timings.json').read_bytes()
            path.write_bytes(original+b' ')
            with patch.object(successor['load'].__globals__['Path'],'read_bytes',return_value=path.read_bytes()):
                with self.assertRaisesRegex(AssertionError,'manifest drift'):
                    successor['load']()
            for source,row in data['historical_sources'].items():
                target = Path(tmp)/row['fixture'];target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((ROOT/row['fixture']).read_bytes())
                successor['historical_source'](Path(tmp),source)
                import gzip
                body = gzip.decompress(target.read_bytes())
                target.write_bytes(gzip.compress(body+b'corrupt',mtime=0))
                with self.assertRaises(AssertionError,msg=source):
                    successor['historical_source'](Path(tmp),source)
        # Removing the successor application must be detected by an actual
        # increased command, not accepted as an unknown/default reservation.
        path = 'tests_isolated/test_api_response_private_remediation_evidence.py'
        self.assertGreater(m.estimated_seconds([path]),51)

    def test_derivation_cohort_keeps_exact_collectors_complete_receipts_and_only_three_replacements(self):
        import runpy
        import xml.etree.ElementTree as ET
        from test_backend_capacity import planner
        successor = runpy.run_path(str(ROOT/'deploy/ci/capacity_successor.py'))
        data = successor['load_derivation']()
        m = planner()
        self.assertEqual(set(data['observations']), {'tests_isolated/test_api_response_source_metadata_v13.py','tests_isolated/test_api_response_ci167_evidence.py','tests_isolated/test_api_response_current_overlay_v13.py'})
        self.assertEqual(sum(r['case_count'] for r in data['observations'].values()),435)
        for command,row in data['observations'].items():
            xml = ET.parse(ROOT/row['xml']).getroot()
            cases = [[c.get('classname'),c.get('name')] for c in xml.iter('testcase')]
            self.assertEqual(len(cases),row['case_count'])
            self.assertEqual(hashlib.sha256(json.dumps(cases).encode()).hexdigest(),row['cases_sha256'])
            self.assertEqual(len(cases),len(set(map(tuple,cases))))
            for suite in xml.iter('testsuite'):
                self.assertEqual([suite.get(k) for k in ('failures','errors','skipped')],['0','0','0'])
            for key in ('log','xml'):
                self.assertEqual(hashlib.sha256((ROOT/row[key]).read_bytes()).hexdigest(),row[key+'_sha256'])
            name = Path(command).stem.removeprefix('test_api_response_')
            folder = ROOT/'docs/private-remediation/capacity-derivation'
            before = json.loads((folder/('before-'+name+'.json')).read_text())
            after = json.loads((folder/('optimized-'+name+'.json')).read_text())
            self.assertEqual(before['cases'],after['cases'])
            for suffix,key in (('xml','xml_sha256'),('log','log_sha256')):
                self.assertEqual(hashlib.sha256((folder/('before-'+name+'.'+suffix)).read_bytes()).hexdigest(),before[key])
            before_xml = ET.parse(folder/('before-'+name+'.xml')).getroot()
            self.assertEqual([[c.get('classname'),c.get('name')] for c in before_xml.iter('testcase')],before['cases'])
            for suite in before_xml.iter('testsuite'):
                self.assertEqual([suite.get(k) for k in ('failures','errors','skipped')],['0','0','0'])
            self.assertEqual(after['cases'],cases)
            self.assertEqual((before['returncode'],after['returncode']),(0,0))
            self.assertEqual(after['seconds'],row['completed_seconds'])
            self.assertLess(after['seconds'],before['seconds'])
            if command in data['modeled_replacements']:
                self.assertEqual(m.estimated_seconds([command]),math.ceil(1.20*after['seconds']+5))
            else:
                self.assertGreaterEqual(m.estimated_seconds([command]),math.ceil(1.20*after['seconds']+5))
        for path,row in data['assertion_preservation'].items():
            import ast
            source = successor['v23_source'](ROOT,path)
            original = [ast.dump(n) for n in ast.walk(ast.parse(source)) if isinstance(n,ast.Assert)]
            current = [ast.dump(n) for n in ast.walk(ast.parse((ROOT/path).read_bytes())) if isinstance(n,ast.Assert)]
            self.assertEqual(original,current)
            self.assertEqual(len(original),row['assertions'])

    def test_derivation_manifest_and_each_retired_v23_blob_reject_corruption(self):
        import runpy
        import tempfile
        import os
        import gzip
        from unittest.mock import patch
        successor = runpy.run_path(str(ROOT/'deploy/ci/capacity_successor.py'))
        data = successor['load_derivation']()
        raw = (ROOT/'deploy/ci/derivation-capacity-timings.json').read_bytes()
        with patch.object(successor['load_derivation'].__globals__['Path'],'read_bytes',return_value=raw+b' '):
            with self.assertRaisesRegex(AssertionError,'derivation manifest drift'):
                successor['load_derivation']()
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            for path,row in data['retired_v23_sources'].items():
                target = Path(tmp)/row['fixture'];target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((ROOT/row['fixture']).read_bytes())
                successor['v23_source'](Path(tmp),path)
                target.write_bytes(gzip.compress(gzip.decompress(target.read_bytes())+b'corrupt',mtime=0))
                with self.assertRaises(AssertionError,msg=path):
                    successor['v23_source'](Path(tmp),path)

    def test_new_heavy_remaining_command_is_not_an_unknown_ten_second_weight(self):
        data = json.loads((ROOT / 'deploy/ci/ci182-backend-timings.json').read_text())
        self.assertEqual(set(data['new_local_successful_command_seconds']), {'tests_isolated/test_agent_19_upgrade.py', 'tests_isolated/test_api_response_refresh_timeout_evidence.py'})
        value = data['new_local_successful_command_seconds']['tests_isolated/test_api_response_refresh_timeout_evidence.py']
        self.assertEqual(value, 145.69222494680434)
        self.assertEqual(math.ceil(1.20 * value + 5), 180)
        self.assertEqual(len(data['local_observations']), 2)
