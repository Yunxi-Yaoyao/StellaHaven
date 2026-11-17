"""Deterministic real projection outputs shared with frontend contract tests."""
from app.public_website import public_module, public_navigation, public_website_result
from tests_public_website.test_projection import module, version, checked


def contract_fixture():
    raw = module() | dict(template_id='user_' + 'a' * 32, background='home', keep_alive=True,
                         request_policy=dict(management_prefixes=['/admin'], read_post_paths=['/api/list'], protect_other_writes=True))
    raw['injection'] = {slot: version() for slot in ('draft', 'active', 'previous')}
    raw['connection'] = dict(transport='proxy', auth_mode='header', header_name='Authorization',
                             injection_delivery='proxy', has_token=True, token='synthetic-private-token')
    raw['private'] = {'secret': 'synthetic-module-extension'}
    saved = public_website_result(raw, checked())
    malformed = public_module(raw | {'name': {'secret': 'synthetic-invalid-name'}, 'keep_alive': 'false'})
    navigation = public_navigation(dict(modules={'legacy-id': raw}, navigation=[
        dict(id='home', title='My Home', icon='globe', route='https://evil.test', builtin=False),
        dict(id='legacy-id', visible=False)], legacy_routes={'drive': 'legacy-id'}),
        [dict(id='home', title='Home', icon='home', route='/')])
    return dict(saved=saved, malformed=malformed, navigation=navigation)
