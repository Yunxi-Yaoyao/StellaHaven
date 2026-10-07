"""Public appearance choices, separate from credentials and owner custom code."""
import json
from copy import deepcopy
from fastapi import HTTPException
from app.models.config import AppConfig

KEY = 'service_appearance_v1'
DEFAULTS = {'drive': {'theme': 'stella', 'simplified': True}, 'gallery': {'logo': 'stella'}}


def check_site(site):
    if site not in DEFAULTS:
        raise HTTPException(404, '接入服务不存在')


def read(db, site):
    check_site(site)
    row = db.get(AppConfig, KEY, populate_existing=True) if db is not None else None
    value = json.loads(row.value) if row else {}
    return deepcopy(DEFAULTS[site]) | value.get(site, {})
