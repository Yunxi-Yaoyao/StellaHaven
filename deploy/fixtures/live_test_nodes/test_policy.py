import unittest
from fixture_policy import allowed
class PolicyTests(unittest.TestCase):
 def test_only_owned_numeric_targets(self):
  for h in ['192.168.160.2','192.168.160.3']:
   self.assertTrue(allowed('ping',h));self.assertTrue(allowed('tcp',h+':8080'));self.assertTrue(allowed('tcp',h+':8081'))
  for h in ['8.8.8.8','169.254.169.254','127.0.0.1','localhost','192.168.1.1','1','192.168.160.3;id','192.168.160.3:443']:
   self.assertFalse(allowed('ping',h));self.assertFalse(allowed('tcp',h))
  self.assertFalse(allowed('https','https://192.168.160.3:8080'))
 def test_mtr_budgets_use_actual_candidate_max_hops_key(self):
  from fixture_policy import mtr_params
  self.assertEqual(mtr_params({'count':100,'max_hops':255,'psize':64000,'interval':.1}),{'count':10,'max_hops':4,'psize':128,'interval':1.0})
if __name__=='__main__':unittest.main()
