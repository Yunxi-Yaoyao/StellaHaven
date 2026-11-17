"""Audited settings projection; content/runtime keys are never serialized wholesale."""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
import re
import secrets
import tempfile
import zipfile
from uuid import UUID

from sqlalchemy import select, func, case, update
from sqlalchemy.orm import Session
from app.models.config import AppConfig
from app.models.user import User
from app.models.blob import BlobObject
from app.models.node import Node
from app.models.monitor import Monitor, MonitorGroup, MonitorGroupMember
from app.models.alert import AlertRule
from app.services.ha_state import state_table
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import insert
from app.services import blob_store
from app.services.backup_archive import InvalidArchive, validate_archive, safe_name, hash_stream, strict_json
from app.services.backup_config_projection import project_config, project_shared

CONFIG_KEYS = frozenset({'public_host', 'homebg_index', 'prometheus_connection',
                         'external_drive_connection', 'external_gallery_connection',
                         'service_appearance_v1', 'builtin_injection_v1', 'backup_center_v1'})
PROFILE = ('id', 'display_name', 'avatar_url', 'avatar_history', 'home_bg')
MAX_SETTINGS = 16 * 1024**2
MAX_ROWS = 50000
RESOURCE = re.compile(r'/assets/((?:homebg|avatars)/[A-Za-z0-9_.-]+)')
TABLES = {
    'nodes': (Node, ('id', 'name', 'platform', 'host', 'token', 'monitored_ifaces', 'net_type',
                     'public_ip', 'public_ip_source', 'ip_version', 'region')),
    'monitors': (Monitor, ('id', 'name', 'node_id', 'type', 'target', 'interval', 'timeout')),
    'alert_rules': (AlertRule, ('id', 'kind', 'target', 'label', 'link', 'severity', 'debounce',
                               'repeat_minutes', 'email', 'enabled', 'schema_version', 'revision', 'condition', 'fingerprint')),
}
SHARED_KEYS = frozenset({'smtp.config', 'oidc.clients'})
GROUP_TABLES = {
    'monitor_groups': (MonitorGroup, ('id', 'name', 'failure_policy', 'rotation_seconds', 'stable_uuid')),
    'monitor_group_members': (MonitorGroupMember, ('group_id', 'monitor_id', 'position')),
}


def project_monitor_tables(db, tables):
    from app.services.entry_monitoring import managed_ids
    from app.services.entry_monitor_groups import owned_groups
    automatic, parents = managed_ids(db), owned_groups(db)
    tables['monitors'] = [row for row in tables['monitors'] if row['id'] not in automatic]
    kept = {row['id'] for row in tables['monitors']}
    members = [dict(group_id=m.group_id, monitor_id=m.monitor_id, position=m.position)
               for m in db.query(MonitorGroupMember).order_by(MonitorGroupMember.group_id, MonitorGroupMember.position, MonitorGroupMember.monitor_id)
               if m.group_id not in parents and m.monitor_id in kept]
    counts = {}
    for member in members:
        counts[member['group_id']] = counts.get(member['group_id'], 0) + 1
    # Automatic parents and their relations are derived, never restored as user groups.
    # Ordinary children inside them remain independently restorable scheduled probes.
    tables['monitor_groups'] = [{f: getattr(g, f) for f in GROUP_TABLES['monitor_groups'][1]}
        for g in db.query(MonitorGroup).order_by(MonitorGroup.id)
        if g.id not in parents and 1 <= counts.get(g.id, 0) <= 12]
    gids = {g['id'] for g in tables['monitor_groups']}
    positions = {}
    tables['monitor_group_members'] = []
    for member in members:
        gid = member['group_id']
        if gid in gids:
            # Deletion/filtering can leave gaps; serialize the same relative order
            # as canonical contiguous positions without mutating live membership.
            tables['monitor_group_members'].append(member | {'position': positions.get(gid, 0)})
            positions[gid] = positions.get(gid, 0) + 1


