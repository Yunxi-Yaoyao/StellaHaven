"""Real list service and router, isolated imports; no production settings/DB.

Offline rows reproduce corrupt JSONB without PostgreSQL accepting NaN first.
The opt-in PG companion uses the same domain and exact-target existing guard.
"""
import copy
import importlib
import json
import sys
import types
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


@contextmanager
def app_modules(modules):
    previous = {k: v for k, v in sys.modules.items() if k == 'app' or k.startswith('app.')}
    attributes = {k: vars(v).copy() for k, v in previous.items() if isinstance(v, types.ModuleType)}
    if 'app' in modules:
        for key in previous:
            sys.modules.pop(key)
    sys.modules.update(modules)
    try:
        yield
    finally:
        for k in list(sys.modules):
            if k == 'app' or k.startswith('app.'):
                sys.modules.pop(k)
        sys.modules.update(previous)
        for k, attrs in attributes.items():
            vars(previous[k]).clear(); vars(previous[k]).update(attrs)


@pytest.fixture
def domain():
    class Base(DeclarativeBase):
        pass
    modules = {}
    for name in ('app', 'app.models', 'app.services', 'app.routers'):
        module = types.ModuleType(name)
        module.__path__ = [str(ROOT / name.replace('.', '/'))]
        modules[name] = module
    modules['app.models'].__dict__.update(Base=Base, Mapped=Mapped, mapped_column=mapped_column, UUID=uuid.UUID, uuid4=uuid.uuid4)
    modules['app.config'] = None
    modules['app.database'] = None
    with app_modules(modules):
        # Real models and service bodies; no eager production registries.
        for name in ('app.models.node', 'app.models.user', 'app.models.config'):
            importlib.import_module(name)
        service = importlib.import_module('app.services.alert_metrics')
        try:
            yield types.SimpleNamespace(service=service)
        finally:
            # Removing modules does not unregister process-global Session hooks.
            for hook, name in [('after_commit', '_after_alert_commit'),
                               ('after_transaction_end', '_after_alert_transaction_end'),
                               ('after_rollback', '_after_alert_rollback'),
                               ('after_soft_rollback', '_after_alert_savepoint_rollback')]:
                event.remove(Session, hook, getattr(service.alerts, name))


class ReadOnlyRows:
    def __init__(self, rows):
        self.rows = rows
    def query(self, *args): return self
    def outerjoin(self, *args): return self
    def filter(self, *args): return self
    def order_by(self, *args): return self
    def all(self): return self.rows
    def commit(self): raise AssertionError('GET committed')
    def flush(self): raise AssertionError('GET flushed')
    def add(self, *args): raise AssertionError('GET wrote')


def condition():
    from app.alert_metrics import Condition
    return Condition(metric='cpu', threshold='80').model_dump(mode='json')


def row(rid=1):
    from app.alert_metrics import Condition, result
    c = condition()
    rule = types.SimpleNamespace(id=rid, target='2', label='retained label', condition=c,
        severity='warning', debounce=2, repeat_minutes=0, email=False, enabled=True, revision=7)
    state = types.SimpleNamespace(state='firing', preview=result(Condition.model_validate(c),
        value=85, quality='valid', watermark=NOW), evaluated_at=NOW)
    return rule, state


def http_list(domain, rows):
    def current(authorization: str = Header('')):
        if authorization != 'reader': raise HTTPException(401)
    def admin(): raise AssertionError('GET invoked admin mutation boundary')
    def get_db(): yield ReadOnlyRows(rows)
    database = types.ModuleType('app.database'); database.get_db = get_db
    auth = types.ModuleType('app.routers.auth'); auth.current_user = current; auth.admin_user = admin
    with app_modules({'app.database': database, 'app.routers.auth': auth}):
        router = importlib.import_module('app.routers.alerts')
        app = FastAPI(); app.include_router(router.router)
        with TestClient(app) as client:
            assert client.get('/alerts/v2/rules').status_code == 401
            response = client.get('/alerts/v2/rules', headers={'authorization': 'reader'})
            assert response.status_code == 200, response.text
            return response.json()


@pytest.mark.parametrize('transport', ['service', 'http'])
def test_invalid_stored_json_is_null_and_marked_without_hiding_healthy_rule(domain, transport):
    good = row(1); bad = row(2)
    bad[0].condition = {'metric': 'private-not-a-metric', 'secret_extension': {'token': 'synthetic-secret'}}
    bad[1].preview = ['not-a-preview', {'token': 'synthetic-secret'}]
    rows = [good, bad]; original = copy.deepcopy(rows)
    output = domain.service.list_rules(ReadOnlyRows(rows)) if transport == 'service' else http_list(domain, rows)
    assert output[1]['condition'] is None
    assert output[1]['preview'] is None
    assert output[1]['projection'] == {'state': 'incomplete', 'invalid_fields': ['condition', 'preview']}
    assert {k: output[1][k] for k in ('id', 'label', 'revision', 'enabled', 'state')} == {
        'id': 2, 'label': 'retained label', 'revision': 7, 'enabled': True, 'state': 'firing'}
    assert output[0]['condition'] == good[0].condition
    assert output[0]['preview'] == good[1].preview
    assert 'projection' not in output[0]
    assert 'synthetic-secret' not in json.dumps(output, default=str)
    assert rows == original


