"""Offline service/HA security regressions; no settings, network or production DB.

The bounded-pool adapter below emulates SQL/row locks, not PostgreSQL itself.
Real disposable-PostgreSQL acceptance remains a separate explicit proof.
"""
import copy
import socket
import sqlite3
import sys
import threading
import types
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from sqlalchemy.pool import QueuePool
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.selectable import Select

from tests_isolated.test_oidc_provider import api, oidc, storage


@pytest.fixture(autouse=True)
def offline_modules(monkeypatch):
    """Bypass eager service/router imports without loading settings or main."""
    before = {name: module for name, module in sys.modules.items()
              if name == 'app' or name.startswith('app.')}
    attrs = {name: dict(module.__dict__) for name, module in before.items()}
    try:
        with monkeypatch.context() as patch:
            import app
            root = Path(__file__).resolve().parents[1]
            for name, relative in [('app.services', 'app/services'), ('app.routers', 'app/routers')]:
                namespace = types.ModuleType(name)
                namespace.__path__ = [str(root / relative)]
                patch.setitem(sys.modules, name, namespace)
                patch.setattr(app, name.rsplit('.', 1)[1], namespace, raising=False)
            for name in ('STELLA_HA_STATE_PG_TEST', 'STELLA_SHARED_STATE', 'STELLA_OIDC_PRIVATE_KEY_FILE'):
                patch.delenv(name, raising=False)
            def deny_network(*args, **kwargs):
                raise AssertionError('offline security test: TCP forbidden')
            patch.setattr(socket.socket, 'connect', deny_network)
            yield
    finally:
        for name in list(sys.modules):
            if (name == 'app' or name.startswith('app.')) and name not in before:
                del sys.modules[name]
        sys.modules.update(before)
        for name, module in before.items():
            for key, value in list(module.__dict__.items()):
                if isinstance(value, types.ModuleType) and value.__name__.startswith('app.') and key not in attrs[name]:
                    delattr(module, key)
            for key, value in attrs[name].items():
                if isinstance(value, types.ModuleType) and value.__name__.startswith('app.'):
                    setattr(module, key, value)


@pytest.fixture
def bounded_state(oidc, monkeypatch):
    """Actual ha_state transactions + real finite pool, emulated SQL/row locks."""
    from app.services import ha_state
    pool = QueuePool(lambda: sqlite3.connect(':memory:', check_same_thread=False),
                     pool_size=2, max_overflow=0, timeout=.2)
    backend = types.SimpleNamespace(payloads={}, checkouts=[], locks=[],
                                    schedule=False, fail_update=None,
                                    holder_ready=threading.Event(), waiter_ready=threading.Event())
    row_locks = {}
    registry_lock = threading.Lock()

    class Result:
        def __init__(self, value=None):
            self.value = value

        def scalar_one(self):
            return copy.deepcopy(self.value)

    class Connection:
        def __init__(self):
            self.held = {}
            self.pending = {}

        def execute(self, statement):
            params = statement.compile().params
            key = params.get('key', params.get('key_1'))
            if isinstance(statement, Insert):
                with registry_lock:
                    row_lock = row_locks.setdefault(key, threading.RLock())
                name = threading.current_thread().name
                if backend.schedule and key == 'oidc.clients' and name.startswith('pool-waiter'):
                    backend.waiter_ready.set()
                if key not in self.held:
                    row_lock.acquire()
                    self.held[key] = row_lock
                    backend.locks.append((name, key))
                if backend.schedule and key == 'oidc.clients' and name.startswith('pool-holder'):
                    backend.holder_ready.set()
                    assert backend.waiter_ready.wait(3), 'waiter did not occupy second slot'
                if key not in backend.payloads:
                    self.pending[key] = copy.deepcopy(params['payload'])
                return Result()
            if isinstance(statement, Select):
                assert key in self.held, 'read without row lock'
                return Result(self.pending.get(key, backend.payloads.get(key)))
            if isinstance(statement, Update):
                assert key in self.held, 'write without row lock'
                if backend.fail_update == key:
                    raise RuntimeError('synthetic state write failure')
                self.pending[key] = copy.deepcopy(params['payload'])
                return Result()
            raise AssertionError(type(statement))

    class Engine:
        dialect = types.SimpleNamespace(name='postgresql')

        @contextmanager
        def begin(self):
            raw = pool.connect()
            backend.checkouts.append(threading.current_thread().name)
            conn = Connection()
            try:
                yield conn
            except BaseException:
                raise
            else:
                backend.payloads.update(conn.pending)
            finally:
                for row_lock in reversed(list(conn.held.values())):
                    row_lock.release()
                raw.close()

    monkeypatch.setattr(ha_state, '_engine', lambda: Engine())
    monkeypatch.setenv('STELLA_SHARED_STATE', 'postgres')
    monkeypatch.setattr(oidc, '_sign_id_token', lambda *a, **kw: 'signed')
    try:
        yield backend
    finally:
        assert pool.checkedout() == 0
        pool.dispose()


@pytest.mark.parametrize('verifier', ['v' * 43, ''])
def test_unbound_code_rejects_supplied_verifier_without_consumption(storage, monkeypatch, verifier):
    monkeypatch.setattr(storage, '_sign_id_token', lambda *a, **kw: 'signed')
    secret = storage.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])['client_secret']
    code = storage.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Owner', '', None)
    assert storage.exchange_code(code, 'rp', secret, 'https://rp.test/cb', code_verifier=verifier) is None
    with storage._shared_state() as state:
        assert code in state['codes']
        assert state['tokens'] == {}
    # Existing confidential-client flows that supply neither field still work.
    assert storage.exchange_code(code, 'rp', secret, 'https://rp.test/cb')['access_token']


