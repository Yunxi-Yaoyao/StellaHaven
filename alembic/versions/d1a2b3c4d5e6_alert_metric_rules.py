"""Add metric rule intent/revision and observational state, preserve v1 IDs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='d1a2b3c4d5e6'
down_revision='d0a1b2c3d4e5'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('alert_rules',sa.Column('schema_version',sa.Integer(),nullable=False,server_default='1'))
    op.add_column('alert_rules',sa.Column('revision',sa.Integer(),nullable=False,server_default='1'))
    op.add_column('alert_rules',sa.Column('condition',JSONB(),nullable=True))
    op.add_column('alert_rules',sa.Column('fingerprint',sa.String(64),nullable=True))
    op.create_index('uq_alert_rule_legacy','alert_rules',['kind','target'],unique=True,postgresql_where=sa.text('schema_version = 1'))
    op.create_index('uq_alert_rule_fingerprint','alert_rules',['target','fingerprint'],unique=True,postgresql_where=sa.text('schema_version = 2'))
    op.drop_constraint('uq_alert_rule','alert_rules',type_='unique')
    op.add_column('alert_states',sa.Column('watermark',sa.DateTime(timezone=True),nullable=True))
    op.add_column('alert_states',sa.Column('evaluated_at',sa.DateTime(timezone=True),nullable=True))
    op.add_column('alert_states',sa.Column('preview',JSONB(),nullable=True))

def downgrade():
    raise RuntimeError('Metric rules and interval evidence must be retained; export/review before destructive downgrade')
