"""Real settings ZIP/checksum service chain; isolated SQLite, no app startup/live DB."""
import io
import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from sqlalchemy import Integer, JSON, MetaData, create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.config import AppConfig
from app.models.node import Node
from app.models.monitor import Monitor, MonitorCheck, MonitorGroup, MonitorGroupMember
from app.models.user import User
from app.models.alert import AlertRule
from app.models.blob import BlobObject
from app.services import backup_projection as backup, entry_monitoring, entry_registry
from app.services.backup_archive import InvalidArchive, create_archive, validate_archive
from app.schemas.control_channel import ControlChannel


@pytest.fixture
def archive_db(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool)
    models = (Node, Monitor, MonitorGroup, MonitorGroupMember, AppConfig, MonitorCheck, User, AlertRule, BlobObject)
    metadata = MetaData()
    for model in models:
        table = model.__table__.to_metadata(metadata)
        for column in table.c:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    metadata.tables['monitor_checks'].c.id.type = Integer()
    metadata.create_all(engine)
    with engine.connect() as conn:
        conn.connection.driver_connection.create_function('octet_length', 1, lambda s: len(s.encode()))
    monkeypatch.setattr(backup, 'require_settings_mode', lambda: None)
    monkeypatch.setattr(entry_registry, 'records', lambda: {'stella': {'public': 'https://main.example', 'private': None}})
    with Session(engine) as db:
        # Reconciliation now requires authenticated inventory (last_seen_at), not
        # merely an unreported row with a synthetic capability declaration.
        n = Node(name='owned', host='192.168.160.3', platform='linux', token='fixture-token',
                 status='online', last_seen_at=datetime.now(timezone.utc),
                 components={'monitoring': {'ready': True, 'types': ['ping'], 'targets': ['192.168.160.3']}})
        db.add(n); db.commit()
        e = entry_monitoring.manifest(n)['entries'][0]
        entry_monitoring.save_channel(db, n, ControlChannel(icmp=[dict(entry_id=e['entry_id'], version=e['version'],
            hostname=e['hostname'], sampled_at=datetime.now(timezone.utc), status='complete',
            results=[dict(ip='192.168.160.3', family=4, status='up', latency_ms=1.2, loss_pct=0)])]))
        probes = [Monitor(name=f'manual{i}', node_id=n.id, type='tcp', target=f'owned:{443+i}', interval=60, timeout=5) for i in range(4)]
        db.add_all(probes); db.commit()
        db.add(AlertRule(kind='monitor_down', target=str(probes[0].id), label='fixture rule')); db.commit()
        from app.services.monitor_groups import save_group
        group = save_group(db, None, name='saved group', child_ids=[probes[1].id, probes[0].id])
        yield db, engine, n.id, [m.id for m in probes], group['id'], models
    engine.dispose()


def make_zip(env, tmp_path, mutate=lambda data: None):
    _, engine, *_ = env
    with engine.connect() as conn, backup.export_settings(conn, str(tmp_path)) as payload:
        data = json.loads(payload.entries['settings.json'].getvalue())
        mutate(data)
        from uuid import uuid4
        path = tmp_path / f'settings-{uuid4()}.zip'
        create_archive(path, scope='settings', entries=payload.entries | {'settings.json': io.BytesIO(json.dumps(data).encode())})
    assert validate_archive(path)['scope'] == 'settings'
    return path


def snapshot(env):
    db, engine, *_, models = env
    db.expire_all()
    with engine.connect() as conn:
        return {m.__tablename__: sorted(repr(dict(r)) for r in conn.execute(select(m.__table__)).mappings()) for m in models}


def reject_without_writes(env, path):
    before = snapshot(env)
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split()[0].upper() in ('INSERT', 'UPDATE', 'DELETE'):
            statements.append(statement)
    event.listen(env[1], 'before_cursor_execute', record)
    try:
        with pytest.raises(InvalidArchive):
            backup.restore_settings(env[1], path)
    finally:
        event.remove(env[1], 'before_cursor_execute', record)
    assert statements == [], 'invalid archive must be preflighted before any database mutation'
    assert snapshot(env) == before


ID_FIELDS = [('nodes', 'id'), ('monitors', 'id'), ('monitors', 'node_id'),
             ('alert_rules', 'id'),
             ('monitor_groups', 'id'), ('monitor_group_members', 'group_id'), ('monitor_group_members', 'monitor_id')]


