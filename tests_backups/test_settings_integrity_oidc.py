"""B01: exercise restored generations at the real PG-backed OIDC consumers."""
import copy
import json
import zipfile

import pytest
from sqlalchemy import select


def archive_settings(engine, tmp_path):
    from app.services.backup_projection import export_settings
    from app.services.backup_archive import create_archive
    path = tmp_path / 'oidc-settings.zip'
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        with export_settings(conn, tmp_path) as payload:
            create_archive(path, scope='settings', entries=payload.entries, warnings=payload.warnings)
    return path


@pytest.mark.parametrize('old_version', [None, 'nonzero-before-rotation'], ids=['legacy-zero', 'nonzero'])
@pytest.mark.parametrize('revocation', ['rotate', 'delete-recreate'])
def test_restore_never_revives_rotated_oidc_codes_or_tokens(engine, tmp_path, monkeypatch, old_version, revocation):
    from authlib.jose import JsonWebKey
    from app.services import ha_state, oidc
    from app.services.backup_projection import restore_settings
    monkeypatch.setattr(ha_state, '_engine', lambda: engine)
    private_key = tmp_path / 'synthetic-oidc-key.json'
    private_key.write_text(json.dumps(JsonWebKey.generate_key('RSA', 2048, is_private=True).as_dict(is_private=True)))
    monkeypatch.setenv('STELLA_OIDC_PRIVATE_KEY_FILE', str(private_key))
    client_id, redirect = 'integrity-fixture', 'https://fixture.invalid/callback'
    secret = 'synthetic-archived-client-secret'
    client = dict(name='Archived client', enabled=True, client_secret=secret,
                  redirect_uris=[redirect], scopes=['openid'])
    if old_version is not None:
        client['credential_version'] = old_version
    with engine.begin() as conn:
        conn.execute(ha_state.state_table.insert().values(key='oidc.clients', payload={client_id: client}))

    def code():
        return oidc.create_authorization_code(client_id, redirect, 'fixture-user', 'Fixture', '', None)

    pending_old = code()
    old_token = oidc.exchange_code(code(), client_id, secret, redirect)['access_token']
    assert oidc.userinfo(old_token) == {'sub': 'fixture-user'}
    archive = archive_settings(engine, tmp_path)
    if revocation == 'rotate':
        current_secret = oidc.rotate_client_secret(client_id)['client_secret']
    else:
        oidc.delete_client(client_id)
        current_secret = oidc.create_client(client_id, name='Recreated', redirect_uris=[redirect], scopes=['openid'])['client_secret']
    assert oidc.userinfo(old_token) is None
    assert oidc.exchange_code(pending_old, client_id, current_secret, redirect) is None
    pending_current = code()
    current_token = oidc.exchange_code(code(), client_id, current_secret, redirect)['access_token']
    assert oidc.userinfo(current_token) == {'sub': 'fixture-user'}
    with engine.connect() as conn:
        runtime_before = copy.deepcopy(conn.execute(select(ha_state.state_table.c.payload).where(
            ha_state.state_table.c.key == 'oidc.runtime')).scalar_one())
        current_version = conn.execute(select(ha_state.state_table.c.payload).where(
            ha_state.state_table.c.key == 'oidc.clients')).scalar_one()[client_id]['credential_version']
    restore_settings(engine, archive)
    with engine.connect() as conn:
        runtime_after = conn.execute(select(ha_state.state_table.c.payload).where(
            ha_state.state_table.c.key == 'oidc.runtime')).scalar_one()
        restored = conn.execute(select(ha_state.state_table.c.payload).where(
            ha_state.state_table.c.key == 'oidc.clients')).scalar_one()[client_id]
    assert runtime_after == runtime_before, 'settings must not overwrite runtime history'
    assert oidc.userinfo(old_token) is None, 'restoring old configuration must not revive revoked tokens'
    assert oidc.exchange_code(pending_old, client_id, secret, redirect) is None, 'revoked codes must stay revoked'
    assert oidc.userinfo(current_token) is None, 'configuration restore establishes a fresh credential epoch'
    assert oidc.exchange_code(pending_current, client_id, secret, redirect) is None
    assert restored['client_secret'] == secret
    assert restored['credential_version'] not in (0, old_version, current_version)
    with zipfile.ZipFile(archive) as z:
        saved = next(row['payload'] for row in json.loads(z.read('settings.json'))['shared'] if row['key'] == 'oidc.clients')
        if old_version is not None:
            assert saved[client_id]['credential_version'] == old_version
    fresh = oidc.exchange_code(code(), client_id, secret, redirect)
    assert oidc.userinfo(fresh['access_token']) == {'sub': 'fixture-user'}
    assert oidc.exchange_code(pending_old, client_id, current_secret, redirect) is None


