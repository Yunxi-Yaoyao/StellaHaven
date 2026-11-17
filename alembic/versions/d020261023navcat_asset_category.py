"""Native navigation asset purposes; additive, no other domain tables."""
from alembic import op
import sqlalchemy as sa
revision='d020261023navcat'
down_revision='cf20261023nav'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('nav_assets',sa.Column('category',sa.String(24),nullable=False,server_default='uncategorized'))


def downgrade():
    op.drop_column('nav_assets','category')
