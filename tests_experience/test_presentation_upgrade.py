import copy
import importlib.util
from pathlib import Path
import unittest
from typing import Any

spec = importlib.util.spec_from_file_location('presentation_upgrade', Path(__file__).resolve().parents[1] / 'deploy/experience-migration/presentation_upgrade.py')
assert spec and spec.loader
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


class PresentationUpgrade(unittest.TestCase):
    def setUp(self):
        code = dict(enabled=True, css='user-css', js='before;OLD_BRIDGE;after', timing='document_start', csp_policy='reject')
        self.old: dict[str, Any] = dict(id='a' * 32, adapter='generic', mode='isolated_proxy', background='solid', keep_alive=False,
                        origin='https://app-' + 'a' * 32 + '.example', target_id='fixed-target', name='drive',
                        request_policy={'read_post_paths': ['/api/fs/list']},
                        connection={'has_token': True}, injection={'active': {**code, 'version': 'v1'}, 'draft': copy.deepcopy(code), 'previous': None})

    def prepare(self, module=None, expected=None):
        m = module if module is not None else self.old
        return upgrade.prepare(m, expected_sha256=expected or upgrade.fingerprint(m), old_bridge='OLD_BRIDGE', new_bridge='NEW_BRIDGE')

    def test_only_explicit_presentation_fields_change(self):
        new = self.prepare()
        self.assertEqual(new['background'], 'home')
        self.assertTrue(new['keep_alive'])
        self.assertEqual(new['injection']['active']['js'], 'before;NEW_BRIDGE;after')
        self.assertEqual(new['injection']['active']['css'], 'user-css')
        self.assertEqual(new['injection']['previous'], self.old['injection']['active'])
        self.assertEqual(new['injection']['draft']['js'], new['injection']['active']['js'])
        for key in self.old:
            if key not in {'background', 'keep_alive', 'injection'}:
                self.assertEqual(new[key], self.old[key])
        self.assertEqual(self.old['background'], 'solid')

    def test_stale_snapshot_refused(self):
        changed = copy.deepcopy(self.old); changed['name'] = 'later edit'
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.prepare(changed, upgrade.fingerprint(self.old))

    def test_distinct_user_draft_refused(self):
        self.old['injection']['draft']['css'] += ' new'
        with self.assertRaisesRegex(ValueError, 'draft'): self.prepare()

    def test_missing_or_repeated_bridge_refused(self):
        for value in ['unrelated code', 'OLD_BRIDGE OLD_BRIDGE']:
            m = copy.deepcopy(self.old); m['injection']['active']['js'] = value
            with self.assertRaisesRegex(ValueError, 'exact old bridge'): self.prepare(m)

    def test_disabled_code_never_reenabled(self):
        self.old['injection']['active']['enabled'] = False
        with self.assertRaisesRegex(ValueError, 'disabled'): self.prepare()

    def test_other_transport_refused(self):
        self.old['mode'] = 'iframe'
        with self.assertRaisesRegex(ValueError, 'isolated'): self.prepare()

    def test_null_draft_stays_null(self):
        self.old['injection']['draft'] = None
        self.assertIsNone(self.prepare()['injection']['draft'])

    def test_exact_rollback(self):
        new = self.prepare()
        restored = upgrade.restore(new, expected_upgraded_sha256=upgrade.fingerprint(new), before=self.old)
        self.assertEqual(restored, self.old)
        self.assertIsNot(restored, self.old)

    def test_rollback_cannot_clobber_later_changes(self):
        new = self.prepare(); expected = upgrade.fingerprint(new); new['background'] = 'solid'
        with self.assertRaisesRegex(ValueError, 'later edits'):
            upgrade.restore(new, expected_upgraded_sha256=expected, before=self.old)


if __name__ == '__main__': unittest.main()