@pytest.mark.parametrize('table,field', ID_FIELDS)
@pytest.mark.parametrize('invalid', [True, False, 1.0, '1', '01', 0, -1, None])
def test_strict_ids_rejected_before_any_write(archive_db, tmp_path, table, field, invalid):
    def mutate(data):
        data['tables'][table][0][field] = invalid
    reject_without_writes(archive_db, make_zip(archive_db, tmp_path, mutate))


@pytest.mark.parametrize('position', [True, False, 0.0, '0', -1, None, 2])
def test_positions_are_nonnegative_real_integers_and_contiguous(archive_db, tmp_path, position):
    def mutate(data):
        data['tables']['monitor_group_members'][0]['position'] = position
    reject_without_writes(archive_db, make_zip(archive_db, tmp_path, mutate))


@pytest.mark.parametrize('table', ['nodes', 'monitors', 'alert_rules', 'monitor_groups', 'monitor_group_members'])
def test_duplicate_rows_rejected_without_writes(archive_db, tmp_path, table):
    def mutate(data):
        data['tables'][table].append(deepcopy(data['tables'][table][0]))
    reject_without_writes(archive_db, make_zip(archive_db, tmp_path, mutate))


def test_duplicate_positions_rejected_without_writes(archive_db, tmp_path):
    def mutate(data):
        data['tables']['monitor_group_members'][1]['position'] = 0
    reject_without_writes(archive_db, make_zip(archive_db, tmp_path, mutate))


@pytest.mark.parametrize('table', ['nodes', 'monitors', 'alert_rules', 'monitor_groups', 'monitor_group_members'])
def test_unknown_row_keys_rejected_without_writes(archive_db, tmp_path, table):
    def mutate(data):
        data['tables'][table][0]['unsupported_identity'] = 'must not be ignored'
    reject_without_writes(archive_db, make_zip(archive_db, tmp_path, mutate))


def test_same_identity_restores_exact_members_order_and_mutable_metadata(archive_db, tmp_path):
    from app.services.monitor_groups import save_group
    db, engine, _, mids, gid, _ = archive_db
    original_uuid = db.get(MonitorGroup, gid).stable_uuid
    path = make_zip(archive_db, tmp_path)
    save_group(db, gid, name='renamed live', child_ids=[mids[2], mids[0], mids[1]], failure_policy='all', rotation_seconds=30)
    backup.restore_settings(engine, path)
    db.expire_all()
    g = db.get(MonitorGroup, gid)
    assert (g.stable_uuid, g.name, g.failure_policy, g.rotation_seconds) == (original_uuid, 'saved group', 'any', 0)
    members = db.query(MonitorGroupMember).filter_by(group_id=gid).order_by(MonitorGroupMember.position).all()
    assert [(m.monitor_id, m.position) for m in members] == [(mids[1], 0), (mids[0], 1)]


@pytest.mark.parametrize('identity', ['different', 'missing', 'malformed', 'noncanonical'])
def test_live_numeric_collision_requires_exact_canonical_uuid(archive_db, tmp_path, identity):
    from uuid import uuid4
    def mutate(data):
        row = data['tables']['monitor_groups'][0]
        row['name'] = 'cannot take over live group'
        if identity == 'missing':
            row.pop('stable_uuid', None)
        else:
            row['stable_uuid'] = str(uuid4()) if identity == 'different' else ('not-a-uuid' if identity == 'malformed' else str(uuid4()).upper())
    reject_without_writes(archive_db, make_zip(archive_db, tmp_path, mutate))


def test_uuid_cannot_be_remapped_implicitly_to_another_numeric_id(archive_db, tmp_path):
    db, _, _, _, gid, _ = archive_db
    def mutate(data):
        data['tables']['monitor_groups'][0]['id'] = gid + 100
        for member in data['tables']['monitor_group_members']:
            member['group_id'] = gid + 100
    path = make_zip(archive_db, tmp_path, mutate)
    # No live members to obscure the stable-UUID conflict with a membership conflict.
    db.query(MonitorGroupMember).filter_by(group_id=gid).delete(); db.commit()
    reject_without_writes(archive_db, path)


