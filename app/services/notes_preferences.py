"""Owner-scoped preferences. GET is strictly read-only; PATCH owns commit."""
import json
from fastapi import HTTPException
from app.models.config import AppConfig
from app.services.notes_tools import lock_key

DEFAULT = dict(revision=0, delete_action='trash', ask_before_delete=True,
               font_size=16, line_height=1.8, read_width=800, code_line_numbers=False,
               code_wrap=True, directory_sort='updated', hidden_folders=[])


def _key(owner_id):
    return 'notes-preferences:' + str(owner_id)


def get_preferences(db, owner_id):
    row = db.get(AppConfig, _key(owner_id))
    return {**DEFAULT, **(json.loads(row.value) if row else {})}


def patch_preferences(db, owner_id, data):
    try:
        key = _key(owner_id)
        # Fences absent-row creation as well as later updates on one connection.
        lock_key(db, key)
        row = db.query(AppConfig).filter(AppConfig.key == key).populate_existing().with_for_update().first()
        current = {**DEFAULT, **(json.loads(row.value) if row else {})}
        changes = data.model_dump(exclude={'expected_revision'}, exclude_unset=True)
        if all(current[name] == value for name, value in changes.items()):
            db.commit()
            return current
        if current['revision'] != data.expected_revision:
            raise HTTPException(409, {'code': 'notes_preferences_conflict', 'current': current})
        result = {**current, **changes, 'revision': current['revision'] + 1}
        if row is None:
            db.add(AppConfig(key=key, value=json.dumps(result)))
        else:
            row.value = json.dumps(result)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
