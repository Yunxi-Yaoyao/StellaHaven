"""Offline contract tests: never import main, database, settings or business routers."""
import importlib.util
import ast
import copy
import sys
from pathlib import Path
from collections import Counter

import pytest

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def contract_module():
    path = ROOT / 'app/openapi_contract.py'
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location('stella_contract_under_test', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def install(app):
    contract = contract_module()
    if contract is not None:
        contract.install_openapi_contract(app)
    return contract


def test_operation_ids_are_per_method_path_stable_without_routing_changes():
    def build(reverse=False):
        app = FastAPI()
        router = APIRouter(prefix='/nested')

        async def handler(request: Request):
            return {'method': request.method}

        paths = ['/a-b/{item}', '/a_b/{item}', '/files/{path:path}']
        for path in reversed(paths) if reverse else paths:
            router.add_api_route(path, handler, methods=['GET', 'POST', 'HEAD'], name='same')
        app.include_router(router, prefix='/v1')
        install(app)
        return app, router

    app, router = build()
    before = [(r.path, r.methods.copy(), r.endpoint, r.operation_id, r.unique_id) for r in router.routes]
    client = TestClient(app)
    assert client.post('/v1/nested/a-b/one').json() == {'method': 'POST'}
    schema = app.openapi()
    ids = {(path, method): operation['operationId'] for path, value in schema['paths'].items()
           for method, operation in value.items()}
    assert len(set(ids.values())) == len(ids), ids
    assert before == [(r.path, r.methods, r.endpoint, r.operation_id, r.unique_id) for r in router.routes]
    assert str(app.url_path_for('same', item='one')) == '/v1/nested/a-b/one'
    assert client.get('/v1/nested/a-b/one').json() == {'method': 'GET'}
    other, _ = build(reverse=True)
    assert ids == {(path, method): operation['operationId'] for path, value in other.openapi()['paths'].items()
                   for method, operation in value.items()}
    assert app.openapi() is schema


def source_dependency(module, name, namespace):
    """Compile the actual signature/Depends AST, never its business body/imports."""
    tree = ast.parse((ROOT / (module.replace('.', '/') + '.py')).read_text())
    node = copy.deepcopy(next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name))
    node.decorator_list = []
    node.returns = None
    for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
        if not (isinstance(arg.annotation, ast.Name) and arg.annotation.id in {'Request', 'Response'}):
            arg.annotation = None
    node.body = [ast.Raise(exc=ast.Call(func=ast.Name(id='AssertionError', ctx=ast.Load()),
                                     args=[ast.Constant('Schema generation executed dependency')], keywords=[]))]
    code = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(code, f'<signature:{module}.{name}>', 'exec'), namespace)
    func = namespace[name]
    func.__module__ = module
    return func


def test_recursive_real_dependency_signatures_and_include_dependencies():
    ns = dict(Depends=Depends, Request=Request, Response=Response, get_db=lambda: None)
    current = source_dependency('app.routers.auth', 'current_user', ns)
    admin = source_dependency('app.routers.auth', 'admin_user', ns)
    agent = source_dependency('app.security', 'agent_token', ns)

    def wrapped(user=Depends(current)):
        raise AssertionError('must not execute')

    app = FastAPI()
    nested = APIRouter()
    nested.get('/ordinary', dependencies=[Depends(wrapped)])(lambda: None)
    nested.get('/elevated', dependencies=[Depends(admin)])(lambda: None)
    app.include_router(nested, prefix='/nested')
    included = APIRouter()
    included.post('/included')(lambda: None)
    app.include_router(included, dependencies=[Depends(admin)])
    app.get('/agent-test', dependencies=[Depends(agent)])(lambda: None)
    install(app)
    paths = app.openapi()['paths']
    ordinary = paths['/nested/ordinary']['get']
    assert ordinary.get('x-stella-auth-type') == 'cookie-access'
    assert ordinary['security'] == [{'StellaAccessCookie': []}]
    assert ordinary['x-stella-elevation'] == 'none'
    for path, method in [('/nested/elevated', 'get'), ('/included', 'post')]:
        assert paths[path][method]['security'] == [{'StellaAccessCookie': []}]
        assert paths[path][method]['x-stella-elevation'] == 'none'
    assert paths['/agent-test']['get']['security'] == [{'StellaAgentBearer': []}, {'StellaAgentQueryLegacy': []}]
    schemes = app.openapi()['components']['securitySchemes']
    assert schemes['StellaAccessCookie'] | {} == {'type': 'apiKey', 'in': 'cookie', 'name': 'stella_at',
        'description': 'HttpOnly access-session cookie issued by Stella login; not an API key to paste into a header.'}
    assert schemes['StellaAgentBearer']['type'] == 'http'
    assert schemes['StellaAgentBearer']['scheme'] == 'bearer'
    assert 'main' not in sys.modules and 'app.database' not in sys.modules


