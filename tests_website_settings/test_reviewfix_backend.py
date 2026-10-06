"""Regression coverage for independent review R2/R3/R5/R6; synthetic fixtures only."""
import pytest
from test_website_settings import upstream, api_env, checker


def test_legacy_icon_retention_does_not_allow_new_or_changed_legacy_icons(upstream, api_env):
    root, _, seen = upstream
    c, _, _, _ = api_env
    old = c.post('/external-modules', json=dict(name='Legacy', icon='heart', browser_url=root)).json()
    seen.clear()
    for icon in ('heart', 'music', 'not-a-real-icon'):
        assert c.post('/website-settings', json=dict(address=root, icon=icon, idempotency_key='restricted-' + icon)).status_code == 422
    for icon in ('music', 'not-a-real-icon'):
        assert c.patch('/website-settings/' + old['id'], json=dict(address=root, icon=icon)).status_code == 422
    assert not seen
    result = c.patch('/website-settings/' + old['id'], json=dict(address=root, icon='heart', name='Rename'))
    assert result.status_code == 200, result.text
    reread = c.get('/external-modules/' + old['id']).json()
    assert (reread['name'], reread['icon']) == ('Rename', 'heart')
    result = c.patch('/website-settings/' + old['id'], json=dict(address=root, icon='book'))
    assert result.status_code == 200, result.text
    seen.clear()
    assert c.patch('/website-settings/' + old['id'], json=dict(address=root, icon='heart')).status_code == 422
    assert not seen


def test_unknown_stored_icon_cannot_bypass_validation_via_partial_edit(upstream, api_env):
    from app.services import integrations as store
    root, _, seen = upstream
    c, factory, _, _ = api_env
    old = c.post('/external-modules', json=dict(name='Fixture', icon='book', browser_url=root)).json()
    with factory() as db:
        with store.edit(db) as config:
            config['modules'][old['id']]['icon'] = 'not-a-real-icon'
    seen.clear()
    result = c.patch('/website-settings/' + old['id'], json=dict(address=root, name='Must reject'))
    assert result.status_code == 422, result.text
    assert not seen


@pytest.mark.parametrize('css', [
    'body { color red; }',
    '@media (width > 0) { body { color red; } }',
    '@supports (display: grid) { body { color red; } }',
    '@font-face { font-family Fixture; src: url(fixture.woff2); }',
    'body { color: red; & .child { color blue; } }',
    'body { @media (width > 0) { color blue; } }',
    '@keyframes fixture { from { opacity 0; } to { opacity: 1; } }',
])
def test_css_declaration_errors_reject_without_persistent_changes(upstream, api_env, css):
    from app.models.config import AppConfig
    root, _, _ = upstream
    c, factory, _, _ = api_env
    result = c.post('/website-settings', json=dict(address=root, idempotency_key='css-declaration-error', custom=dict(enabled=True, css=css)))
    assert result.status_code == 422, result.text
    assert any('CSS' in issue for issue in result.json()['detail']['check']['issues'])
    with factory() as db:
        assert db.query(AppConfig).count() == 0


@pytest.mark.parametrize('css', [
    'body { --theme: { color red; --inner: blue }; color: var(--theme); }',
    '@media (width > 0) { body { color: red; } }',
    '@supports (display: grid) { body { display: grid; } }',
    '@font-face { font-family: Fixture; src: url(fixture.woff2); }',
    'body { color: red; & .child { color: blue; } }',
    'body { @media (width > 0) { color: blue; & .child { color: red; } } }',
    '@keyframes fixture { from { opacity: 0; } 50%, to { opacity: 1; } }',
    '@layer theme { @supports (display: grid) { body { --x: [one two]; color: var(--x); } } }',
    '@page { margin: 1cm; @top-left { content: "Fixture"; } }',
    '@font-feature-values Fixture { @styleset { nice: 1; } }',
])
def test_css_legal_nesting_custom_values_and_at_rules_remain_saveable(upstream, api_env, css):
    root, _, _ = upstream
    c, _, _, _ = api_env
    result = c.post('/website-settings', json=dict(address=root, idempotency_key='css-legal-grammar', custom=dict(enabled=True, css=css)))
    assert result.status_code == 201, result.text
    assert c.get('/external-modules/' + result.json()['id']).json()['injection']['active']['css'] == css


