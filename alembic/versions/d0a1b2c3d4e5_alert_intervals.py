"""Nullable interval proof; legacy rows deliberately remain unknown."""
from alembic import op
import sqlalchemy as sa
revision = 'd0a1b2c3d4e5'
down_revision = 'c0d1e2f3a4b5'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('node_metrics', sa.Column('interval_start',sa.DateTime(timezone=True),nullable=True))
    op.add_column('node_metrics', sa.Column('elapsed_seconds',sa.Float(),nullable=True))
    op.add_column('node_metrics', sa.Column('quality',sa.String(24),nullable=True))

def downgrade():
    raise RuntimeError('Interval evidence is retained; downgrade requires explicit data export/review')
