"""Explicit owned-target fixture; the default is None, not ambient DSN opt-in.

Only the self-provisioning launcher can supply the verified target: it checks
Docker ID/nonce/loopback binding/running PID before namespace entry. Here we
recheck that private binding and namespace, validate the exact URL BEFORE
connect, then read real SQL identity on that same connection before use.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import pytest

@pytest.fixture
def owned_target():
    """Original test execution retains its exact historical target guard."""
    return None

class OwnedTarget:
    def __init__(self):
        # Never import guard here: that would turn an arbitrary invocation into
        # implicit opt-in or load credentials outside the launcher's namespace.
        assert 'guard' in sys.modules, 'owned launcher required'
        self.guard = sys.modules['guard']
        assert Path(self.guard.__file__).resolve().parent == Path(__file__).resolve().parent
        self._binding()
        self.database = self.guard.s['db']
        self.username = self.guard.s['user']

    def _binding(self):
        g = self.guard
        binding = json.loads((g.ROOT/'binding.json').read_text())
        assert binding == {**{k:g.s[k] for k in ('id','nonce','pid','port','db','user')},
                           'netns':g.os.readlink(f'/proc/{g.s["pid"]}/ns/net')}
        assert g.os.readlink('/proc/self/ns/net') == binding['netns']
        assert binding['netns'] != g.os.readlink('/proc/1/ns/net'), 'host namespace forbidden'
        assert binding['db'] == 'stella_test_'+binding['nonce']
        assert binding['user'] == 'coverage_'+binding['nonce']
        assert binding['port'] not in {5432,24532,24533,24534}

    def validate(self, engine):
        self._binding()
        u = engine.url
        assert (u.drivername,u.host,u.port,u.database,u.username,u.password) == (
            'postgresql+psycopg2','127.0.0.1',5432,self.database,self.username,self.guard.s['password'])
        assert not u.query, 'URL overrides forbidden'

    def identity(self, connection):
        self.validate(connection.engine)
        actual = connection.exec_driver_sql(
            'select current_database(),current_user,host(inet_server_addr()),inet_server_port()').one()
        assert tuple(actual) == (self.database,self.username,'127.0.0.1',5432)

    def confirmation(self, engine):
        self.validate(engine)
        with engine.connect() as connection:
            self.identity(connection)
        return self.database

    @contextmanager
    def scope(self):
        self._binding()
        with self.guard.schema_scope() as (engine, schema):
            self.confirmation(engine)
            yield engine