def test_oidc_restore_uses_clients_then_runtime_locks_and_preserves_concurrent_runtime(engine, tmp_path, monkeypatch):
    import os
    from pathlib import Path
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import event, text
    from app.services import ha_state, oidc
    from app.services.backup_projection import restore_settings
    monkeypatch.setattr(ha_state, '_engine', lambda: engine)
    cid, redirect = 'lock-fixture', 'https://fixture.invalid/callback'
    oidc.create_client(cid, name='Lock fixture', redirect_uris=[redirect], scopes=['openid'])
    with ha_state.locked_state('oidc.runtime', {'codes': {}, 'tokens': {}}):
        pass
    archive = archive_settings(engine, tmp_path)
    labels, pids, trace = threading.local(), {}, []

    def record(conn, cursor, statement, parameters, context, executemany):
        label = getattr(labels, 'name', None)
        if label and 'ha_shared_state' in statement:
            pids[label] = conn.connection.driver_connection.get_backend_pid()
            keys = [v for v in parameters.values() if isinstance(v, str) and v in ('oidc.clients', 'oidc.runtime')]
            trace.extend(dict(worker=label, key=key, sql=statement) for key in keys)

    def work(label, call):
        labels.name = label
        return call()

    def wait_for_block(label, blocker):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if label in pids:
                with engine.connect() as conn:
                    row = conn.execute(text('SELECT wait_event_type, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=:pid'),
                                       {'pid': pids[label]}).one_or_none()
                if row and row[0] == 'Lock' and blocker in row[1]:
                    return dict(worker=label, pid=pids[label], wait_event_type=row[0], blockers=row[1])
            time.sleep(0.01)
        pytest.fail('expected exact owned PostgreSQL row-lock waiter was not observed')

    event.listen(engine, 'before_cursor_execute', record)
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        with ha_state.locked_state('oidc.runtime', {'codes': {}, 'tokens': {}}) as runtime:
            with engine.connect() as observer:
                holder = observer.execute(text("SELECT pid FROM pg_stat_activity WHERE state='idle in transaction' AND query LIKE '%ha_shared_state%' AND pid<>pg_backend_pid()")).scalars().all()
            assert len(holder) == 1
            runtime['concurrent-marker'] = 'must-survive-restore'
            restoring = pool.submit(work, 'restore', lambda: restore_settings(engine, archive))
            restore_wait = wait_for_block('restore', holder[0])
            rotating = pool.submit(work, 'rotate', lambda: oidc.rotate_client_secret(cid))
            rotate_wait = wait_for_block('rotate', pids['restore'])
        restoring.result(timeout=5)
        rotated = rotating.result(timeout=5)
    finally:
        pool.shutdown(wait=True)
        event.remove(engine, 'before_cursor_execute', record)
    restore_keys = list(dict.fromkeys(row['key'] for row in trace if row['worker'] == 'restore'))
    assert restore_keys == ['oidc.clients', 'oidc.runtime']
    with engine.connect() as conn:
        runtime = conn.execute(select(ha_state.state_table.c.payload).where(ha_state.state_table.c.key == 'oidc.runtime')).scalar_one()
        clients = conn.execute(select(ha_state.state_table.c.payload).where(ha_state.state_table.c.key == 'oidc.clients')).scalar_one()
    assert runtime == {'codes': {}, 'tokens': {}, 'concurrent-marker': 'must-survive-restore'}
    assert clients[cid]['client_secret'] == rotated['client_secret']
    (Path(os.environ['TMPDIR']) / 'B01-lock-observation.json').write_text(json.dumps(
        dict(restore_lock_order=restore_keys, waits=[restore_wait, rotate_wait], statements=trace,
             concurrent_runtime_preserved=True, rotation_completed=True), indent=2))


def test_oidc_restore_security_epoch_is_inside_settings_rollback_boundary(engine, tmp_path, monkeypatch):
    from app.services import ha_state, oidc
    from app.services.backup_projection import restore_settings
    monkeypatch.setattr(ha_state, '_engine', lambda: engine)
    oidc.create_client('rollback-fixture', name='Rollback', redirect_uris=['https://fixture.invalid/callback'])
    archive = archive_settings(engine, tmp_path)
    oidc.rotate_client_secret('rollback-fixture')
    with engine.connect() as conn:
        before = conn.execute(select(ha_state.state_table).order_by(ha_state.state_table.c.key)).all()
    calls = 0

    def fail_at_commit():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('injected ownership loss before commit')

    with pytest.raises(RuntimeError, match='ownership loss'):
        restore_settings(engine, archive, fence=fail_at_commit)
    assert calls == 2
    with engine.connect() as conn:
        assert conn.execute(select(ha_state.state_table).order_by(ha_state.state_table.c.key)).all() == before
