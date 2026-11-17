from test_lifecycle import db, rule, alerts, NOW, AlertEvent, Notification


def test_additive_migration_retains_legacy_events_and_notification_identity(db):
    from importlib import import_module
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    r=rule(db);alerts._evaluate(db,r,True,'old evidence',NOW);db.commit()
    event_id=db.query(AlertEvent).one().id
    note_id=db.query(Notification).one().id
    db.rollback()
    with db.bind.begin() as c:
        assert c.execute(text("select current_database(),current_user,current_setting('stella.test_isolation')")).one()==('alerts_test','stella_alert_test','alerts-feedback-owned')
        c.execute(text('ALTER TABLE notifications DROP COLUMN dedupe_key, DROP COLUMN context'))
        c.execute(text('ALTER TABLE alert_events DROP COLUMN snapshot'))
        c.execute(text('DROP INDEX uq_alert_rule_legacy'))
        c.execute(text('DROP INDEX uq_alert_rule_fingerprint'))
        c.execute(text('ALTER TABLE alert_rules DROP COLUMN archived'))
        c.execute(text('CREATE UNIQUE INDEX uq_alert_rule_legacy ON alert_rules(kind,target) WHERE schema_version=1'))
        c.execute(text('CREATE UNIQUE INDEX uq_alert_rule_fingerprint ON alert_rules(target,fingerprint) WHERE schema_version=2'))
        from importlib.util import spec_from_file_location,module_from_spec
        from pathlib import Path
        spec=spec_from_file_location('migration',Path(__file__).resolve().parents[1]/'alembic/versions/af20261019_alert_history.py')
        migration=module_from_spec(spec);spec.loader.exec_module(migration)
        with Operations.context(MigrationContext.configure(c)):
            migration.upgrade()
        assert c.execute(text('select id,snapshot from alert_events')).one()==(event_id,None)
        assert c.execute(text('select id,context,dedupe_key from notifications')).one()==(note_id,None,None)
        assert c.execute(text('select archived,enabled from alert_rules')).one()==(False,True)
