"""Inventory must reject metadata/file inconsistencies before any writes."""
from types import SimpleNamespace
import pytest
from scripts.import_media_objects import inventory


def test_attachment_size_mismatch_is_refused(tmp_path):
    (tmp_path/'attachments').mkdir()
    (tmp_path/'attachments'/'a').write_bytes(b'actual')
    class DB:
        calls = 0
        def execute(self, *args):
            self.calls += 1
            return SimpleNamespace(scalars=lambda: [SimpleNamespace(id='a',mime='text/plain',size=2)] if self.calls == 1 else [])
    with pytest.raises(RuntimeError, match='size mismatch'):
        inventory(DB(), tmp_path)
