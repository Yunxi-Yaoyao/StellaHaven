"""Preserve archived rule definitions and exact incident/notification evidence.

No backfill of invented starts, recoveries, labels or notification associations.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'af20261019'
down_revision = '62a4d9c0e871'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('alert_rules',sa.Column('archived',sa.Boolean(),nullable=False,server_default=sa.false()))
    for name in ('uq_alert_rule_legacy','uq_alert_rule_fingerprint'):
        op.drop_index(name,table_name='alert_rules')
    op.create_index('uq_alert_rule_legacy','alert_rules',['kind','target'],unique=True,
                    postgresql_where=sa.text('schema_version=1 AND NOT archived'))
    op.create_index('uq_alert_rule_fingerprint','alert_rules',['target','fingerprint'],unique=True,
                    postgresql_where=sa.text('schema_version=2 AND NOT archived'))
    op.add_column('alert_events',sa.Column('snapshot',JSONB(),nullable=True))
    op.add_column('notifications',sa.Column('context',JSONB(),nullable=True))
    op.add_column('notifications',sa.Column('dedupe_key',sa.String(192),nullable=True))
    op.create_unique_constraint('uq_notifications_dedupe_key','notifications',['dedupe_key'])
    op.create_index('ix_alert_events_rule_ts_id','alert_events',['rule_id','ts','id'])


def downgrade():
    raise RuntimeError('Archived definitions and incident evidence must be retained; export/review before destructive downgrade')