@pytest.mark.parametrize('field,value', [
    ('value', True), ('value', float('nan')), ('value', 'NaN'), ('value', 'Infinity'),
    ('value', '-1'), ('value', '1e9999'), ('value', '1e99999999999999999999'),
    ('value', '1e-99999999999999999999'), ('lower', 'NaN'), ('upper', False),
    ('watermark', 'not-a-time'), ('watermark', '2026-01-01T00:00:00'), ('watermark', 123),
    ('bad', 1), ('bad', False), ('quality', 'secret-quality'), ('reason', 'secret-reason'),
    ('unit', 'byte'), ('quality', 'partial'), ('lower', '90'),
])
def test_preview_known_field_corruption_is_local_and_explicit(domain, field, value):
    good = row(1); bad = row(2); bad[1].preview[field] = value
    before = json.dumps([vars(x) for pair in (good, bad) for x in pair], default=str)
    output = http_list(domain, [good, bad])
    assert output[0]['preview'] == good[1].preview
    assert output[1]['condition'] == bad[0].condition
    assert output[1]['preview'] is None
    assert output[1]['projection']['invalid_fields'] == ['preview']
    assert before == json.dumps([vars(x) for pair in (good, bad) for x in pair], default=str)


def test_extensions_are_discarded_recursively_without_losing_valid_fields(domain):
    good = row()
    good[0].condition['secret_extra'] = {'password': 'synthetic-secret'}
    good[0].condition['window']['secret_extra'] = 'synthetic-secret'
    good[1].preview['secret_extra'] = {'password': 'synthetic-secret'}
    good[1].preview['normalized_condition']['secret_extra'] = 'synthetic-secret'
    good[1].preview['normalized_condition']['window']['secret_extra'] = 'synthetic-secret'
    original = copy.deepcopy(good)
    output = http_list(domain, [good])[0]
    assert output['condition'] == condition()
    assert output['preview']['value'] == '85'
    assert 'projection' not in output
    assert 'synthetic-secret' not in json.dumps(output)
    assert original == good


def test_old_fixed_window_and_decimal_exponent_keep_writer_shape(domain):
    from app.alert_metrics import Condition, result, volume_result
    historic = Condition(metric='network.volume', interface='eth0', direction='out', threshold='9007199254740993',
        window={'kind': 'fixed', 'start': '2001-01-01T00:00:00.123456+00:00',
                'end': '2001-01-02T00:00:00.123456+00:00', 'timezone': 'Asia/Shanghai'})
    r, s = row()
    r.condition = historic.model_dump(mode='json')
    s.preview = volume_result(historic, 9007199254740993, None, NOW)
    output = http_list(domain, [(r, s)])[0]
    assert output['condition'] == r.condition and output['preview'] == s.preview
    assert output['enabled'] is True and 'projection' not in output
    r, s = row()
    s.preview = result(Condition.model_validate(r.condition), value='8E+1', quality='valid', watermark=NOW)
    assert http_list(domain, [(r, s)])[0]['preview'] == s.preview


@pytest.mark.parametrize('slot,value', [('condition', None), ('condition', []), ('preview', {}), ('preview', False)])
def test_missing_or_wrong_json_slot_is_not_a_normal_record(domain, slot, value):
    r, s = row()
    setattr(r if slot == 'condition' else s, slot, value)
    output = http_list(domain, [(r, s)])[0]
    assert output[slot] is None and slot in output['projection']['invalid_fields']


def test_invalid_definition_without_state_does_not_invent_ok(domain):
    r, _ = row(); r.condition = {'metric': 'unknown'}
    output = http_list(domain, [(r, None)])[0]
    assert output['state'] == 'unknown'
    assert output['condition'] is None and output['enabled'] is True
    assert output['projection']['invalid_fields'] == ['condition']


def test_absent_state_and_unevaluated_preview_remain_normal(domain):
    r, s = row(); s.preview = None; s.evaluated_at = None
    for pair in ((r, None), (r, s)):
        output = http_list(domain, [pair])[0]
        assert output['preview'] is None and output['evaluated_at'] is None
        assert output['state'] == ('ok' if pair[1] is None else 'firing')
        assert 'projection' not in output


@pytest.mark.parametrize('field,value,public,expected', [
    ('target', 'private-target', 'node_id', None), ('target', '-5', 'node_id', None),
    ('severity', 'private-severity', 'severity', None), ('state', 'invalid', 'state', 'unknown'),
])
def test_malformed_relational_labels_do_not_break_sibling_rows(domain, field, value, public, expected):
    good = row(1); bad = row(2)
    setattr(bad[1] if field == 'state' else bad[0], field, value)
    output = http_list(domain, [good, bad])
    assert output[0]['preview'] == good[1].preview
    assert output[1][public] == expected
    assert public in output[1]['projection']['invalid_fields']
    assert output[1]['enabled'] is True and output[1]['revision'] == 7