def _validate_table_rows(name, rows):
    fields = set((TABLES | GROUP_TABLES)[name][1])
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise InvalidArchive('unsafe settings fields')
    ids = set()
    uuids = set()
    for row in rows:
        # Legacy group archives lack identity proof; only absent groups may be created.
        allowed = (fields, fields - {'stable_uuid'}) if name == 'monitor_groups' else (fields,)
        if not isinstance(row, dict) or set(row) not in allowed:
            raise InvalidArchive('unsafe settings fields')
        for field in fields & {'id', 'node_id', 'group_id', 'monitor_id'}:
            if type(row[field]) is not int or row[field] <= 0:
                raise InvalidArchive('settings identity must be a positive integer')
        identity = row.get('id', row.get('monitor_id'))
        if identity in ids:
            raise InvalidArchive('duplicate settings identity')
        ids.add(identity)
        if name == 'monitor_groups' and 'stable_uuid' in row:
            value = row['stable_uuid']
            try:
                valid = isinstance(value, str) and str(UUID(value)) == value
            except ValueError:
                valid = False
            if not valid or value in uuids:
                raise InvalidArchive('invalid or duplicate monitor group identity')
            uuids.add(value)
        if name == 'monitor_group_members' and (type(row['position']) is not int or row['position'] < 0):
            raise InvalidArchive('invalid monitor group position')


def _preview_monitor_groups(db, tables):
    for name in GROUP_TABLES:
        _validate_table_rows(name, tables.get(name, []))
    from app.services.entry_monitor_groups import owned_groups
    from app.services.entry_monitoring import managed_ids
    parents, automatic = owned_groups(db), managed_ids(db)
    archived = tables.get('monitor_groups', [])
    members = tables.get('monitor_group_members', [])
    gids = {g['id'] for g in archived}
    mids = [m['monitor_id'] for m in members]
    if len(gids) != len(archived) or len(set(mids)) != len(mids):
        raise InvalidArchive('duplicate monitor grouping')
    incoming = {m['id'] for m in tables.get('monitors', [])}
    if any(m['group_id'] not in gids or m['monitor_id'] in automatic or
           (m['monitor_id'] not in incoming and db.get(Monitor, m['monitor_id']) is None) for m in members):
        raise InvalidArchive('unsafe monitor group reference')
    by_group = {}
    for member in members:
        by_group.setdefault(member['group_id'], []).append(member)
    plan = []
    for row in archived:
        children = by_group.get(row['id'], [])
        if (row['id'] in parents or not 1 <= len(children) <= 12 or not isinstance(row['name'], str)
                or not row['name'].strip() or len(row['name']) > 64 or row['failure_policy'] not in ('any', 'all')
                or type(row['rotation_seconds']) is not int or row['rotation_seconds'] not in (0, 8, 15, 30)):
            raise InvalidArchive('unsafe monitor group')
        if sorted(m['position'] for m in children) != list(range(len(children))):
            raise InvalidArchive('monitor group positions must be unique and contiguous')
        group = db.get(MonitorGroup, row['id'], with_for_update=True)
        stable_uuid = row.get('stable_uuid')
        if group is not None and (stable_uuid is None or group.stable_uuid != stable_uuid):
            raise InvalidArchive('live monitor group identity conflict')
        if stable_uuid is not None:
            owner = db.query(MonitorGroup).filter_by(stable_uuid=stable_uuid).with_for_update().first()
            if owner is not None and owner.id != row['id']:
                raise InvalidArchive('monitor group identity requires explicit remap')
        for member in children:
            existing = db.query(MonitorGroupMember).filter_by(monitor_id=member['monitor_id']).first()
            if existing and existing.group_id != row['id']:
                raise InvalidArchive('monitor belongs to another live group')
        plan.append((row, children))
    return plan


def _apply_monitor_groups(db, plan):
    for row, children in plan:
        group = db.get(MonitorGroup, row['id'])
        if group is None:
            db.add(MonitorGroup(**row))
        else:
            for field, value in row.items():
                setattr(group, field, value)
        db.flush()
        # Replace only this proven identity, never union or clear unrelated groups.
        db.query(MonitorGroupMember).filter_by(group_id=row['id']).delete(synchronize_session='fetch')
        db.add_all(MonitorGroupMember(**member) for member in children)
    db.flush()


def restore_monitor_groups(db, tables):
    _apply_monitor_groups(db, _preview_monitor_groups(db, tables))


class UnsupportedSettingsMode(RuntimeError):
    pass


def settings_supported():
    from app.services import ha_state
    return blob_store.enabled() and ha_state.enabled()


def require_settings_mode():
    if not settings_supported():
        raise UnsupportedSettingsMode('PostgreSQL blob/shared state required; legacy file configuration is not an atomic settings restore')


def allowed_key(key):
    if key in CONFIG_KEYS or key == 'integrations_v1':
        return True
    for prefix in ('notes-preferences:', 'client-preferences:', 'node_map_manual:'):
        if key.startswith(prefix):
            suffix = key[len(prefix):]
            try:
                UUID(suffix) if prefix != 'node_map_manual:' else int(suffix)
                return True
            except ValueError:
                return False
    return False


