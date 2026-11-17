"""Admission for disposable nav test PG, not a general database switch."""
import json
import os
import re
import subprocess


def target():
    if os.environ.get('STELLA_CI_OWNED_RECEIPT'):
        from deploy.ci.owned_pg import owned_target
        return owned_target()
    port = int(os.environ.get('POSTGRES_PORT', '33070'))
    database = os.environ.get('POSTGRES_DB', 'navqa')
    user = os.environ.get('POSTGRES_USER', 'navqa')
    assert os.environ.get('POSTGRES_HOST', '127.0.0.1') == '127.0.0.1'
    assert port not in {5432, 24532, 25432, 25436} and 1024 < port < 65536
    assert re.fullmatch(r'navqa(?:_[a-z0-9]{8,32})?', database) and user == database
    container = os.environ.get('NAV_PG_CONTAINER', 'stella-native-nav-qa-20261023')
    nonce = os.environ.get('NAV_PG_NONCE', '')
    assert re.fullmatch(r'[a-f0-9]{32}', nonce), 'explicit owned fixture nonce required'
    raw = subprocess.check_output(['docker', 'inspect', container], timeout=10)
    row = json.loads(raw)[0]
    assert row['State']['Running'] and row['Config']['Labels'].get('stella.navqa.nonce') == nonce
    assert row['Config']['Labels'].get('stella.navqa.purpose') == 'native-nav-tests'
    bindings = row['NetworkSettings']['Ports']['5432/tcp']
    assert bindings == [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]
    env = dict(v.split('=', 1) for v in row['Config']['Env'] if '=' in v)
    assert env.get('POSTGRES_DB') == database and env.get('POSTGRES_USER') == user
    return port, database, user, row['Id']


def verify_connection(connection, database, user):
    from sqlalchemy import text
    actual = connection.execute(text('SELECT current_database(), current_user, inet_server_addr()::text')).one()
    assert actual[0] == database and actual[1] == user and actual[2] is not None
