"""Execute exported editable snapshots; no DB, DNS or production imports."""
import json
import os
import subprocess
import unittest
from unittest.mock import patch
from tests_experience.test_background_bridge import HARNESS
from app.services.website_templates import export_code

PUBLIC='https://main.example'
PRIVATE='https://main.p.example'

class ExportedDualParent(unittest.TestCase):
    def run_case(self, scenario):
        with patch.dict(os.environ, {'STELLA_ENTRY_REGISTRY':json.dumps([{'service_id':'stella','public':PUBLIC,'private':PRIVATE}])}):
            code=export_code('drive', main_origin=PUBLIC)['js']
        start=code.index('/* stella:background-ready:v1 */')
        code=code[start:code.index('\n})();',start)+6]
        result=subprocess.run(['node','-e',HARNESS,json.dumps(code),scenario],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_private_ack_uses_sender_origin_and_canvas_scheme(self):self.run_case('private')
    def test_public_ack_remains_bound(self):self.run_case('ready')
    def test_similar_origins_and_wrong_window_rejected(self):self.run_case('lookalike')
    def test_bad_envelopes_do_not_change_styles(self):self.run_case('invalid')

if __name__=='__main__':unittest.main()