def static_inventory(root=ROOT):
    """Strict AST inventory of main's mounted routers, not an import of main.

    Accept the declarative subset used by Stella. New dynamic routing must fail
    this audit rather than silently disappear. Follow imports/re-exports and
    Depends in router, include, decorator and function/Annotated arguments.
    """
    modules = {}

    def load(module):
        if module in modules:
            return modules[module]
        file = root / (module.replace('.', '/') + '.py')
        if not file.exists():
            file = root / module.replace('.', '/') / '__init__.py'
        tree = ast.parse(file.read_text())
        aliases = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.level, f'Review relative import: {file}:{node.lineno}'
                for alias in node.names:
                    aliases[alias.asname or alias.name] = f'{node.module}.{alias.name}'
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    aliases[alias.asname or alias.name] = alias.name
        modules[module] = tree, aliases
        return tree, aliases

    def symbol(module, node):
        text = ast.unparse(node)
        first, *rest = text.split('.')
        return '.'.join([load(module)[1].get(first, f'{module}.{first}'), *rest])

    def deps(module, nodes):
        result = set()
        for node in nodes:
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and symbol(module, call.func) in {'fastapi.Depends', 'fastapi.Security'}:
                    target = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg == 'dependency'), None)
                    assert target is not None, 'Review inferred dependency'
                    result.add(symbol(module, target))
        return result

    def dependency_graph(names):
        result, pending = set(), list(names)
        while pending:
            name = pending.pop()
            if name in result:
                continue
            result.add(name)
            module, attr = name.rsplit('.', 1)
            tree, aliases = load(module)
            if attr in aliases:
                pending.append(aliases[attr])
                continue
            node = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == attr), None)
            assert node is not None, f'Unknown dependency shape: {name}'
            pending.extend(deps(module, [node.args]) - result)
        return frozenset(result)

    records, mounted, excluded = [], set(), []

    def visit(qualified, prefix='', inherited=frozenset(), include_schema=True, ancestors=()):
        assert qualified not in ancestors, f'Router cycle: {qualified}'
        module, name = qualified.rsplit('.', 1)
        tree, aliases = load(module)
        if name in aliases:
            return visit(aliases[name], prefix, inherited, include_schema, (*ancestors, qualified))
        ctor = next((n.value for n in tree.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)), None)
        assert isinstance(ctor, ast.Call) and symbol(module, ctor.func) in {'fastapi.APIRouter', 'fastapi.FastAPI'}, qualified
        kw = {k.arg: k.value for k in ctor.keywords}
        prefix += ast.literal_eval(kw['prefix']) if 'prefix' in kw else ''
        inherited = inherited | deps(module, [kw['dependencies']] if 'dependencies' in kw else [])
        include_schema = include_schema and ('include_in_schema' not in kw or ast.literal_eval(kw['include_in_schema']))
        mounted.add(qualified)
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == name:
                    action = call.func.attr
                    opts = {k.arg: k.value for k in call.keywords}
                    if action == 'include_router':
                        assert call.args, 'Review keyword router'
                        extra = ast.literal_eval(opts['prefix']) if 'prefix' in opts else ''
                        more = deps(module, [opts['dependencies']] if 'dependencies' in opts else [])
                        visible = include_schema and ('include_in_schema' not in opts or ast.literal_eval(opts['include_in_schema']))
                        visit(symbol(module, call.args[0]), prefix + extra, inherited | more, visible, (*ancestors, qualified))
                    elif action == 'mount':
                        excluded.append((module, node.lineno, 'ASGI mount'))
                    else:
                        assert action in {'add_middleware', 'add_exception_handler'}, f'Review router operation: {action}'
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == name):
                    continue
                action = decorator.func.attr
                if action in {'middleware', 'websocket'}:
                    excluded.append((module, node.lineno, action))
                    continue
                assert action in {'get', 'head', 'post', 'put', 'patch', 'delete', 'options', 'trace', 'api_route'}, action
                opts = {k.arg: k.value for k in decorator.keywords}
                if not include_schema or ('include_in_schema' in opts and not ast.literal_eval(opts['include_in_schema'])):
                    excluded.append((module, node.lineno, 'hidden'))
                    continue
                assert decorator.args, 'Review keyword path'
                from starlette.routing import compile_path
                path = compile_path(prefix + ast.literal_eval(decorator.args[0]))[1]
                methods = ast.literal_eval(opts['methods']) if action == 'api_route' else [action.upper()]
                names = dependency_graph(inherited | deps(module, [node.args]) |
                    deps(module, [opts['dependencies']] if 'dependencies' in opts else []))
                for method in methods:
                    records.append((method.upper(), path, f'{module}.{node.name}', names))
        # Reject conditional/dynamic registration rather than claim complete coverage.
        for node in tree.body:
            if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
                assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                               and (n.func.attr in {'include_router', 'add_api_route', 'add_route', 'route', 'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace', 'connect', 'api_route'}
                                    or (isinstance(n.func.value, ast.Name) and n.func.value.id == name
                                        and n.func.attr not in {'add_middleware', 'add_exception_handler'}))
                               for n in ast.walk(node)), f'Review dynamic routes in {module}'

    visit('main.app')
    assert len(records) == len({(m, p) for m, p, _, _ in records}), 'Duplicate mounted method/path'
    return records, mounted, excluded


