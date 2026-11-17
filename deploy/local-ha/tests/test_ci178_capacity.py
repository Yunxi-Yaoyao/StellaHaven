"""Current completed CI intervals calibrate weights, not runner timeout."""
import hashlib
import json
import math
from collections import Counter
import unittest
from test_backend_capacity import ROOT, planner, assert_historical_floor_or_measured_clone

class CI178Capacity(unittest.TestCase):
 def test_all_successful_ci178_observations_are_costed(self):
  path=ROOT/'deploy/ci/ci178-backend-timings.json'
  raw=path.read_bytes()
  self.assertEqual(hashlib.sha256(raw).hexdigest(),'9288bbbabdb1767c4421a2dce890458fe640ed346c80cfcb8ff02cfe6f3602cb')
  data=json.loads(raw)
  self.assertEqual(data['source_commit'],'3551f39993667fd9aa898f48ca38a6f78e500fb6')
  self.assertEqual(len(data['successful_command_seconds']),196)
  self.assertNotIn('tests_isolated/test_system_memory.py',data['successful_command_seconds'])
  m=planner()
  owned_raw=(ROOT/'deploy/ci/owned-timings.json').read_bytes()
  self.assertEqual(hashlib.sha256(owned_raw).hexdigest(),'8fbcbb945b79c1748b9f6d235845ab024d898a75b6be708dee30c2c6239aab2c')
  owned=json.loads(owned_raw)
  for command,seconds in owned['completed_seconds'].items():
   with self.subTest(owned=command):
    completed=max(seconds,data['successful_command_seconds'].get(command,0),owned['prior_remote_completed_seconds'].get(command,0),m._CI182_TIMINGS['successful_command_seconds'].get(command,0))
    self.assertEqual(m.estimated_seconds([command]),math.ceil(1.20*completed+5))
  # New complete command observations are explicit, never default ten seconds.
  self.assertEqual(owned['completed_seconds']['tests_agent_refresh_timeout/test_full_main.py'],49.39614888979122)
  self.assertEqual(owned['completed_seconds']['tests_agent_unified/test_refresh_timeout.py'],120.23372340016067)
  for command,seconds in data['successful_command_seconds'].items():
   with self.subTest(command=command):
    assert_historical_floor_or_measured_clone(self,m,command,seconds)
 def test_seven_shards_keep_every_original_command_and_ten_percent_reserve(self):
  m=planner();data=json.loads((ROOT/'deploy/ci/ci178-backend-timings.json').read_text())
  plans=[m.plan(ROOT,i,7) for i in range(1,8)]
  expected=[list(c) for c in m.GROUP_COMMANDS]+[[str(p.relative_to(ROOT)),'--noconftest'] for p in sorted((ROOT/'tests_isolated').glob('test_*.py'))]+[[str(p.relative_to(ROOT))] for d in ('tests_node_files','tests_node_files_delivery','tests_agent_unified','tests_agent_refresh_timeout') for p in sorted((ROOT/d).glob('test_*.py'))]
  self.assertEqual(Counter(map(tuple,expected)),Counter(tuple(c) for shard in plans for c in shard))
  for shard in plans:
   setup=75+(140 if any(m.command_requires_browser(c) for c in shard) else 0)
   self.assertLessEqual(setup+sum(m.estimated_seconds(c) for c in shard),1100)
   # Completed refresh commands replace unknown ten-second defaults/reserves;
   # do not describe conservative estimated margins as observed wall time.
   observed_commands=dict(data['successful_command_seconds'])
   owned=json.loads((ROOT/'deploy/ci/owned-timings.json').read_text())
   for command,seconds in owned['completed_seconds'].items():
    observed_commands[command]=max(observed_commands.get(command,0),seconds)
   for command,row in m._COPY_TIMINGS['observations'].items():
    observed_commands[command]=row['completed_seconds']
   for command,seconds in m._CI182_TIMINGS['successful_command_seconds'].items():
    if command not in m._COPY_TIMINGS['observations']:
     observed_commands[command]=max(observed_commands.get(command,0),seconds)
   for command,row in m._V23_TIMINGS['observations'].items():
    observed_commands[command]=max(observed_commands.get(command,0),row['completed_seconds'])
   for command,row in m._DERIVATION_TIMINGS['observations'].items():
    observed_commands[command]=row['completed_seconds']
   observed=setup+sum(observed_commands.get(c[0],m.estimated_seconds(c)) for c in shard)
   self.assertLessEqual(observed,1000)