def config_value(key, value):
    return project_config(key, value)


@dataclass
class Payload:
    entries: dict
    warnings: list


def configuration_resources(data):
    """Dependencies of projected configuration, including legacy bare names.

    Recurse only over already allowlisted config fields, not arbitrary stored
    AppConfig/content. Profile history is a JSON string, while catalog.file is
    an authoritative original even when no profile selects it and media is absent.
    """
    required = set()

    def urls(value):
        if isinstance(value, str):
            required.update(RESOURCE.findall(value))
        elif isinstance(value, dict):
            for child in value.values():
                urls(child)
        elif isinstance(value, list):
            for child in value:
                urls(child)

    for profile in data['profiles']:
        urls(profile['avatar_url'])
        urls(profile['home_bg'])
        history = strict_json(profile['avatar_history'] or '[]')
        if not isinstance(history, list) or any(not isinstance(url, str) for url in history):
            raise InvalidArchive('invalid avatar history')
        urls(history)
    for row in data['config']:
        value = row['value'] if row['key'] == 'public_host' else strict_json(row['value'])
        urls(value)
        if row['key'] == 'homebg_index':
            for entry in value:
                filename = entry.get('file')
                if (not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', filename)
                        or '..' in filename):
                    raise InvalidArchive('invalid background filename')
                required.add('homebg/' + filename)
    for key in required:
        safe_name(key)
    return required


@contextmanager
def export_settings(conn, scratch):
    require_settings_mode()
    with ExitStack() as stack:
        db = Session(bind=conn)
        users = [dict(row) for row in conn.execute(select(*(getattr(User, f) for f in PROFILE))).mappings()]
        configs = []
        skipped = 0
        # Discover keys only: NEVER fetch webpage/note/receipt payloads to filter in Python.
        for key in conn.execute(select(AppConfig.key).execution_options(yield_per=100)).scalars():
            if not allowed_key(key):
                skipped += 1
                continue
            value = conn.execute(select(case((func.octet_length(AppConfig.value) <= MAX_SETTINGS, AppConfig.value), else_=None)).where(AppConfig.key == key)).scalar_one()
            if value is None:
                raise InvalidArchive('configuration row too large')
            configs.append({'key': key, 'value': config_value(key, value)})
            if len(configs) > MAX_ROWS:
                raise InvalidArchive('settings row limit')
        tables = {name: [dict(row) for row in conn.execute(select(*(getattr(model, f) for f in fields))).mappings()]
                  for name, (model, fields) in TABLES.items()}
        # Automatic numeric-IP identities cannot be restored as manual probes:
        # their manifest/scope ledger and telemetry are intentionally not settings.
        project_monitor_tables(db, tables)
        shared = []
        if inspect(conn).has_table('ha_shared_state'):
            shared = [{'key': row['key'], 'payload': project_shared(row['key'], row['payload'])}
                      for row in conn.execute(select(state_table).where(state_table.c.key.in_(SHARED_KEYS))).mappings()]
        data = {'version': 1, 'profiles': users, 'config': configs, 'tables': tables, 'shared': shared, 'resources': {}}
        entries = {}
        from app.services.native_nav_backup import export_domain
        data['native_nav'] = export_domain(db, entries)
        warnings = [f'{skipped} private/content/runtime configuration rows omitted'] if skipped else []
        warnings.append('Known settings use explicit field projections; unknown extensions and all browser-only unsynced preferences are omitted')
        resources = conn.execute(select(BlobObject.key, BlobObject.size, BlobObject.mime, BlobObject.sha256).where(
            BlobObject.key.like('homebg/%') | BlobObject.key.like('avatars/%')).execution_options(yield_per=50))
        for key, size, mime, sha in resources:
            safe_name(key)
            stream = stack.enter_context(tempfile.TemporaryFile(dir=scratch))
            for chunk in blob_store.read_range(db, key, 0, size):
                stream.write(chunk)
            stream.seek(0)
            if hash_stream(stream) != (size, sha):
                raise InvalidArchive('configuration resource checksum mismatch')
            stream.seek(0)
            entries['resources/' + key] = stream
            data['resources'][key] = {'bytes': size, 'sha256': sha, 'mime': mime}
        raw = json.dumps(data, ensure_ascii=False, default=str).encode()
        if len(raw) > MAX_SETTINGS:
            raise InvalidArchive('settings payload limit')
        entries['settings.json'] = io.BytesIO(raw)
        required = configuration_resources(data)
        if any('resources/' + key not in entries for key in required):
            raise InvalidArchive('missing configuration resource')
        yield Payload(entries, warnings)


