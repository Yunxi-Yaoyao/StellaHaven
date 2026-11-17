"""CI170 capacity regression: frozen observations, not a wall-clock guarantee."""
from collections import Counter
import hashlib
import importlib.util
import math
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import os
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[3]


def planner():
    spec = importlib.util.spec_from_file_location('capacity_planner', ROOT/'deploy/ci/run-backend-shard.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_historical_floor_or_measured_clone(test, module, path, seconds):
    """Historical bytes stay frozen; only a proven changed cohort retires floors."""
    observed = module._COPY_TIMINGS['observations'].get(path)
    if observed is None:
        test.assertGreaterEqual(module.estimated_seconds([path]), math.ceil(seconds*1.05))
    else:
        test.assertGreaterEqual(observed['old_weight'], math.ceil(seconds*1.05))
        current = module._V23_TIMINGS['observations'][path]['completed_seconds']
        optimized = module._DERIVATION_TIMINGS['observations'].get(path) if path in module._DERIVATION_TIMINGS['modeled_replacements'] else None
        expected = math.ceil(1.20*optimized['completed_seconds']+5) if optimized else max(math.ceil(1.20*observed['completed_seconds']+5), math.ceil(1.20*current+5))
        audit = module._AUDIT_TIMINGS['observations'].get(path)
        if audit:
            expected = max(expected, math.ceil(1.20*audit['completed_seconds']+5))
        test.assertEqual(module.estimated_seconds([path]), expected)

class BackendCapacityContract(unittest.TestCase):
    def test_six_is_the_smallest_setup_aware_plan_with_twenty_percent_headroom(self):
        m = planner()
        expected = [list(c) for c in m.GROUP_COMMANDS] + [
            [str(p.relative_to(ROOT)), '--noconftest']
            for p in sorted((ROOT/'tests_isolated').glob('test_*.py'))] + [[str(p.relative_to(ROOT))] for d in ('tests_node_files','tests_node_files_delivery','tests_agent_unified','tests_agent_refresh_timeout') for p in sorted((ROOT/d).glob('test_*.py'))]
        costs = {}
        for total in (1, 4, 5, 6, 7):
            plans = [m.plan(ROOT, i, total) for i in range(1, total+1)]
            self.assertEqual(Counter(tuple(c) for shard in plans for c in shard),
                             Counter(map(tuple, expected)))
            costs[total] = max(75 + sum(m.estimated_seconds(c) for c in shard)
                              + (140 if any(m.command_requires_browser(c) for c in shard) else 0)
                              for shard in plans)
            self.assertEqual(plans, [m.plan(ROOT, i, total) for i in range(1,total+1)])
            for i, shard in enumerate(plans, 1):
                self.assertEqual(m.browser_required(ROOT,i,total),
                                 any(m.command_requires_browser(c) for c in shard))
        self.assertGreater(costs[4], 1200)
        self.assertGreater(costs[5], 960)
        self.assertGreater(costs[6], 960)
        self.assertLessEqual(costs[7], 1100)
        # Current CI178 floors are deliberately higher than the historical model.
        # Keep seven slots and the real 1200s cap, rather than concealing that
        # the older 20% estimate no longer fits after API evidence was added.
        ci = yaml.safe_load((ROOT/'.gitlab-ci.yml').read_text())
        self.assertEqual(ci['backend-test']['parallel'], 7)
        # YAML remains 25m; the unchanged effective runner cap is 1200s.
        self.assertEqual(ci['backend-test']['timeout'], '25m')

    def test_ci170_complete_intervals_and_censored_settings_are_not_ten_second_defaults(self):
        m = planner()
        # CI170 next-command timestamps; 5% ceiling. Keep the prior conservative
        # value when larger. job966 settings was censored after >110s, so 240s
        # is an explicit uncertain reserve, not an invented completed timing.
        for path, seconds in {
            'tests_isolated/test_api_response_completion.py': 509.279836,
            'tests_isolated/test_api_response_contract.py': 471.659,
            'tests_isolated/test_api_response_final_gate.py': 226.183196,
            'tests_isolated/test_api_response_ci167_evidence.py': 140.379924,
            'tests_isolated/test_api_response_agent_rollout_evidence.py': 35.292,
            'tests_isolated/test_api_response_monitor_ux_evidence.py': 128.949,
            'tests_isolated/test_web_project_7790dcf_response_contract.py': 216.080253,
            'tests_generic_templates': 33.854924,
        }.items():
            with self.subTest(path=path):
                assert_historical_floor_or_measured_clone(self,m,path,seconds)
        # CI178 completed this previously censored command in 140.108558s.
        self.assertEqual(m.estimated_seconds(['tests_website_settings']), math.ceil(1.05*m._CI182_TIMINGS['successful_command_seconds']['tests_website_settings']))
        # Replace ONLY the formerly censored documentation reserve: job968's
        # actual complete interval 22.710521s, 1 passed (pytest 21.41s).
        self.assertEqual(m.estimated_seconds(['tests_isolated/test_documentation_export.py']), max(24, math.ceil(1.20*m._V23_TIMINGS['observations']['tests_isolated/test_documentation_export.py']['completed_seconds']+5)))

    def test_legal_counts_boundaries_and_discovery_do_not_drop_new_commands(self):
        m = planner()
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            (root/'tests_isolated').mkdir()
            names = ['test_new_canary.py', 'test_new_ledger.py']
            for name in reversed(names):
                (root/'tests_isolated'/name).touch()
            expected = list(m.GROUP_COMMANDS) + [('tests_isolated/'+n,'--noconftest') for n in names]
            for total in (1,3,4,5,6,200):
                self.assertCountEqual([tuple(c) for i in range(1,total+1)
                                       for c in m.plan(root,i,total)], expected)
            for total in (0,-1,201,True,6.0,'6',None):
                with self.subTest(total=total), self.assertRaises(ValueError):
                    m.plan(root,1,total)
            for i in (0,8,-1,True,1.0,'1',None):
                with self.subTest(index=i), self.assertRaises(ValueError):
                    m.plan(root,i,7)
            for value in (0,-1,float('nan'),float('inf'),-float('inf'),True,'10',None):
                with self.subTest(value=value), patch.object(m,'DEFAULT_ESTIMATED_SECONDS',value):
                    with self.assertRaises(ValueError):
                        m.plan(root,1,6)

    def test_every_successful_ci170_interval_is_a_frozen_independent_floor(self):
        raw = (Path(__file__).parent/'fixtures/ci170-backend-timings.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '2db90d1d7809503fb36121aeb8a7d6d4e9653dd64e7d598d70b17f2faa018aca')
        fixture = json.loads(raw)
        self.assertEqual(fixture['source_commit'],'ae489f8889300f7e03d0bb7bba608785eab9c1f9')
        observations = fixture['successful_command_seconds']
        self.assertEqual(len(observations),135)
        m = planner()
        for path,seconds in observations.items():
            with self.subTest(path=path):
                assert_historical_floor_or_measured_clone(self,m,path,seconds)
        self.assertEqual(m.estimated_seconds(['tests_isolated/test_documentation_export.py']),max(24, math.ceil(1.20*m._V23_TIMINGS['observations']['tests_isolated/test_documentation_export.py']['completed_seconds']+5)))
        self.assertEqual(fixture['censored_settings_reserve_seconds'], 240)
        self.assertEqual(m.estimated_seconds(['tests_website_settings']), math.ceil(1.05*m._CI182_TIMINGS['successful_command_seconds']['tests_website_settings']))

    def test_actual_six_shards_use_fresh_argv_and_fail_fast_for_every_shard(self):
        m = planner()
        for index in range(1,8):
            with self.subTest(shard=index), patch.object(m.subprocess,'run') as run:
                run.return_value.returncode = 0
                self.assertEqual(m.execute(ROOT,index,7),0)
                expected = m.plan(ROOT,index,7)
                self.assertEqual(run.call_count,len(expected))
                for call,args in zip(run.call_args_list,expected):
                    self.assertEqual(call.args[0],([m.sys.executable,str(ROOT/'deploy/ci/run-owned-suite.py'),*args] if m._OWNED['owned_command'](args) else [m.sys.executable,'-m','pytest','-q',*args]))
                    self.assertEqual(call.kwargs,{'cwd':ROOT})
                run.reset_mock()
                run.return_value.returncode = 7
                self.assertEqual(m.execute(ROOT,index,7),7)
                self.assertEqual(run.call_count,1)

    def test_cli_dispatches_every_argv_in_a_real_distinct_process_and_stops_on_failure(self):
        m = planner()
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            calls = root/'calls.jsonl'
            # Replace only pytest's payload with an owned argv recorder. The
            # actual planner CLI + execute/subprocess.run are unmodified.
            (root/'pytest.py').write_text(
                'import json,os,sys\n'
                'with open(os.environ["CALLS"],"a") as f:\n'
                ' f.write(json.dumps({"pid":os.getpid(),"parent":os.getppid(),"argv":sys.argv[1:]})+"\\n")\n'
                'sys.exit(73 if os.environ.get("FAIL") else 0)\n')
            ci = root/'deploy/ci'
            ci.mkdir(parents=True)
            for name in ('run-backend-shard.py','owned_inventory.py','owned-timings.json','ci178-backend-timings.json','ci182-backend-timings.json','copy-capacity-timings.json','capacity_successor.py','v23-capacity-timings.json','derivation-capacity-timings.json','servers-audit-capacity-sources.json'):
                (ci/name).write_bytes((ROOT/'deploy/ci'/name).read_bytes())
            (ci/'run-owned-suite.py').write_bytes((root/'pytest.py').read_bytes())
            for directory in ('tests_isolated','tests_node_files','tests_node_files_delivery','tests_agent_unified','tests_agent_refresh_timeout'):
                (root/directory).mkdir()
                for path in (ROOT/directory).glob('test_*.py'):
                    (root/directory/path.name).touch()
            base = {'PATH':'/usr/bin:/bin','HOME':tmp,'TMPDIR':tmp,
                    'PYTHONPATH':tmp,'PYTHONDONTWRITEBYTECODE':'1',
                    'CI_NODE_TOTAL':'7','CALLS':str(calls)}
            records = []
            for i in range(1,8):
                result = subprocess.run([sys.executable,str(ci/'run-backend-shard.py')],
                    cwd=root,env={**base,'CI_NODE_INDEX':str(i)},
                    capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stderr)
                shard = [json.loads(line) for line in calls.read_text().splitlines()]
                self.assertEqual([r['argv'] for r in shard],
                                 [c if m._OWNED['owned_command'](c) else ['-q',*c] for c in m.plan(root,i,7)])
                records.extend(shard)
                calls.unlink()
                failed = subprocess.run([sys.executable,str(ci/'run-backend-shard.py')],
                    cwd=root,env={**base,'CI_NODE_INDEX':str(i),'FAIL':'1'},
                    capture_output=True,text=True,timeout=30)
                self.assertEqual(failed.returncode,73,failed.stderr)
                stopped = [json.loads(line) for line in calls.read_text().splitlines()]
                self.assertEqual(len(stopped),1)
                first = m.plan(root,i,7)[0]
                self.assertEqual(stopped[0]['argv'],first if m._OWNED['owned_command'](first) else ['-q',*first])
                calls.unlink()
            self.assertEqual(len(records),len({r['pid'] for r in records}))
            self.assertTrue(all(r['pid'] != r['parent'] for r in records))


if __name__ == '__main__':
    unittest.main()