def test_deleted_group_numeric_id_reused_by_new_group_is_not_same_identity(archive_db, tmp_path):
    db, _, _, mids, gid, _ = archive_db
    path = make_zip(archive_db, tmp_path)
    db.query(MonitorGroupMember).filter_by(group_id=gid).delete()
    db.query(MonitorGroup).filter_by(id=gid).delete(); db.commit()
    db.add(MonitorGroup(id=gid, name='new unrelated group')); db.commit()
    reject_without_writes(archive_db, path)


def test_export_is_read_only_and_stable_identity_persists_across_exports(archive_db, tmp_path):
    before = snapshot(archive_db)
    ids = []
    for i in range(2):
        def inspect_export(data):
            ids.append(data['tables']['monitor_groups'][0]['stable_uuid'])
        make_zip(archive_db, tmp_path, inspect_export)
    assert ids[0] == ids[1]
    assert snapshot(archive_db) == before


def test_sparse_live_positions_export_canonical_order_without_db_writes(archive_db, tmp_path):
    db, engine, _, mids, gid, _ = archive_db
    members = db.query(MonitorGroupMember).filter_by(group_id=gid).order_by(MonitorGroupMember.position).all()
    members[0].position = 4; members[1].position = 9; db.commit()
    before = snapshot(archive_db)
    def inspect_export(data):
        rows = [r for r in data['tables']['monitor_group_members'] if r['group_id'] == gid]
        assert [(r['monitor_id'], r['position']) for r in rows] == [(mids[1], 0), (mids[0], 1)]
    path = make_zip(archive_db, tmp_path, inspect_export)
    assert snapshot(archive_db) == before
    backup.restore_settings(engine, path)


@pytest.mark.parametrize('field', ['monitor', 'group', 'member'])
@pytest.mark.parametrize('alias', ['integer', 'string', 'leadingzero', 'float', 'bool'])
@pytest.mark.parametrize('deleted', [False, True])
def test_automatic_and_tombstone_aliases_never_adopted(archive_db, tmp_path, field, alias, deleted):
    db, _, nid, mids, _, _ = archive_db
    auto_mid = db.query(Monitor).filter_by(type='ping').one().id
    # Both entry lanes now own groups, even when the private lane is empty.
    # Select the actual automatic probe's parent, never infer ownership by name.
    auto_group = (db.query(MonitorGroup).join(MonitorGroupMember)
                  .filter(MonitorGroupMember.monitor_id == auto_mid).one())
    auto_gid, auto_uuid = auto_group.id, auto_group.stable_uuid
    if deleted:
        db.query(MonitorGroupMember).filter_by(group_id=auto_gid).delete()
        db.query(MonitorGroup).filter_by(id=auto_gid).delete()
        db.query(MonitorCheck).filter_by(monitor_id=auto_mid).delete()
        db.query(Monitor).filter_by(id=auto_mid).delete(); db.commit()
    def value(i):
        return {'integer': i, 'string': str(i), 'leadingzero': f'0{i}', 'float': float(i), 'bool': True}[alias]
    def mutate(data):
        if field == 'monitor':
            data['tables']['monitors'][0]['id'] = value(auto_mid)
        elif field == 'group':
            data['tables']['monitor_groups'][0].update(id=value(auto_gid), stable_uuid=auto_uuid)
            for m in data['tables']['monitor_group_members']:
                m['group_id'] = value(auto_gid)
        else:
            data['tables']['monitor_group_members'][0]['monitor_id'] = value(auto_mid)
    reject_without_writes(archive_db, make_zip(archive_db, tmp_path, mutate))


def test_late_invalid_group_preflight_does_not_write_earlier_rows(archive_db, tmp_path):
    from uuid import uuid4
    def mutate(data):
        data['tables']['nodes'][0]['name'] = 'must not update first'
        data['tables']['monitors'][0]['target'] = 'must-not-write:443'
        data['tables']['monitor_groups'].append(dict(id=900, name='late invalid group', failure_policy='any', rotation_seconds=0, stable_uuid=str(uuid4())))
        data['tables']['monitor_group_members'].extend([dict(group_id=900, monitor_id=mid, position=pos) for mid, pos in [(4, 0), (5, 2)]])
    reject_without_writes(archive_db, make_zip(archive_db, tmp_path, mutate))