@pytest.mark.parametrize('change', [
    {'threshold': True}, {'threshold': 'NaN'}, {'metric': 'memory', 'direction': 'in'},
    {'metric': 'network.rate', 'interface': 'eth0', 'direction': 'any'},
    {'metric': 'network.utilization', 'interface': 'eth0', 'direction': 'in',
     'capacity': {'mode': 'independent', 'in_bps': True}},
    {'metric': 'network.volume', 'interface': 'eth0', 'direction': 'out',
     'window': {'kind': 'fixed', 'start': 123, 'end': 456, 'timezone': 'UTC'}},
    {'metric': 'network.volume', 'interface': 'eth0', 'direction': 'out',
     'window': {'kind': 'fixed', 'start': '2001-01-01T00:00:00Z', 'end': '2001-03-01T00:00:00Z', 'timezone': 'UTC'}},
])
def test_condition_semantics_and_strict_capacity_survive_storage_boundary(domain, change):
    r, s = row(); r.condition.update(change)
    output = http_list(domain, [(r, s)])[0]
    assert output['condition'] is None and output['preview'] is None
    assert output['projection']['invalid_fields'] == ['condition', 'preview']
    assert output['enabled'] is True


@pytest.mark.parametrize('field', ['value', 'lower', 'upper', 'quality', 'reason', 'bad', 'unit', 'watermark', 'normalized_condition'])
def test_preview_requires_every_writer_field(domain, field):
    r, s = row(); del s.preview[field]
    output = http_list(domain, [(r, s)])[0]
    assert output['preview'] is None and output['projection']['invalid_fields'] == ['preview']


@pytest.mark.parametrize('change', [
    {'reason': 'history_missing'}, {'watermark': '20261016T000000Z'},
])
def test_preview_reason_and_timestamp_match_actual_writer(domain, change):
    r, s = row(); s.preview.update(change)
    output = http_list(domain, [(r, s)])[0]
    assert output['preview'] is None


def test_every_real_writer_shape_matches_public_schema_and_pg_fixture(domain):
    from app.alert_metrics import Condition, result, volume_result, evaluate
    from app.public_alert_metrics import PublicMetricRule
    from pydantic import TypeAdapter
    from jsonschema import Draft202012Validator, FormatChecker
    from datetime import timedelta
    schema = TypeAdapter(list[PublicMetricRule]).json_schema(mode='serialization')
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    Draft202012Validator.check_schema(schema)
    cases = []
    for metric in ('cpu', 'memory', 'root_disk', 'network.rate', 'network.utilization', 'network.volume'):
        data = {'metric': metric, 'threshold': '80'}
        if metric.startswith('network.'):
            data.update(interface='eth0', direction='out')
        if metric == 'network.utilization':
            data['capacity'] = {'mode': 'independent', 'out_bps': 1000}
        if metric == 'network.volume':
            data['window'] = {'kind': 'fixed', 'start': (NOW-timedelta(days=1)).isoformat(), 'end': NOW.isoformat(), 'timezone': 'UTC'}
        c = Condition.model_validate(data)
        reasons = ('target_missing', 'interface_missing', 'scheduled', 'query_unavailable', 'query_budget',
            'history_missing', 'overlapping_intervals', 'evaluation_lag', 'clock_skew', 'stale',
            'metric_missing', 'legacy_interval', 'invalid_interval')
        previews = [result(c, reason=reason) for reason in reasons]
        if metric == 'network.volume':
            previews += [volume_result(c, 100, 100, NOW), volume_result(c, 60, 100, NOW),
                volume_result(c, 100, None, NOW), volume_result(c, 0, 70, NOW)]
        else:
            previews += [result(c, value='8E+1', quality='valid', watermark=NOW),
                result(c, value='8E+1', quality='valid', reason='future_clock_quarantined', watermark=NOW)]
            points = [{'ts': NOW, 'interval_start': NOW-timedelta(seconds=10), 'elapsed_seconds': 10,
                       'quality': 'valid', 'rx_delta': 100, 'tx_delta': 100, 'cpu_pct': 80, 'mem_pct': 80, 'disk_pct': 80}]
            previews.append(evaluate(c, points, NOW))
        for preview in previews:
            r, s = row(); r.condition = c.model_dump(mode='json'); s.preview = preview
            output = http_list(domain, [(r, s)])
            assert output[0]['preview'] == preview and 'projection' not in output[0]
            validator.validate(output); cases.extend(output)
    fixture = json.loads((ROOT/'frontend/tests/fixtures/publicAlertProjection.json').read_text())
    assert fixture == json.loads((ROOT/'remediation/alerts-public-read/pg-public-samples.json').read_text())
    validator.validate(fixture)
    # Schema is closed at every object (including nullable nested Condition).
    def closed(value):
        if isinstance(value, dict):
            if value.get('type') == 'object': assert value.get('additionalProperties') is False
            for child in value.values(): closed(child)
        elif isinstance(value, list):
            for child in value: closed(child)
    closed(schema)
    assert len(cases) > 90