def _restore_oidc_clients(db, archived):
    # Match oidc._locked_client_runtime/ha_state.locked_states: initialize and
    # lock clients THEN runtime on this transaction's single connection. Do not
    # use an independent locked_states transaction outside the restore boundary.
    states = {}
    for key, default in (('oidc.clients', {}), ('oidc.runtime', {'codes': {}, 'tokens': {}})):
        db.execute(insert(state_table).values(key=key, payload=default)
                   .on_conflict_do_nothing(index_elements=['key']))
        states[key] = db.execute(select(state_table.c.payload).where(
            state_table.c.key == key).with_for_update()).scalar_one()
    restored = project_shared('oidc.clients', archived)
    for cid, client in restored.items():
        # A settings archive is NOT a revocation-state rollback. Issue a fresh
        # epoch even for identical/restored/deleted clients, including legacy 0.
        # Leave runtime byte-for-byte intact, but no retained code/token may
        # match the newly restored registration's credential version.
        forbidden = [client.get('credential_version', 0),
                     states['oidc.clients'].get(cid, {}).get('credential_version', 0)]
        for kind in ('codes', 'tokens'):
            forbidden.extend(rec.get('credential_version', 0)
                             for rec in states['oidc.runtime'].get(kind, {}).values()
                             if rec.get('client_id') == cid)
        version = secrets.token_hex(16)
        while version in forbidden:
            version = secrets.token_hex(16)
        client['credential_version'] = version
    db.execute(update(state_table).where(state_table.c.key == 'oidc.clients').values(payload=restored))


