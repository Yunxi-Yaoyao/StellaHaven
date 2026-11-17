"""Retention boundary extensions; real routers/SQLite/owned loopback, never PG."""
import copy
from contextlib import contextmanager

import pytest
from tests_website_settings.test_website_settings import api_env, upstream
from tests_website_settings.test_retention_independent_oracle import setup, snapshot, legacy_probe


def database_snapshot(factory):
    from app.models.config import AppConfig
    with factory() as db:
        return {row.key: row.value for row in db.query(AppConfig).all()}


def seed_capabilities(factory, mid):
    from app.services import integrations as store
    with factory() as db:
        with store.edit(db) as cfg:
            # Nonempty synthetic rows; never submitted to real launch/bootstrap.
            cfg['tickets']['fixture-ticket'] = dict(id=mid, fixture_marker='ticket')
            cfg['grants']['fixture-grant'] = dict(id=mid, fixture_marker='grant')


@contextmanager
def writes(factory):
    from sqlalchemy import event
    statements = []
    engine = factory.kw['bind']
    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE', 'REPLACE'}:
            statements.append(statement)
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        yield statements
    finally:
        event.remove(engine, 'before_cursor_execute', observe)


@pytest.mark.parametrize('transport', ['direct', 'proxy'])
@pytest.mark.parametrize('field', ['access_adapter', 'request_policy', 'policy_null'])
def test_explicit_equal_effective_authority_is_retained(api_env, upstream, monkeypatch, transport, field):
    from app.services import integrations as store, website_policy
    c, f, mid, before, payload, _, seen = setup(api_env, upstream, monkeypatch, transport)
    policy = dict(management_prefixes=['/admin'], read_post_paths=['/search'], protect_other_writes=True)
    with f() as db:
        with store.edit(db) as cfg:
            cfg['modules'][mid].update(access_adapter='immich', request_policy=policy)
    old = snapshot(f)
    addition = {'request_policy': None} if field == 'policy_null' else {field: old['modules'][mid][field]}
    seen.clear()
    response = c.patch('/website-settings/' + mid, json=payload | addition)
    assert response.status_code == 200, response.text
    current = snapshot(f)
    assert current['targets'] == old['targets']
    assert current['tickets'] == old['tickets'] and current['grants'] == old['grants']
    for key in ('request_policy', 'access_adapter', 'connection', 'private_address', 'browser_url', 'mode', 'origin', 'target_id', 'initial_path'):
        assert current['modules'][mid][key] == old['modules'][mid][key], key
    assert website_policy.management_required(current['modules'][mid], 'POST', '/admin/delete') is True
    assert seen == []


@pytest.mark.parametrize('field', ['access_adapter', 'management_prefixes', 'read_post_paths', 'protect_other_writes'])
def test_effective_authority_change_rejected_before_any_dml(api_env, upstream, monkeypatch, field):
    from app.services import integrations as store
    c, f, mid, before, payload, _, seen = setup(api_env, upstream, monkeypatch)
    policy = dict(management_prefixes=['/admin'], read_post_paths=['/search'], protect_other_writes=True)
    with f() as db:
        with store.edit(db) as cfg:
            cfg['modules'][mid].update(access_adapter='generic', request_policy=policy)
    seed_capabilities(f, mid)
    old = snapshot(f)
    all_before = database_snapshot(f)
    changed = copy.deepcopy(policy)
    if field == 'access_adapter':
        addition = {field: 'immich'}
    else:
        changed[field] = False if field == 'protect_other_writes' else []
        addition = {'request_policy': changed}
    seen.clear()
    with writes(f) as statements:
        response = c.patch('/website-settings/' + mid, json=payload | addition)
    assert response.status_code == 422, response.text
    assert snapshot(f) == old
    assert database_snapshot(f) == all_before
    assert statements == []
    assert seen == []


@pytest.mark.parametrize('auth', ['original', 'header'])
@pytest.mark.parametrize('fault', ['missing', 'dns_pin', 'controlled', 'upstream', 'extra_header',
                                  'missing_id', 'wrong_id', 'missing_name', 'missing_headers',
                                  'missing_ips', 'empty_ips', 'missing_controlled', 'bad_controlled'])
