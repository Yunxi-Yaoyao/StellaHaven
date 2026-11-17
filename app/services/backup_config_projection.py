"""Audited structural projections for known configuration classes only."""
import json
import re
from app.services.backup_archive import strict_json, InvalidArchive


def fields(value, names):
    if not isinstance(value, dict):
        raise InvalidArchive('configuration object expected')
    return {key: value[key] for key in names if key in value}


INJECTION = ('enabled', 'css', 'js', 'timing', 'csp_policy', 'version', 'status', 'source_origin')


def injections(value):
    return {key: (fields(raw, INJECTION) if raw is not None else None)
            for key, raw in fields(value, ('draft', 'active', 'previous')).items()}


def integration_state(state):
    result = {}
    if 'modules' in state:
        result['modules'] = {}
        names = ('id', 'name', 'icon', 'mode', 'adapter', 'browser_url', 'target_id', 'initial_path',
                 'enabled', 'keep_alive', 'origin', 'template_id', 'background')
        for mid, module in state['modules'].items():
            value = fields(module, names)
            if 'injection' in module: value['injection'] = injections(module['injection'])
            if 'connection' in module: value['connection'] = fields(module['connection'], ('transport', 'auth_mode', 'header_name', 'injection_delivery', 'has_token'))
            if 'request_policy' in module: value['request_policy'] = fields(module['request_policy'], ('management_prefixes', 'read_post_paths', 'protect_other_writes'))
            if 'exact_legacy_sha256' in module.get('migration', {}):
                signatures = fields(module['migration']['exact_legacy_sha256'], ('style', 'script'))
                if any(not isinstance(items, list) or any(not isinstance(item, str) or not re.fullmatch(r'[0-9a-f]{64}', item)
                                                          for item in items) for items in signatures.values()):
                    raise InvalidArchive('invalid migration digest')
                # Active dedup is configuration; legacy snapshots/before are not.
                value['migration'] = {'exact_legacy_sha256': signatures}
            result['modules'][mid] = value
    if 'legacy_routes' in state:
        result['legacy_routes'] = fields(state['legacy_routes'], ('drive', 'gallery'))
        if any(not isinstance(mid, str) for mid in result['legacy_routes'].values()):
            raise InvalidArchive('invalid legacy route')
    if 'targets' in state:
        result['targets'] = {key: fields(raw, ('id', 'name', 'upstream_url', 'allowed_ips', 'controlled', 'headers')) for key, raw in state['targets'].items()}
        for target in result['targets'].values():
            if 'headers' in target:
                target['headers'] = fields(target['headers'], ('authorization', 'x-api-key', 'x-auth-token'))
    if 'navigation' in state:
        result['navigation'] = [fields(raw, ('id', 'title', 'icon', 'visible')) for raw in state['navigation']]
    if 'website_templates' in state:
        from app.services.saved_website_templates import portable_draft
        result['website_templates'] = {}
        for key, raw in state['website_templates'].items():
            record = fields(raw, ('id', 'name', 'owner_id'))
            record['draft'] = portable_draft(raw['draft'])
            result['website_templates'][key] = record
    if 'website_version_origins' in state:
        result['website_version_origins'] = {mid: {key: url for key, url in raw.items() if isinstance(url, str)}
                                             for mid, raw in state['website_version_origins'].items()}
    if 'website_retired_versions' in state:
        result['website_retired_versions'] = {mid: [fields(raw, INJECTION) for raw in versions]
                                              for mid, versions in state['website_retired_versions'].items()}
    return result


def project_config(key, value):
    if key == 'public_host':
        if not isinstance(value, str) or len(value) > 2048:
            raise InvalidArchive('public host size')
        return value
    raw = strict_json(value)
    if key == 'backup_center_v1':
        from app.schemas.backups import Config
        result = {'config': Config.model_validate(raw['config']).model_dump()}
    elif key.startswith('notes-preferences:'):
        from app.schemas.notes_preferences import NotesPreferencesPatch
        from app.services.notes_preferences import DEFAULT
        selected = fields(raw, DEFAULT)
        selected.pop('revision', None)
        patch = NotesPreferencesPatch.model_validate(dict(expected_revision=0, **selected))
        result = DEFAULT | patch.model_dump(exclude={'expected_revision'}, exclude_unset=True)
        result['revision'] = raw.get('revision', 0)
    elif key.startswith('client-preferences:'):
        from app.schemas.backups import ClientPreferences
        result = ClientPreferences.model_validate(raw).model_dump(exclude_none=True)
    elif key == 'integrations_v1':
        result = integration_state(raw)
    elif key == 'builtin_injection_v1':
        result = {site: injections(raw[site]) for site in ('drive', 'gallery') if site in raw}
    elif key == 'service_appearance_v1':
        result = {site: fields(raw[site], ('theme', 'simplified') if site == 'drive' else ('logo',)) for site in ('drive', 'gallery') if site in raw}
    elif key.startswith('external_'):
        from app.services.external_services import Connection
        result = Connection.model_validate(fields(raw, Connection.model_fields)).model_dump()
    elif key == 'prometheus_connection':
        from app.routers.metrics_source import PrometheusConnection
        result = PrometheusConnection.model_validate(raw).model_dump()
    elif key.startswith('node_map_manual:'):
        from app.services.server_map import MapLocationUpdate
        result = MapLocationUpdate.model_validate(raw).model_dump() if raw is not None else None
    elif key == 'homebg_index':
        result = []
        for record in raw:
            entry = fields(record, ('id', 'name', 'ext', 'file', 'isDefault', 'isSystem', 'owner', 'size', 'sha256'))
            if 'media' in record:
                entry['media'] = fields(record['media'], ('url', 'status', 'poster', 'thumbnail', 'display', 'variants', 'width', 'height', 'duration', 'bytes'))
                if 'variants' in entry['media']:
                    entry['media']['variants'] = fields(entry['media']['variants'], ('original', 'compressed1', 'compressed2'))
            result.append(entry)
    else:
        raise InvalidArchive('unknown settings class')
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def project_shared(key, raw):
    if key == 'smtp.config':
        return fields(raw, ('host', 'port', 'username', 'password', 'from_name', 'enabled'))
    if key == 'oidc.clients':
        return {client: fields(value, ('client_id', 'name', 'client_secret', 'enabled', 'redirect_uris', 'scopes', 'credential_version'))
                for client, value in raw.items()}
    raise InvalidArchive('unknown shared settings class')
