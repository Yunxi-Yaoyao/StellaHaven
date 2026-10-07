"""Non-secret projection and atomic settings for the two builtin adapters."""
import json
from uuid import uuid4
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.services.backup_health import record_change
from app.services.service_settings_input import SettingsInput, DriveAppearance, GalleryAppearance, connection_input
from app.models.config import AppConfig
from app.services import integrations as store, builtin_injection as injection
from app.services import external_services as external, service_appearance as appearance


async def check(db, site, incoming):
    appearance.check_site(site)
    if set(incoming) != {'connection'}:
        raise HTTPException(422, '检测只接受 connection')
    try:
        connection = connection_input(site, incoming['connection'])
        if site == 'drive' and connection.auth_mode == 'token' and connection.token is None and not connection.clear_token:
            saved = external.load(db, site)
            if external.endpoint(saved, '') != external.endpoint(connection, ''):
                raise HTTPException(422, '地址已改变：请使用手动模式检测，或明确填写该地址的凭据；不会向新地址发送已保存凭据')
        cfg = external.merge(db, site, connection)
    except (ValidationError, ValueError):
        raise HTTPException(422, '连接配置无效，请检查地址、登录方式和凭据') from None
    db.rollback()  # Authentication/config snapshot complete; release DB before I/O.
    result = await external.probe(site, cfg)
    if result['ok']:
        result['warning'] = '仅验证服务器连接；浏览器嵌入、Cookie 与单点登录仍需在实际页面验证。'
    return result


def save(db, site, incoming, actor_id):
    appearance.check_site(site)
    # Validate all fields before locking/writing; never echo Pydantic input/token.
    try:
        data = SettingsInput.model_validate(incoming)
        connection = connection_input(site, data.connection)
        visual = (DriveAppearance if site == 'drive' else GalleryAppearance).model_validate(data.appearance).model_dump()
    except ValidationError as exc:
        raise HTTPException(422, {'errors': [{'loc': list(e['loc']), 'msg': e['msg']} for e in exc.errors(include_input=False, include_context=False)]}) from None
    if 'custom' in data.model_fields_set and data.custom is None:
        raise HTTPException(422, 'custom 不可为 null；不修改时请省略')
    custom = data.custom.model_dump() if data.custom is not None else None
    if custom is not None:
        problems = injection.draft_errors(custom)
        if problems: raise HTTPException(422, {'errors': problems})
    key = f'external_{site}_connection'
    defaults = {store.KEY: store.empty_state(), key: external.DEFAULTS[site], appearance.KEY: appearance.DEFAULTS}
    if custom is not None: defaults[injection.KEY] = injection.empty_state()
    try:
        # Same rows/locks as the legacy APIs, without their independently committing
        # edit()/put() helpers. A fixed order also serializes absent-row creation.
        rows = {}
        for name in sorted(defaults):
            db.execute(insert(AppConfig).values(key=name, value=json.dumps(defaults[name])).on_conflict_do_nothing(index_elements=['key']))
            rows[name] = db.execute(select(AppConfig).where(AppConfig.key == name).with_for_update().execution_options(populate_existing=True)).scalar_one()
        try:
            cfg = external.merge(db, site, connection)
        except ValueError:
            raise HTTPException(422, '连接配置无效：Token 登录需要有效凭据') from None
        values = {name: json.loads(row.value) for name, row in rows.items()}
        registry = values[store.KEY]
        entry = next((e for e in registry['navigation'] if e['id'] == site), None)
        if entry is None:
            # Preserve navigation order: materialize the existing effective order,
            # instead of moving an uncustomized builtin to the front.
            registry['navigation'] = [dict(id=e['id'], title=e['title'], icon=e['icon'], visible=e['visible']) for e in store.navigation(db)['entries']]
            entry = next(e for e in registry['navigation'] if e['id'] == site)
        entry.update(title=data.name, icon=data.icon, visible=data.visible)
        values[key] = cfg.model_dump()
        values[appearance.KEY][site] = visual
        if custom is not None:
            state = values[injection.KEY][site]
            state['draft'] = custom
            if any(state['active'].get(k) != v for k, v in custom.items()):
                state['previous'] = state['active'] | {'status': 'revoked'}
                state['active'] = custom | {'version': uuid4().hex, 'status': 'active'}
        changed = False
        for name, row in rows.items():
            if json.loads(row.value) != values[name]:
                row.value = json.dumps(values[name], ensure_ascii=False)
                changed = True
        db.flush()
        if changed:
            record_change(db, action='service.settings', actor_id=actor_id,
                          changed_fields=['name', 'icon', 'visible', 'target', 'injection'])
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return read(db, site)


def oidc_summary(db):
    from app.services import oidc, ha_state
    # Never use _load_clients / locked_state: both can initialize shared state.
    if ha_state.enabled():
        clients = db.execute(select(ha_state.state_table.c.payload).where(
            ha_state.state_table.c.key == 'oidc.clients')).scalar_one_or_none() or {}
    else:
        clients = json.loads(oidc.CLIENT_FILE.read_text()) if oidc.CLIENT_FILE.exists() else {}
    client = clients.get('immich') or {}
    return {'client_registered': bool(client.get('client_secret')),
            'issuer': oidc.DEFAULT_ISSUER, 'client_id': 'immich',
            'redirect_uris': list(client.get('redirect_uris', []))}


def read(db, site):
    appearance.check_site(site)
    # Refresh retained ORM objects as well as fresh request sessions. Keep the
    # references alive while the legacy projection helpers use Session.get().
    _rows = db.execute(select(AppConfig).where(AppConfig.key.in_(
        (store.KEY, f'external_{site}_connection'))).execution_options(populate_existing=True)).scalars().all()
    entry = next(e for e in store.navigation(db)['entries'] if e['id'] == site)
    cfg = external.load(db, site)
    connection = external.masked_drive(cfg) if site == 'drive' else {
        key: getattr(cfg, key) for key in ('browser_url', 'upstream_url', 'alternate_browser_url', 'auth_mode')}
    state = injection.read(db, site)
    return {'site': site, 'name': entry['title'], 'icon': entry['icon'], 'visible': entry['visible'],
            'connection': connection, 'appearance': appearance.read(db, site),
            'injection': {key: state[key] for key in ('draft', 'active', 'previous')},
            'capabilities': {'background': site == 'drive', 'oidc': site == 'gallery'},
            'scopes': {'appearance': 'embedded' if site == 'drive' else 'domain', 'background': 'device' if site == 'drive' else None},
            'oidc': oidc_summary(db) if site == 'gallery' else None,
            'compatibility': ['目录快照缓存修复', '管理授权提示（手动重试）', '同源背景同步'] if site == 'drive' else ['原域名加载器（不更改原站 OIDC 配置）']}
