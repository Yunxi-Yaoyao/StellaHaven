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
def locked_states(defaults):
    """Lock an ordered mapping of keys/defaults on one connection/transaction.

    Callers must request shared keys in a consistent order (OIDC: clients then
    runtime). Initialize and SELECT FOR UPDATE each key before moving to the
    next: even absent-row creation therefore respects that order. Every write
    commits together; any exception rolls the whole set back. No file fallback.
    """
    engine = _engine()
    if engine.dialect.name != 'postgresql':
        raise RuntimeError('shared state requires PostgreSQL')
    with engine.begin() as conn:
        states = {}
        for key, default in defaults.items():
            conn.execute(insert(state_table).values(key=key, payload=default)
                         .on_conflict_do_nothing(index_elements=['key']))
            states[key] = deepcopy(conn.execute(select(state_table.c.payload)
                                   .where(state_table.c.key == key).with_for_update()).scalar_one())
        yield states
        for key, state in states.items():
            conn.execute(update(state_table).where(state_table.c.key == key).values(payload=state))


@contextmanager
def locked_state(key, default):
    """Single-key compatibility wrapper; mutation must stay inside the context."""
    with locked_states({key: default}) as states:
        yield states[key]
