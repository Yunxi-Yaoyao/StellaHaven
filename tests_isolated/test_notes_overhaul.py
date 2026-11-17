"""Standalone behavior tests; production bootstrap is denied by env."""
import json
import pytest
from sqlalchemy.orm import Session
from test_api_draft_contract import env


def test_preferences_upgrade_conflict_and_owner_isolation(env):
    from app.services.notes_preferences import get_preferences, patch_preferences
    from app.schemas.notes_preferences import NotesPreferencesPatch
    from fastapi import HTTPException
    with Session(env.engine) as db:
        db.add(env.models.AppConfig(key='notes-preferences:'+str(env.uid), value=json.dumps(dict(revision=2, delete_action='trash', ask_before_delete=True))))
        db.commit()
        initial = get_preferences(db, env.uid)
        assert initial['font_size'] == 16
        assert initial['hidden_folders'] == []
        changed = patch_preferences(db, env.uid, NotesPreferencesPatch(expected_revision=2, font_size=20, line_height=2, read_width=900, code_line_numbers=True, code_wrap=False, directory_sort='title', hidden_folders=[str(env.did)]))
        assert changed['revision'] == 3
        assert get_preferences(db, env.uid) == changed
        assert get_preferences(db, 'other')['font_size'] == 16
        with pytest.raises(HTTPException) as error:
            patch_preferences(db, env.uid, NotesPreferencesPatch(expected_revision=2, font_size=24))
        assert error.value.status_code == 409
        assert get_preferences(db, env.uid) == changed


def test_server_identity_and_ancestor_cascade_protection(env):
    from app.services.notes_templates import guard_protected
    from fastapi import HTTPException
    with Session(env.engine) as db:
        doc = db.get(env.models.Document, env.did)
        doc.title = '模板'
        doc.frontmatter = {'system': 'templates'}
        db.commit()
        guard_protected(db, [doc])  # Names and client frontmatter confer no privilege.
        db.add(env.models.AppConfig(key='notes-template-root:'+str(env.wid), value=str(env.did)))
        db.commit()
        with pytest.raises(HTTPException):
            env.svc.delete_document(db, env.did)
        assert db.get(env.models.Document, env.did).deleted_at is None


@pytest.mark.parametrize('fields', [dict(font_size=0), dict(line_height=8), dict(read_width=10), dict(code_wrap=None), dict(hidden_folders=['not-uuid']), dict(directory_sort='unknown')])
def test_preferences_reject_invalid_fields(env, fields):
    from app.schemas.notes_preferences import NotesPreferencesPatch
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        NotesPreferencesPatch(expected_revision=0, **fields)
