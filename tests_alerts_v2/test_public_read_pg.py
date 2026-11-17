"""Owned PostgreSQL + actual alert router list; no main or production settings."""
import importlib
import json
import os
import sys
import types
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from test_persistence import domain, db, NOW, ROOT


def test_real_pg_list_is_readonly_and_keeps_history(domain, db, monkeypatch):
    from app.alert_metrics import Condition, result
    seen = []
    monkeypatch.setattr(domain.legacy, '_push_ws', seen.append)
    good = domain.svc.save(db, dict(node_id=1, label='healthy firing', condition={'metric': 'cpu', 'threshold': '80'},
        debounce=1, email=False), now=NOW-timedelta(minutes=1))
    bad = domain.svc.save(db, dict(node_id=1, label='invalid retained', condition={'metric': 'memory', 'threshold': '80'},
        debounce=1, email=False), now=NOW-timedelta(minutes=1))
    old = domain.svc.save(db, dict(node_id=1, label='historical window', enabled=False, email=False,
        condition={'metric': 'network.volume', 'interface': 'eth0', 'direction': 'out', 'threshold': '100',
            'window': {'kind': 'fixed', 'start': '2001-01-01T00:00:00+00:00', 'end': '2001-01-02T00:00:00+00:00', 'timezone': 'UTC'}}), now=NOW)
    for r in (good, bad):
        domain.legacy._evaluate(db, r, True, 'retained history', NOW)
        s = db.get(domain.alert.AlertState, r.id)
        s.preview = result(Condition.model_validate(r.condition), value=85, quality='valid', watermark=NOW)
        s.evaluated_at = NOW
    bad.condition = {'metric': 'unknown', 'secret_extension': {'token': 'synthetic-secret'}}
    db.get(domain.alert.AlertState, bad.id).preview = ['malformed', {'token': 'synthetic-secret'}]
    domain.legacy.create_rule(db, 'node_offline', '1', email=False)
    db.commit(); seen.clear()
    ids = (good.id, bad.id, old.id)
    connection = db.get_bind()
    def snapshot(session):
        return {table: session.execute(text(f'SELECT row_to_json(t)::text FROM {table} t ORDER BY 1')).scalars().all()
                for table in ('alert_rules', 'alert_states', 'alert_events', 'notifications')}
    before = snapshot(db); db.commit()
    statements = []
    def read_only_sql(conn, cursor, statement, *args):
        statements.append(statement.split()[0].upper())
        assert statement.lstrip().upper().startswith('SELECT'), 'list issued non-SELECT'
    def forbidden(*args, **kwargs): raise AssertionError('GET committed/flushed/queued notification')
    def current(authorization: str = Header('')):
        if authorization != 'reader': raise HTTPException(401)
    def admin(): raise AssertionError('GET used admin writer')
    def get_db():
        with Session(connection, autoflush=False) as session:
            session.execute(text('SET TRANSACTION READ ONLY'))
            monkeypatch.setattr(session, 'commit', forbidden)
            monkeypatch.setattr(session, 'flush', forbidden)
            event.listen(connection, 'before_cursor_execute', read_only_sql)
            try:
                yield session
                assert not session.dirty and not session.new and not session.deleted
            finally:
                event.remove(connection, 'before_cursor_execute', read_only_sql)
    database = types.ModuleType('app.database'); database.get_db = get_db
    auth = types.ModuleType('app.routers.auth'); auth.current_user = current; auth.admin_user = admin
    routers = types.ModuleType('app.routers'); routers.__path__ = [str(ROOT/'app/routers')]
    with patch.dict(sys.modules, {'app.database': database, 'app.routers.auth': auth, 'app.routers': routers}):
        router = importlib.import_module('app.routers.alerts')
        app = FastAPI(); app.include_router(router.router)
        with TestClient(app) as client:
            assert client.get('/alerts/v2/rules').status_code == 401
            response = client.get('/alerts/v2/rules', headers={'authorization': 'reader'})
            assert response.status_code == 200, response.text
            data = response.json()
            assert len(data) == 3 and [r['id'] for r in data] == list(ids)
            assert 'projection' not in data[0] and data[0]['preview']['value'] == '85'
            assert data[0]['state'] == 'firing'
            assert data[1]['condition'] is None and data[1]['preview'] is None
            assert data[1]['projection']['invalid_fields'] == ['condition', 'preview']
            assert data[1]['enabled'] is True and data[1]['state'] == 'firing'
            assert data[2]['condition']['window']['start'].startswith('2001-') and data[2]['enabled'] is False
            assert 'projection' not in data[2]
            assert 'synthetic-secret' not in response.text
        sys.modules.pop('app.routers.alerts', None)
    assert statements == ['SELECT'] and seen == []
    with Session(connection, autoflush=False) as fresh:
        assert snapshot(fresh) == before
    # Receipt contains only synthetic public data and exact table equality facts.
    if os.environ.get('ALERTS_PUBLIC_EVIDENCE'):
        out = Path(os.environ['ALERTS_PUBLIC_EVIDENCE'])
        (out/'pg-public-samples.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
        (out/'pg-readonly.json').write_text(json.dumps({'statements': statements, 'tables_equal': list(before),
            'dispatch_count': len(seen), 'fresh_session_equal': True}, indent=2)+'\n')