def test_retained_proxy_target_must_be_complete_exact_and_never_recreated(api_env, upstream, monkeypatch, auth, fault):
    from app.services import integrations as store
    c, f, mid, before, payload, _, seen = setup(api_env, upstream, monkeypatch, auth=auth)
    with f() as db:
        with store.edit(db) as cfg:
            tid = cfg['modules'][mid]['target_id']
            target = cfg['targets'][tid]
            if fault == 'missing':
                del cfg['targets'][tid]
            elif fault == 'dns_pin': target['allowed_ips'] = ['127.0.0.2']
            elif fault == 'controlled': target['controlled'] = True
            elif fault == 'upstream': target['upstream_url'] = target['upstream_url'].replace('127.0.0.1', '127.0.0.2')
            elif fault == 'extra_header': target['headers']['x-auth-token'] = 'synthetic-extra'
            elif fault == 'wrong_id': target['id'] = 'wrong-fixture-target'
            elif fault == 'empty_ips': target['allowed_ips'] = []
            elif fault == 'bad_controlled': target['controlled'] = 'false'
            else:
                key = {'missing_id': 'id', 'missing_name': 'name', 'missing_headers': 'headers',
                       'missing_ips': 'allowed_ips', 'missing_controlled': 'controlled'}[fault]
                del target[key]
    seed_capabilities(f, mid)
    old = snapshot(f)
    all_before = database_snapshot(f)
    seen.clear()
    with writes(f) as statements:
        response = c.patch('/website-settings/' + mid, json=payload)
    assert response.status_code == 422, response.text
    assert snapshot(f) == old
    assert database_snapshot(f) == all_before
    assert statements == []
    if fault not in {'controlled', 'extra_header'}:
        assert seen == []


@pytest.mark.parametrize('auth', ['original', 'header'])
@pytest.mark.parametrize('historical_path', [False, True])
def test_header_free_and_credentialled_exact_targets_are_reused(api_env, upstream, monkeypatch, auth, historical_path):
    from app.services import integrations as store
    c, f, mid, before, payload, _, seen = setup(api_env, upstream, monkeypatch, auth=auth)
    if historical_path:
        with f() as db:
            with store.edit(db) as cfg:
                cfg['modules'][mid]['initial_path'] = '/historical-entry?q=original#kept'
    seed_capabilities(f, mid)
    old = snapshot(f)
    seen.clear()
    response = c.patch('/website-settings/' + mid, json=payload | {'custom': dict(enabled=False, css='body{color:teal}')})
    assert response.status_code == 200, response.text
    current = snapshot(f)
    assert current['targets'] == old['targets']
    assert current['modules'][mid]['target_id'] == old['modules'][mid]['target_id']
    for key in ('initial_path', 'connection', 'request_policy', 'origin', 'private_address'):
        assert current['modules'][mid][key] == old['modules'][mid][key], key
    assert current['tickets'] == old['tickets'] and current['grants'] == old['grants']
    assert seen == []


@pytest.mark.parametrize('change', ['visible', 'title', 'icon', 'remove', 'insert', 'move',
                                   'duplicate', 'extension', 'remove_visible', 'null_title'])
def test_late_navigation_writer_full_row_and_position_cas(api_env, upstream, monkeypatch, change):
    from app.services import integrations as store, website_settings as service
    c, f, mid, before, payload, _, seen = setup(api_env, upstream, monkeypatch)
    with f() as db:
        with store.edit(db) as cfg:
            cfg['navigation'].append(dict(id='notes', title='Sibling', icon='file-text', visible=True))
            if change == 'insert': cfg['navigation'] = [row for row in cfg['navigation'] if row['id'] != mid]
    seed_capabilities(f, mid)
    legacy_probe(f)
    expected = []
    all_expected = []
    real = service.check_draft
    async def late_writer(*args, **kwargs):
        checked = await real(*args, **kwargs)
        with f() as db:
            with store.edit(db) as cfg:
                nav = next((row for row in cfg['navigation'] if row['id'] == mid), None)
                if change == 'visible': nav['visible'] = False
                elif change == 'title': nav['title'] = 'Late title'
                elif change == 'icon': nav['icon'] = 'heart'
                elif change == 'remove': cfg['navigation'].remove(nav)
                elif change == 'insert': cfg['navigation'].insert(0, dict(id=mid, title=before['name'], icon=before['icon'], visible=True))
                elif change == 'move': cfg['navigation'].remove(nav); cfg['navigation'].append(nav)
                elif change == 'duplicate': cfg['navigation'].append(copy.deepcopy(nav))
                elif change == 'extension': nav['fixture_extension'] = {'late': True}
                elif change == 'remove_visible': del nav['visible']
                elif change == 'null_title': nav['title'] = None
        expected.append(snapshot(f))
        all_expected.append(database_snapshot(f))
        return checked
    monkeypatch.setattr(service, 'check_draft', late_writer)
    response = c.patch('/website-settings/' + mid, json=payload)
    assert response.status_code == 409, response.text
    assert len(expected) == 1
    assert snapshot(f) == expected[0], 'Preserve full module, targets, navigation, tickets and writer state'
    assert database_snapshot(f) == all_expected[0], 'No save-key or audit writes on conflict'


