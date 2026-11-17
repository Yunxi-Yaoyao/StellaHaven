"""Independent repeat of the upgraded original browser ID, not extra business coverage."""
from tests.test_notes_zip_browser import test_real_browser_zip_template_roundtrip as _original

def test_current_more_menu_zip_template_roundtrip(db_session,monkeypatch,tmp_path):
    _original(db_session,monkeypatch,tmp_path)
