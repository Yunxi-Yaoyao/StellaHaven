"""Run only inside the OS read-only filesystem/private-net runner."""
import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.unified_root_fixture

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('old_installer_cases', ROOT / 'tests_isolated/test_agent_installer.py')
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)


class TestRootInstaller(old.LinuxInstances):
    def setUp(self):
        # Session autouse admission verifies either the real readonly/private-net
        # fixture or the exact CI parent-owned nonce/overlay before this writer.
        from tests_agent_unified.conftest import require_os_fixture
        require_os_fixture()
        super().setUp()

    def install(self, *args, **kwargs):
        result = super().install(*args, **kwargs)
        if result.returncode == 0:
            for unit in (self.root / 'etc/systemd/system').glob('*.service'):
                text = unit.read_text()
                self.assertIn('\nUser=root\n', text, 'new Linux Agent must own its root child')
                self.assertIn('\nKillMode=control-group\n', text)
                self.assertIn('\nTimeoutStopSec=10\n', text)
                self.assertNotIn('ProtectHome=', text)
                self.assertNotIn('ProtectSystem=', text)
                iid = unit.stem.removeprefix('stella-agent-')
                source = self.root / 'opt/stella-agents' / iid / 'stella_agent.py'
                self.assertEqual((source.stat().st_uid, source.parent.stat().st_uid), (0, 0))
                self.assertNotIn(old.TOKEN, text)
            self.assertFalse(list((self.root/'etc/systemd/system').glob('stella-files-*')))
        return result

    def test_existing_owned_nonroot_instance_transitions_to_root(self):
        self.assertEqual(self.install().returncode, 0)
        unit = self.root / 'etc/systemd/system' / ('stella-agent-' + old.instance_id(old.CENTER_A) + '.service')
        unit.write_text(unit.read_text().replace('User=root\n', 'User=sta' + old.instance_id(old.CENTER_A) + '\n'))
        source = self.code() / 'stella_agent.py'
        os.chown(source, 65001, 65001); os.chown(source.parent, 65001, 65001)
        self.assertEqual(self.install().returncode, 0)
        self.assertIn('User=root\n', unit.read_text())