def restore_settings(engine, path, *, fence=lambda: None):
    require_settings_mode()
    manifest = validate_archive(path)
    if manifest['scope'] != 'settings':
        raise InvalidArchive('settings archive required')
    with zipfile.ZipFile(path) as z:
        if z.getinfo('settings.json').file_size > MAX_SETTINGS:
            raise InvalidArchive('settings payload limit')
        raw = z.read('settings.json')
        data = strict_json(raw)
        if set(data) not in ({'version', 'profiles', 'config', 'tables', 'shared', 'resources'}, {'version', 'profiles', 'config', 'tables', 'shared', 'resources', 'native_nav'}) or data['version'] != 1:
            raise InvalidArchive('settings payload version')
        if set(data['tables']) not in (set(TABLES), set(TABLES) | set(GROUP_TABLES)):
            raise InvalidArchive('unexpected settings table')
        for name, rows in data['tables'].items():
            _validate_table_rows(name, rows)
        if any(set(row) != {'key', 'payload'} or row['key'] not in SHARED_KEYS for row in data['shared']):
            raise InvalidArchive('unsafe shared state')
        for row in data['config']:
            if set(row) != {'key', 'value'} or not allowed_key(row['key']) or config_value(row['key'], row['value']) != row['value']:
                raise InvalidArchive('private configuration key')
        for profile in data['profiles']:
            if set(profile) != set(PROFILE):
                raise InvalidArchive('unsafe profile fields')
            UUID(profile['id'])
        for name in manifest['entries']:
            if name == 'settings.json':
                continue
            if not (name.startswith('resources/homebg/') or name.startswith('resources/avatars/') or name.startswith('resources/native-nav/')):
                raise InvalidArchive('non-configuration resource')
        if any('resources/' + key not in manifest['entries'] for key in configuration_resources(data)):
            raise InvalidArchive('missing configuration resource')
        from app.services.native_nav_backup import validate_domain, restore_domain, PREFIX
        native_plan = validate_domain(data.get('native_nav', []), z, manifest)
        if set('resources/' + key for key in data['resources']) != {name for name in manifest['entries'] if not name.startswith(PREFIX)} - {'settings.json'}:
            raise InvalidArchive('resource catalog mismatch')
        for key, meta in data['resources'].items():
            if (set(meta) != {'bytes', 'sha256', 'mime'} or not isinstance(meta['mime'], str) or len(meta['mime']) > 200
                    or {k: meta[k] for k in ('bytes', 'sha256')} != manifest['entries']['resources/' + key]):
                raise InvalidArchive('resource metadata mismatch')
        with Session(engine) as db, db.begin():
            fence()
            # Settings restore also writes home_bg, the shared catalog and nav.
            # Join the same media transaction before any profile/config locks.
            from app.services.homebg_references import lock_library, validate_new, preference_urls
            from app.models.native_nav import NavState
            if blob_store.enabled():
                lock_library(db)  # settings restore requires PG blob mode
            previous_media = list(db.scalars(select(User.home_bg))) + preference_urls(db)
            if inspect(db.get_bind()).has_table('nav_states'):
                previous_media += list(db.scalars(select(NavState.data)))
            from app.services.entry_monitor_groups import lock
            from app.services.entry_monitoring import managed_ids
            lock(db)
            automatic = managed_ids(db)
            if any(row['id'] in automatic for row in data['tables']['monitors']):
                raise InvalidArchive('cannot overwrite automatic monitor identity')
            group_plan = _preview_monitor_groups(db, data['tables'])
            node_ids = {row['id'] for row in data['tables']['nodes']}
            if any(row['node_id'] not in node_ids and db.get(Node, row['node_id']) is None
                   for row in data['tables']['monitors']):
                raise InvalidArchive('missing monitor source identity')
            for profile in data['profiles']:
                if db.get(User, UUID(profile['id'])) is None:
                    raise InvalidArchive('profile identity missing; use full restore for a new site')
            for name, (model, fields) in TABLES.items():
                for row in data['tables'][name]:
                    current = db.get(model, row['id'], with_for_update=True)
                    if model is AlertRule:
                        # CAS is a live fencing token, never an archive value.
                        row = row | {'revision': max(current.revision if current else 0, row['revision']) + 1}
                    if current is None:
                        current = model(**row)
                        db.add(current)
                    else:
                        for key in fields[1:]:
                            setattr(current, key, row[key])
                    if model is AlertRule and current.schema_version == 2:
                        from app.services.alerts import _state_for
                        # Same rule -> state lock order and edit semantics as
                        # alert_metrics.save: keep firing/history, but require a
                        # NEW sample under the restored definition. Flush in
                        # _state_for before populate_existing is intentional.
                        state = _state_for(db, current)
                        state.consecutive = 0
                        now = datetime.now(timezone.utc)
                        state.watermark = max(state.watermark, now) if state.watermark else now
                        state.evaluated_at = None
                        state.preview = None
                db.flush()
            _apply_monitor_groups(db, group_plan)
            for row in data['shared']:
                if row['key'] == 'oidc.clients':
                    _restore_oidc_clients(db, row['payload'])
                else:
                    db.execute(insert(state_table).values(**row).on_conflict_do_update(index_elements=['key'], set_={'payload': row['payload']}))
            for profile in data['profiles']:
                current = db.get(User, UUID(profile['id']))
                if current is None:
                    raise InvalidArchive('profile identity missing; use full restore for a new site')
                for key in PROFILE[1:]:
                    setattr(current, key, profile[key])
            for row in sorted(data['config'], key=lambda r: r['key']):
                current = db.get(AppConfig, row['key'], with_for_update=True)
                value = row['value']
                if row['key'] == 'integrations_v1':
                    old = json.loads(current.value) if current else {}
                    # Aliases belong to the archived modules, not to retained
                    # grants/runtime. Absence in an older archive means none.
                    value = json.dumps(old | {'legacy_routes': {}} | json.loads(value))
                elif row['key'] == 'backup_center_v1':
                    old = json.loads(current.value) if current else {'config': {'revision': 0}, 'job': None, 'last_slot': None}
                    saved = json.loads(value)['config']
                    saved['revision'] = old['config']['revision'] + 1
                    value = json.dumps(old | {'config': saved})
                elif row['key'].startswith(('client-preferences:', 'notes-preferences:')):
                    previous = json.loads(current.value) if current else {'revision': 0}
                    incoming = json.loads(value)
                    incoming['revision'] = max(previous.get('revision', 0), incoming.get('revision', 0)) + 1
                    value = json.dumps(incoming)
                if current is None:
                    db.add(AppConfig(key=row['key'], value=value))
                else:
                    current.value = value
            restore_domain(db, native_plan)
            for name in manifest['entries']:
                if name.startswith('resources/') and not name.startswith(PREFIX):
                    fence()
                    with z.open(name) as stream:
                        key = name[len('resources/'):]
                        blob_store.put(db, key, stream, data['resources'][key]['mime'], 1024**3)
            db.flush()
            validate_new(db, [p['home_bg'] for p in data['profiles']] + [p[1] for p in native_plan] + preference_urls(db), previous_media)
            fence()  # Failed ownership check rolls back the actual DB writes.