def test_cross_group_conflict_is_rejected_in_preflight(archive_db, tmp_path):
    from app.services.monitor_groups import save_group
    db, _, _, mids, _, _ = archive_db
    path = make_zip(archive_db, tmp_path)
    # Move one archived member to another real live group.
    db.query(MonitorGroupMember).filter_by(monitor_id=mids[0]).delete(); db.commit()
    save_group(db, None, name='unrelated', child_ids=[mids[0], mids[2]])
    reject_without_writes(archive_db, path)


def test_final_fence_failure_rolls_back_real_applied_group_and_monitor_changes(archive_db, tmp_path):
    db, engine, _, mids, gid, _ = archive_db
    def mutate(data):
        data['tables']['monitors'][0]['name'] = 'would change'
        data['tables']['monitor_groups'][0]['name'] = 'would change group'
        data['tables']['monitor_group_members'].reverse()
        for i, row in enumerate(data['tables']['monitor_group_members']):
            row['position'] = i
    path = make_zip(archive_db, tmp_path, mutate)
    before = snapshot(archive_db)
    calls = []
    def fence():
        calls.append(True)
        if len(calls) == 2:
            raise RuntimeError('fixture lost final ownership')
    with pytest.raises(RuntimeError, match='final ownership'):
        backup.restore_settings(engine, path, fence=fence)
    assert len(calls) == 2
    assert snapshot(archive_db) == before


@pytest.mark.parametrize('kind', ['no_groups', 'legacy_groups', 'new_groups'])
def test_legacy_compatibility_and_missing_group_recreation(archive_db, tmp_path, kind):
    db, engine, _, _, gid, _ = archive_db
    original_uuid = db.get(MonitorGroup, gid).stable_uuid
    def mutate(data):
        if kind == 'no_groups':
            data['tables'].pop('monitor_groups'); data['tables'].pop('monitor_group_members')
        elif kind == 'legacy_groups':
            for g in data['tables']['monitor_groups']:
                g.pop('stable_uuid')
    path = make_zip(archive_db, tmp_path, mutate)
    if kind != 'no_groups':
        db.query(MonitorGroupMember).filter_by(group_id=gid).delete()
        db.query(MonitorGroup).filter_by(id=gid).delete(); db.commit()
    backup.restore_settings(engine, path)
    db.expire_all()
    group = db.get(MonitorGroup, gid)
    assert group.name == 'saved group'
    if kind != 'legacy_groups':
        assert group.stable_uuid == original_uuid
    assert db.query(MonitorGroupMember).filter_by(group_id=gid).count() == 2


def test_duplicate_stable_uuid_rejected_before_writes(archive_db, tmp_path):
    def mutate(data):
        group = deepcopy(data['tables']['monitor_groups'][0]); group['id'] = 900
        data['tables']['monitor_groups'].append(group)
    reject_without_writes(archive_db, make_zip(archive_db, tmp_path, mutate))


def test_missing_manual_probes_and_group_recreated_together_after_preflight(archive_db, tmp_path):
    db, engine, _, mids, gid, _ = archive_db
    original_uuid = db.get(MonitorGroup, gid).stable_uuid
    path = make_zip(archive_db, tmp_path)
    db.query(MonitorGroupMember).filter_by(group_id=gid).delete()
    db.query(MonitorGroup).filter_by(id=gid).delete()
    db.query(Monitor).filter(Monitor.id.in_(mids[:2])).delete(); db.commit()
    backup.restore_settings(engine, path); db.expire_all()
    assert db.get(MonitorGroup, gid).stable_uuid == original_uuid
    assert all(db.get(Monitor, mid) is not None for mid in mids)
    assert [m.monitor_id for m in db.query(MonitorGroupMember).filter_by(group_id=gid).order_by(MonitorGroupMember.position)] == [mids[1], mids[0]]


def test_checksum_tampering_rejected_before_database_writes(archive_db, tmp_path):
    import zipfile
    path = make_zip(archive_db, tmp_path)
    with zipfile.ZipFile(path) as z:
        entries = {name: z.read(name) for name in z.namelist()}
    entries['settings.json'] += b' '
    corrupt = tmp_path / 'corrupt.zip'
    with zipfile.ZipFile(corrupt, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, raw in entries.items():
            z.writestr(name, raw)
    reject_without_writes(archive_db, corrupt)
