"""Opt-in transactional PostgreSQL state. Importing this module opens no DB.

Apply the dedicated migration before enabling STELLA_SHARED_STATE=postgres.
There is deliberately no request-time import/fallback to legacy JSON files.
All nodes must retain the same externally provisioned OIDC signing-key file.
"""
from contextlib import contextmanager
from copy import deepcopy
import os

from sqlalchemy import Column, MetaData, String, Table, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert

metadata = MetaData()
state_table = Table('ha_shared_state', metadata,
                    Column('key', String(128), primary_key=True),
                    Column('payload', JSONB, nullable=False))


def enabled():
    value = os.getenv('STELLA_SHARED_STATE', '')
    if value not in ('', 'legacy', 'postgres'):
        raise ValueError('STELLA_SHARED_STATE must be legacy or postgres')
    return value == 'postgres'


def _engine():
    from app.database import engine
    return engine


@contextmanager
def locked_state(key, default):
    """One transaction owns initialization, row lock, read, mutation and write.

    ON CONFLICT also serializes racing creation of an absent key. Never expose
    a load/modify/save API: callers must mutate only within this context.
    Exceptions roll back all mutations; DB failure never falls back to files.
    """
    engine = _engine()
    if engine.dialect.name != 'postgresql':
        raise RuntimeError('shared state requires PostgreSQL')
    with engine.begin() as conn:
        conn.execute(insert(state_table).values(key=key, payload=default)
                     .on_conflict_do_nothing(index_elements=['key']))
        state = deepcopy(conn.execute(select(state_table.c.payload)
                         .where(state_table.c.key == key).with_for_update()).scalar_one())
        yield state
        conn.execute(update(state_table).where(state_table.c.key == key).values(payload=state))