def test_css_recursion_budget_rejects_deep_rules():
    from app.services.website_settings import css_errors
    css = '@media (width > 0) {' * 80 + 'body { color: red; }' + '}' * 80
    assert css_errors(css)


@pytest.mark.parametrize('source,parent,status', [
    ('http://stella.test:80', 'https://stella.test', 'allowed'),
    ('http://stella.test:80', 'https://stella.test:443', 'allowed'),
    ('http://stella.test', 'https://stella.test', 'allowed'),
    ('stella.test:80', 'https://stella.test', 'allowed'),
    ('http://stella.test:8080', 'https://stella.test', 'blocked'),
    ('http://stella.test:80', 'https://stella.test:8443', 'blocked'),
    ('https://stella.test:80', 'https://stella.test', 'blocked'),
    ('https://stella.test:443', 'http://stella.test:80', 'blocked'),
    ('http://stella.test:8443', 'https://stella.test:8443', 'allowed'),
    ('http://stella.test:*', 'https://stella.test:8443', 'allowed'),
])
def test_csp_secure_upgrade_is_limited_to_default_http_port(source, parent, status):
    import httpx
    result = checker().evaluate_embedding(httpx.Headers({'content-security-policy': 'frame-ancestors ' + source}), 'http://document.test/', parent)
    assert result['status'] == status, result


def test_legacy_navigation_override_reads_without_migration_and_survives_partial_edit(upstream, api_env):
    from app.services import integrations as store
    from app.models.config import AppConfig
    root, _, _ = upstream
    c, factory, _, _ = api_env
    old = c.post('/external-modules', json=dict(name='Master old', icon='globe', browser_url=root)).json()
    mid = old['id']
    with factory() as db:
        with store.edit(db) as config:
            config['navigation'].append(dict(id=mid, title='Legacy display', icon='heart', visible=False))
        before = db.get(AppConfig, store.KEY).value
    reread = c.get('/external-modules/' + mid).json()
    assert (reread['name'], reread['icon']) == ('Legacy display', 'heart')
    listed = next(m for m in c.get('/external-modules').json() if m['id'] == mid)
    assert (listed['name'], listed['icon']) == ('Legacy display', 'heart')
    nav = next(e for e in c.get('/navigation').json()['entries'] if e['id'] == mid)
    assert (nav['title'], nav['icon'], nav['visible']) == ('Legacy display', 'heart', False)
    with factory() as db:
        assert db.get(AppConfig, store.KEY).value == before  # GET does not migrate/write.
    result = c.patch('/website-settings/' + mid, json=dict(address=root + '/edited'))
    assert result.status_code == 200, result.text
    assert (result.json()['name'], result.json()['icon']) == ('Legacy display', 'heart')
    with factory() as db:
        config = store.state(db)
        module = config['modules'][mid]
        override = next(e for e in config['navigation'] if e['id'] == mid)
        assert (module['name'], module['icon']) == (override['title'], override['icon']) == ('Legacy display', 'heart')
        assert override['visible'] is False
    result = c.patch('/website-settings/' + mid, json=dict(address=root, name='Explicit edit', icon='book'))
    assert result.status_code == 200, result.text
    reread = c.get('/external-modules/' + mid).json()
    nav = next(e for e in c.get('/navigation').json()['entries'] if e['id'] == mid)
    assert (reread['name'], reread['icon']) == (nav['title'], nav['icon']) == ('Explicit edit', 'book')


def test_invalid_legacy_display_overrides_never_enter_module_editor(upstream, api_env):
    from app.services import integrations as store
    root, _, _ = upstream
    c, factory, _, _ = api_env
    old = c.post('/external-modules', json=dict(name='Master', icon='book', browser_url=root)).json()
    with factory() as db:
        with store.edit(db) as config:
            config['navigation'].append(dict(id=old['id'], title='', icon='unknown-persisted'))
    reread = c.get('/external-modules/' + old['id']).json()
    assert (reread['name'], reread['icon']) == ('Master', 'book')