def test_actual_mounted_route_inventory_has_reviewed_auth_without_importing_main():
    contract = contract_module()
    records, mounted, excluded = static_inventory()
    unknown = [(method, path, endpoint) for method, path, endpoint, names in records
               if contract.classify_auth(method, path, endpoint, names).auth_type == 'unclassified']
    assert not unknown, unknown
    counts = Counter(contract.classify_auth(*record).auth_type for record in records)
    print(f'\nStatic mounted operations={len(records)} routers={len(mounted)} classifications={dict(sorted(counts.items()))}; exclusions={excluded}')
    assert 'app.routers.builtin_injection.router' not in mounted
    assert 'app.routers.service_settings.router' not in mounted
    assert 'main' not in sys.modules and 'app.database' not in sys.modules


@pytest.mark.parametrize('method', ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
def test_proxy_elevation_is_method_and_upstream_path_conditional(method):
    contract = contract_module()
    record = next(r for r in static_inventory()[0] if r[:2] == (method, '/drive/openlist/{path}'))
    policy = contract.classify_auth(*record)
    assert policy.auth_type == 'cookie-access'
    expected = 'none'
    assert policy.elevation == expected
    if method != 'OPTIONS':
        assert 'management_required' in policy.detail


@pytest.mark.parametrize('method,path,elevation', [
    ('PUT', '/auth/security', 'none'),
    ('POST', '/auth/admin/password', 'none'),
    ('POST', '/auth/admin/setup', 'none'),
    ('POST', '/auth/admin/unlock', 'none'),
])
def test_password_proofs_are_not_misrepresented_as_existing_grants(method, path, elevation):
    contract = contract_module()
    record = next(r for r in static_inventory()[0] if r[:2] == (method, path))
    policy = contract.classify_auth(*record)
    assert policy.auth_type == 'cookie-access'
    assert policy.elevation == elevation


def test_unknown_endpoint_is_not_public_and_validator_fails_without_breaking_schema():
    app = FastAPI()
    app.get('/new-unreviewed')(lambda: {'ok': True})
    contract = install(app)
    schema = app.openapi()
    assert schema['paths']['/new-unreviewed']['get']['x-stella-auth-type'] == 'unclassified'
    assert hasattr(contract, 'validate_contract'), 'Missing fail-closed validator'
    with pytest.raises(contract.ContractError, match='GET /new-unreviewed.*unclassified'):
        contract.validate_contract(app)
    assert TestClient(app).get('/new-unreviewed').json() == {'ok': True}


def test_conflicting_auth_families_are_not_silently_documented_as_either():
    contract = contract_module()
    policy = contract.classify_auth('GET', '/mixed', 'example.endpoint', frozenset({
        'app.security.agent_token', 'app.routers.auth.current_user'}))
    assert policy.auth_type == 'unclassified'


def test_validator_detects_shadowed_duplicate_routes():
    app = FastAPI()
    app.get('/duplicate')(lambda: None)
    app.get('/duplicate')(lambda: None)
    contract = install(app)
    assert hasattr(contract, 'validate_contract'), 'Missing duplicate method/path validation'
    with pytest.raises(contract.ContractError, match='duplicate route.*GET /duplicate'):
        contract.validate_contract(app)


def test_main_installs_contract_without_importing_main():
    tree = ast.parse((ROOT / 'main.py').read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == 'install_openapi_contract']
    assert len(calls) == 1 and ast.unparse(calls[0].args[0]) == 'app'


def backup_source_signatures(dependencies):
    """New Backup Center inputs/DTOs, with every business body replaced by raise.

    Only its standalone pydantic module is loaded. No router imports, lifespan,
    app.config/database/main, workers or environment-dependent service imports.
    LayoutPreferences must stay available for both the read and write DTOs.
    """
    spec = importlib.util.spec_from_file_location('source_shaped_backup_dtos', ROOT / 'app/schemas/backups.py')
    assert spec is not None and spec.loader is not None
    dto = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = dto
    spec.loader.exec_module(dto)
    ns = dict(vars(dto), Depends=Depends, Request=Request, Response=Response, Session=object)
    ns.update({name.rsplit('.', 1)[-1]: fn for name, fn in dependencies.items()})
    tree = ast.parse((ROOT / 'app/routers/backups.py').read_text())
    ctor = next(n.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'router' for t in n.targets))
    tags = ast.literal_eval(next(k.value for k in ctor.keywords if k.arg == 'tags'))
    result = {}
    for source in tree.body:
        if not isinstance(source, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorators = [d for d in source.decorator_list if isinstance(d, ast.Call)
                      and isinstance(d.func, ast.Attribute) and isinstance(d.func.value, ast.Name)
                      and d.func.value.id == 'router']
        if not decorators:
            continue
        assert len(decorators) == 1
        opts = {k.arg: k.value for k in decorators[0].keywords}
        model = opts.get('response_model')
        assert model is None or isinstance(model, ast.Name)
        kwargs = dict(tags=tags, status_code=ast.literal_eval(opts['status_code']) if 'status_code' in opts else 200,
                      response_model=ns[model.id] if model is not None else None)
        node = copy.deepcopy(source)
        node.decorator_list = []
        node.body = [ast.Raise(exc=ast.Call(func=ast.Name(id='AssertionError', ctx=ast.Load()),
                                         args=[ast.Constant('Schema generation executed backup handler')], keywords=[]))]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<backup-signature>', 'exec'), ns)
        handler = ns[node.name]
        handler.__module__ = 'app.routers.backups'
        handler.__qualname__ = node.name
        result['app.routers.backups.' + node.name] = handler, kwargs
    return result


def profile_source_signature(dependencies):
    """Extract the actual ProfileIn and PATCH signature, never auth imports/body."""
    from pydantic import BaseModel, Field

    namespace = dict(BaseModel=BaseModel, Field=Field, Depends=Depends, User=object, Session=object)
    namespace.update({name.rsplit('.', 1)[-1]: fn for name, fn in dependencies.items()})
    tree = ast.parse((ROOT / 'app/routers/auth.py').read_text())
    model = copy.deepcopy(next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ProfileIn'))
    endpoint = copy.deepcopy(next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'update_profile'))
    endpoint.decorator_list = []
    endpoint.body = [ast.Raise(exc=ast.Call(func=ast.Name(id='AssertionError', ctx=ast.Load()),
                                          args=[ast.Constant('Schema generation executed profile handler')], keywords=[]))]
    code = ast.fix_missing_locations(ast.Module(body=[model, endpoint], type_ignores=[]))
    exec(compile(code, '<profile-input-signature>', 'exec'), namespace)
    handler = namespace['update_profile']
    handler.__module__ = 'app.routers.auth'
    handler.__qualname__ = 'update_profile'
    return handler


def source_shaped_app():
    """All mounted method/path + endpoint identities + real dependency signatures.

    Bodies are never executed. Other legacy request/response models are omitted;
    backup DTOs and ProfileIn/PATCH signatures preserve their actual inputs.
    """
    records, _, _ = static_inventory()
    ns = dict(Depends=Depends, Request=Request, Response=Response)
    funcs = {}
    # Build shared get_db/current_user before their dependent signatures.
    names = sorted(set().union(*(set(r[3]) for r in records)), key=lambda n: (n != 'app.database.get_db', n != 'app.routers.auth.current_user', n != 'app.routers.auth.admin_user', n))
    for name in names:
        module, attr = name.rsplit('.', 1)
        funcs[name] = source_dependency(module, attr, ns)
    backup_signatures = backup_source_signatures(funcs)
    profile_signature = profile_source_signature(funcs)
    app = FastAPI()
    for method, path, endpoint, dependencies in records:
        if endpoint == 'app.routers.auth.update_profile':
            app.add_api_route(path, profile_signature, methods=[method],
                              dependencies=[Depends(funcs[n]) for n in sorted(dependencies)])
            continue
        if endpoint.startswith('app.routers.backups.'):
            handler, kwargs = backup_signatures[endpoint]
            app.add_api_route(path, handler, methods=[method], **kwargs)
            continue
        def handler():
            raise AssertionError('Inventory endpoint must never execute')
        handler.__module__, handler.__qualname__ = endpoint.rsplit('.', 1)
        app.add_api_route(path, handler, methods=[method], dependencies=[Depends(funcs[n]) for n in sorted(dependencies)])
    return app, records


def test_source_shaped_wrapper_resolves_real_admin_dependency_before_compilation():
    from inspect import Parameter, signature
    from app.openapi_contract import dependency_names

    app, _ = source_shaped_app()
    route = next(r for r in app.routes if getattr(r, 'path', None) == '/website-settings'
                 and 'POST' in getattr(r, 'methods', set()))
    names = dependency_names(route.dependant)
    assert {'app.routers.website_settings.website_write_context',
            'app.routers.auth.admin_user', 'app.routers.auth.current_user',
            'app.database.get_db'} <= names
    pending = [route.dependant]
    wrappers = []
    while pending:
        dep = pending.pop()
        pending.extend(dep.dependencies)
        if getattr(dep.call, '__name__', '') == 'website_write_context':
            wrappers.append(dep.call)
    assert wrappers
    for wrapper in wrappers:
        params = signature(wrapper).parameters
        assert all(p.kind not in {Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD}
                   for p in params.values())
        assert any(getattr(p.default, 'dependency', None).__module__ == 'app.routers.auth'
                   and getattr(p.default, 'dependency', None).__name__ == 'admin_user'
                   for p in params.values() if getattr(p.default, 'dependency', None))


def test_all_static_operations_roundtrip_through_fastapi_schema_and_strict_validator():
    app, records = source_shaped_app()
    contract = install(app)
    assert 'require_all_overrides' in __import__('inspect').signature(contract.validate_contract).parameters
    schema = contract.validate_contract(app, require_all_overrides=True)
    from fastapi.openapi.models import OpenAPI
    OpenAPI.model_validate(schema)
    actual = {(method.upper(), path) for path, item in schema['paths'].items() for method in item}
    assert actual == {(m, p) for m, p, _, _ in records}
    ids = [operation['operationId'] for item in schema['paths'].values() for operation in item.values()]
    assert len(set(ids)) == len(records)
    paths = schema['paths']
    assert paths['/auth/login']['post']['security'] == []
    assert paths['/auth/refresh']['post']['security'] == [{'StellaRefreshCookie': []}]
    assert paths['/oauth/userinfo']['get']['security'] == [{'StellaOIDCAccessBearer': []}]
    assert paths['/oauth/token']['post']['x-stella-client-auth']['anonymous-allowed'] is False
    assert paths['/oauth/token']['post']['security'] == [{}, {'StellaOIDCClientBasic': []}]
    assert paths['/oauth/authorize']['get']['security'] == [{}, {'StellaAccessCookie': []}, {'StellaRefreshCookie': []}]
    for path in ['/auth/logout', '/auth/email/resend']:
        assert {} in paths[path]['post']['security']
    assert paths['/website-assets/{mid}.js']['get']['security'] == [{}, {'StellaAccessCookie': []}]
    assert 'security' not in schema
    assert 'app.database' not in sys.modules and 'main' not in sys.modules


@pytest.mark.parametrize('damage,expected', [('id', 'operationId'), ('auth', 'authentication metadata'), ('scheme', 'security scheme')])
def test_validator_rejects_invalid_generated_contract(damage, expected):
    app, _ = source_shaped_app()
    contract = install(app)
    schema = copy.deepcopy(app.openapi())
    if damage == 'id':
        schema['paths']['/auth/me']['get']['operationId'] = 'unstable'
    elif damage == 'auth':
        schema['paths']['/auth/me']['get']['x-stella-auth-type'] = 'anonymous'
    else:
        del schema['components']['securitySchemes']['StellaAccessCookie']
    app.openapi = lambda: schema
    with pytest.raises(contract.ContractError, match=expected):
        contract.validate_contract(app)


def test_override_identity_dependency_and_method_changes_fail_closed():
    contract = contract_module()
    for (method, path), override in contract.AUTH_OVERRIDES.items():
        assert contract.classify_auth(method, path, override.endpoint, override.dependencies) == override.policy
        assert contract.classify_auth(method, path, override.endpoint + '_changed', override.dependencies).auth_type == 'unclassified'
        assert contract.classify_auth(method, path, override.endpoint, override.dependencies | {'other.check'}).auth_type == 'unclassified'
    assert contract.classify_auth('DELETE', '/oauth/token', 'app.routers.oidc.token', frozenset()).auth_type == 'unclassified'
    app = FastAPI()
    install(app)
    with pytest.raises(contract.ContractError, match='stale override'):
        contract.validate_contract(app, require_all_overrides=True)


def test_schema_security_objects_do_not_mutate_the_policy_registry():
    app, _ = source_shaped_app()
    contract = install(app)
    schema = app.openapi()
    schema['components']['securitySchemes']['StellaAccessCookie']['in'] = 'header'
    assert contract.SECURITY_SCHEMES['StellaAccessCookie']['in'] == 'cookie'


def test_nested_annotated_security_dependencies_and_late_route_cache_invalidation():
    from typing import Annotated
    from fastapi import Security
    ns = dict(Depends=Depends, Request=Request, Response=Response, get_db=lambda: None)
    current = source_dependency('app.routers.auth', 'current_user', ns)
    admin = source_dependency('app.routers.auth', 'admin_user', ns)
    app = FastAPI()
    install(app)
    first = app.openapi()
    inner, outer = APIRouter(), APIRouter()

    def endpoint(user: Annotated[object, Security(admin)]):
        return None

    inner.add_api_route('/proof', endpoint, methods=['POST'], operation_id='old_explicit_id')
    outer.include_router(inner, prefix='/inner')
    app.include_router(outer, prefix='/outer')
    second = app.openapi()
    assert first is not second
    operation = second['paths']['/outer/inner/proof']['post']
    assert operation['x-stella-elevation'] == 'none'
    assert operation['security'] == [{'StellaAccessCookie': []}]
    assert inner.routes[0].operation_id == 'old_explicit_id'
    assert operation['operationId'] != 'old_explicit_id'


def test_dependency_walk_handles_shared_and_cyclic_graphs_and_unrelated_names():
    from types import SimpleNamespace
    contract = contract_module()
    def current_user():
        pass
    child = SimpleNamespace(call=current_user, dependencies=[])
    child.dependencies = [child]
    parent = SimpleNamespace(dependencies=[child, child])
    names = contract.dependency_names(parent)
    assert len(names) == 1
    assert contract.classify_auth('GET', '/unknown', 'test.endpoint', names).auth_type == 'unclassified'