def test_http_unbound_code_with_verifier_returns_invalid_grant(api, oidc):
    secret = oidc.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])['client_secret']
    code = oidc.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Owner', '', None)
    payload = {'grant_type': 'authorization_code', 'client_id': 'rp', 'client_secret': secret,
               'code': code, 'redirect_uri': 'https://rp.test/cb', 'code_verifier': 'v' * 43}
    result = api.client.post('/oauth/token', data=payload)
    assert result.status_code == 400 and result.json() == {'error': 'invalid_grant'}
    payload.pop('code_verifier')
    assert api.client.post('/oauth/token', data=payload).status_code == 200


@pytest.mark.parametrize('operation', ['issue', 'exchange', 'userinfo'])
def test_lifecycle_uses_one_checkout_when_client_waiter_fills_pool(oidc, bounded_state, operation):
    backend = bounded_state
    secret = oidc.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])['client_secret']
    code = oidc.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Owner', '', None)
    backend.checkouts.clear()
    backend.locks.clear()
    backend.schedule = True

    def holder():
        if operation == 'issue':
            return oidc.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Owner', '', None)
        if operation == 'exchange':
            return oidc.exchange_code(code, 'rp', secret, 'https://rp.test/cb')
        # Public userinfo reaches the same lock path even with a garbage token.
        return oidc.userinfo('not-a-token')

    def waiter():
        assert backend.holder_ready.wait(3)
        return oidc.list_clients()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='pool-holder') as holders, \
         ThreadPoolExecutor(max_workers=1, thread_name_prefix='pool-waiter') as waiters:
        result = holders.submit(holder)
        waiting = waiters.submit(waiter)
        value = result.result(timeout=5)
        assert len(waiting.result(timeout=5)) == 1
    assert (value is None) if operation == 'userinfo' else bool(value)
    assert len([n for n in backend.checkouts if n.startswith('pool-holder')]) == 1
    assert [key for name, key in backend.locks if name.startswith('pool-holder')] == ['oidc.clients', 'oidc.runtime']
    assert not oidc.CLIENT_FILE.exists() and not (oidc.OIDC_DIR / 'runtime').exists()


def test_invalid_legacy_client_does_not_initialize_runtime(oidc):
    assert oidc.exchange_code('unknown', 'unknown', 'wrong', 'https://rp.test/cb') is None
    with pytest.raises(ValueError, match='invalid_client'):
        oidc.create_authorization_code('unknown', 'https://rp.test/cb', 'owner', 'Owner', '', None)
    assert not (oidc.OIDC_DIR / 'runtime').exists()


@pytest.mark.parametrize('failed_key', ['oidc.clients', 'oidc.runtime'])
def test_exchange_rolls_back_code_token_and_usage_together(oidc, bounded_state, failed_key):
    secret = oidc.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])['client_secret']
    code = oidc.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Owner', '', None)
    before = copy.deepcopy(bounded_state.payloads)
    bounded_state.fail_update = failed_key
    with pytest.raises(RuntimeError, match='synthetic state write failure'):
        oidc.exchange_code(code, 'rp', secret, 'https://rp.test/cb')
    assert bounded_state.payloads == before
    assert code in bounded_state.payloads['oidc.runtime']['codes']
    assert bounded_state.payloads['oidc.runtime']['tokens'] == {}
    assert 'last_used_at' not in bounded_state.payloads['oidc.clients']['rp']
    bounded_state.fail_update = None
    result = oidc.exchange_code(code, 'rp', secret, 'https://rp.test/cb')
    assert code not in bounded_state.payloads['oidc.runtime']['codes']
    assert result['access_token'] in bounded_state.payloads['oidc.runtime']['tokens']
    assert bounded_state.payloads['oidc.clients']['rp']['last_used_at']


def test_locked_states_rolls_back_initialization_and_caller_mutation(oidc, bounded_state):
    from app.services import ha_state
    defaults = {'oidc.clients': {}, 'oidc.runtime': {'codes': {}, 'tokens': {}}}
    with pytest.raises(RuntimeError, match='caller rollback'):
        with ha_state.locked_states(defaults) as states:
            states['oidc.clients']['temporary'] = {'name': 'uncommitted'}
            states['oidc.runtime']['codes']['temporary'] = {'expires': 0}
            raise RuntimeError('caller rollback')
    assert bounded_state.payloads == {}
    assert defaults == {'oidc.clients': {}, 'oidc.runtime': {'codes': {}, 'tokens': {}}}
    assert len(bounded_state.checkouts) == 1
    assert [key for _, key in bounded_state.locks] == list(defaults)
    # Existing single-row consumers use the same transactional implementation.
    with ha_state.locked_state('smtp.config', {}) as state:
        state['host'] = 'synthetic.test'
    assert bounded_state.payloads == {'smtp.config': {'host': 'synthetic.test'}}


def test_concurrent_exchange_consumes_code_once_with_one_checkout_each(oidc, bounded_state):
    secret = oidc.create_client('rp', name='RP', redirect_uris=['https://rp.test/cb'])['client_secret']
    code = oidc.create_authorization_code('rp', 'https://rp.test/cb', 'owner', 'Owner', '', None)
    bounded_state.checkouts.clear()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: oidc.exchange_code(code, 'rp', secret, 'https://rp.test/cb'), range(8)))
    assert len([value for value in results if value]) == 1
    assert len(bounded_state.checkouts) == 8
    assert len(bounded_state.payloads['oidc.runtime']['tokens']) == 1
    assert code not in bounded_state.payloads['oidc.runtime']['codes']
