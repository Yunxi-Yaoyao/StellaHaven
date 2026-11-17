"""Audited account presentation preferences; never reads/dumps browser localStorage."""
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.schemas.backups import ClientPreferences, ClientPreferencesWrite
from app.services.backup_center import Conflict


def read_preferences(engine, owner):
    with engine.connect() as conn:
        raw = conn.execute(text('SELECT value FROM app_config WHERE key=:key'), {'key': 'client-preferences:' + str(owner)}).scalar_one_or_none()
        return ClientPreferences.model_validate_json(raw).model_dump(exclude_none=True) if raw else ClientPreferences().model_dump(exclude_none=True)


def write_preferences(engine, owner, incoming):
    data = ClientPreferencesWrite.model_validate(incoming)
    key = 'client-preferences:' + str(owner)
    from app.services.homebg_references import lock_library, validate_new
    with Session(engine) as db, db.begin():
        lock_library(db)  # shared media -> account presentation row
        conn = db.connection()
        conn.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'), {'key': key})
        raw = conn.execute(text('SELECT value FROM app_config WHERE key=:key FOR UPDATE'), {'key': key}).scalar_one_or_none()
        current = ClientPreferences.model_validate_json(raw) if raw else ClientPreferences()
        if current.revision != data.expected_revision:
            raise Conflict('client preference revision changed')
        validate_new(db, data.home.bgImage, current.home.bgImage)
        # Legacy A/B clients cannot accidentally erase the one retained custom palette.
        custom = data.customAppearance if 'customAppearance' in data.model_fields_set else current.customAppearance
        value = ClientPreferences(revision=current.revision + 1, appearance=data.appearance, customAppearance=custom, home=data.home, ui=data.ui)
        conn.execute(text('INSERT INTO app_config (key,value) VALUES (:key,:value) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value'),
                     {'key': key, 'value': value.model_dump_json(exclude_none=True)})
    return read_preferences(engine, owner)