def test_legacy_override_changed_during_check_is_not_overwritten(upstream, api_env, monkeypatch):
    from app.services import integrations as store, website_settings
    root, _, _ = upstream
    c, factory, _, _ = api_env
    old = c.post('/external-modules', json=dict(name='Master', icon='book', browser_url=root)).json()
    mid = old['id']
    with factory() as db:
        with store.edit(db) as config:
            config['navigation'].append(dict(id=mid, title='Old override', icon='heart', visible=True))
    real = website_settings.check_draft
    async def concurrent_override(*args, **kwargs):
        result = await real(*args, **kwargs)
        with factory() as db:
            with store.edit(db) as config:
                config['navigation'][0].update(title='Concurrent override')
        return result
    monkeypatch.setattr(website_settings, 'check_draft', concurrent_override)
    result = c.patch('/website-settings/' + mid, json=dict(address=root + '/edited'))
    assert result.status_code == 409, result.text
    assert c.get('/external-modules/' + mid).json()['name'] == 'Concurrent override'


def test_http_custom_delivery_uses_https_isolated_proxy_without_mixed_content(upstream, api_env, monkeypatch):
    from app.services import integrations as store
    root, _, seen = upstream
    c, factory, _, _ = api_env
    monkeypatch.setenv('STELLA_MAIN_ORIGIN', 'https://stella.test')
    checked = c.post('/website-settings/check', json=dict(address=root + '/custom', custom_enabled=True))
    assert checked.status_code == 200, checked.text
    result = checked.json()
    assert result['injection']['status'] == 'supported'
    assert result['embedding']['status'] == 'allowed', result
    assert result['embedding']['reason_code'] == 'isolated_https_proxy'
    assert result['can_save'] is True
    payload = dict(address=root + '/custom', idempotency_key='https-delivery-http-upstream', custom=dict(enabled=True, css='body{color:red}'))
    saved = c.post('/website-settings', json=payload)
    assert saved.status_code == 201, saved.text
    module = saved.json()
    assert module['mode'] == 'isolated_proxy' and module['origin'].startswith('https://')
    assert c.get('/external-modules/' + module['id']).json()['injection']['active']['css'] == 'body{color:red}'
    with factory() as db:
        target = store.state(db)['targets'][module['target_id']]
        assert target['upstream_url'] == root + '/'
        assert target['allowed_ips'] == ['127.0.0.1']
        assert target['headers'] == {} and target['controlled'] is False
    assert all(not any(k.lower() in {'cookie', 'authorization', 'referer'} for k in headers) for _, headers in seen)


@pytest.mark.parametrize('headers,body,custom_enabled,reason', [
    ([], b'<html/>', False, 'mixed_content'),
    ([('Content-Security-Policy', "frame-ancestors 'none'")], b'<html/>', True, 'csp_frame_ancestors'),
    ([('X-Frame-Options', 'DENY')], b'<html/>', True, 'xfo_deny'),
    ([], b'<meta http-equiv="content-security-policy" content="default-src self">', True, 'mixed_content'),
])
def test_http_not_safe_for_proxy_stays_blocked_without_writes(upstream, api_env, monkeypatch, headers, body, custom_enabled, reason):
    from app.models.config import AppConfig
    root, responses, _ = upstream
    c, factory, _, _ = api_env
    monkeypatch.setenv('STELLA_MAIN_ORIGIN', 'https://stella.test')
    responses['/restricted'] = (200, [('Content-Type', 'text/html')] + headers, body)
    result = c.post('/website-settings/check', json=dict(address=root + '/restricted', custom_enabled=custom_enabled)).json()
    assert result['embedding']['status'] == 'blocked'
    assert result['embedding']['reason_code'] == reason
    assert result['can_save'] is False
    saved = c.post('/website-settings', json=dict(address=root + '/restricted', idempotency_key='restricted-http-delivery', custom=dict(enabled=custom_enabled, css='body{color:red}')))
    assert saved.status_code == 422, saved.text
    with factory() as db:
        assert db.query(AppConfig).count() == 0
