"""Opt-in file automation is an exact nine-key deployment contract."""
import copy
import unittest
from test_production_release import load
from test_production_entry_overlay import overlay, extended_inventory

class FileAutomationEnvTests(unittest.TestCase):
 def test_nine_field_flag_admitted_without_mutating_existing_fields(self):
  n=load('node_production');r=load('production_release')
  for flag in ('0','1'):
   env=dict(overlay(),STELLA_NODE_FILES_ENABLED=flag);original=copy.deepcopy(env)
   self.assertEqual(n.validate_application_env_overrides(env),original)
   inv=extended_inventory(env)
   self.assertEqual(r.validate_inventory(inv),inv)
   n.Node(dict(node='nas',inventory=inv,op='release'))
 def test_unknown_partial_and_nonboolean_flags_are_refused(self):
  n=load('node_production')
  for flag in ('true','false','yes','',True,1,'1\n'):
   with self.subTest(flag=flag),self.assertRaises(ValueError):
    n.validate_application_env_overrides(dict(overlay(),STELLA_NODE_FILES_ENABLED=flag))
  for key in overlay():
   env=dict(overlay(),STELLA_NODE_FILES_ENABLED='1');del env[key]
   with self.subTest(missing=key),self.assertRaises(ValueError):n.validate_application_env_overrides(env)
  with self.assertRaises(ValueError):n.validate_application_env_overrides(dict(overlay(),STELLA_NODE_FILES_ENABLED='1',UNREVIEWED='1'))
 def test_legacy_six_and_eight_contracts_unchanged(self):
  from test_production_upgrade_contract import overrides
  n=load('node_production')
  for env in (overrides(),overlay()):self.assertEqual(n.validate_application_env_overrides(env),env)