@pytest.mark.parametrize('change', ['sibling_fields', 'append_sibling', 'reorder_other_siblings'])
def test_unrelated_navigation_writer_does_not_conflict(api_env, upstream, monkeypatch, change):
    from app.services import integrations as store, website_settings as service
    c, f, mid, before, payload, _, _ = setup(api_env, upstream, monkeypatch)
    with f() as db:
        with store.edit(db) as cfg:
            cfg['navigation'].extend([dict(id='notes', title='Sibling', icon='file-text', visible=True),
                                      dict(id='settings', title='Settings', icon='settings', visible=True)])
    legacy_probe(f)
    expected = []
    real = service.check_draft
    async def late_writer(*args, **kwargs):
        checked = await real(*args, **kwargs)
        with f() as db:
            with store.edit(db) as cfg:
                if change == 'sibling_fields': cfg['navigation'][1].update(title='Late sibling', visible=False, icon='heart')
                elif change == 'append_sibling': cfg['navigation'].append(dict(id='status', title='Late status', visible=False))
                else: cfg['navigation'][1:] = reversed(cfg['navigation'][1:])
        expected.append(snapshot(f))
        return checked
    monkeypatch.setattr(service, 'check_draft', late_writer)
    response = c.patch('/website-settings/' + mid, json=payload)
    assert response.status_code == 200, response.text
    current = snapshot(f)
    assert [row for row in current['navigation'] if row['id'] != mid] == [row for row in expected[0]['navigation'] if row['id'] != mid]
    assert current['targets'] == expected[0]['targets']
    assert current['tickets'] == expected[0]['tickets'] and current['grants'] == expected[0]['grants']


@pytest.mark.parametrize('stage', ['initial_read', 'locked_recheck'])
def test_cached_session_reads_actual_store_in_both_phases(api_env, upstream, monkeypatch, stage):
    from app.database import get_db
    from app.models.config import AppConfig
    from app.services import integrations as store, website_settings as service
    c, f, mid, before, payload, _, _ = setup(api_env, upstream, monkeypatch)
    _, _, app, _ = api_env
    seed_capabilities(f, mid)
    legacy_probe(f)
    real = service.check_draft
    expected = []
    all_expected = []
    with f() as session:
        # Strong reference keeps the actual identity-map row alive.
        cached = [session.get(AppConfig, store.KEY)]
        def database():
            try: yield session
            finally: session.rollback()
        app.dependency_overrides[get_db] = database
        def write():
            with f() as db:
                with store.edit(db) as cfg:
                    next(row for row in cfg['navigation'] if row['id'] == mid)['visible'] = False
            expected.append(snapshot(f))
            all_expected.append(database_snapshot(f))
        if stage == 'initial_read':
            write()
        else:
            async def after_probe(*args, **kwargs):
                checked = await real(*args, **kwargs)
                # Rehydrate the old row after save_website's initial rollback,
                # then make a second session write while this copy stays cached.
                cached.append(session.get(AppConfig, store.KEY))
                assert cached[-1] is cached[0]
                write()
                assert cached[-1].value != all_expected[-1][store.KEY]
                return checked
            monkeypatch.setattr(service, 'check_draft', after_probe)
        response = c.patch('/website-settings/' + mid, json={'address': before['browser_url']})
    assert response.status_code == (200 if stage == 'initial_read' else 409), response.text
    current = snapshot(f)
    if stage == 'locked_recheck':
        assert database_snapshot(f) == all_expected[-1]
    else:
        assert next(row for row in current['navigation'] if row['id'] == mid)['visible'] is False
        assert current['modules'][mid] == expected[-1]['modules'][mid]
        for key in ('targets', 'tickets', 'grants'):
            assert current[key] == expected[-1][key]
