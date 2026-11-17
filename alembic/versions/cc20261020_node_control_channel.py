"""Latest completed control-channel measurements; old Agents remain NULL.

Revision ID: cc20261020
Revises: bf20261019
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = 'cc20261020'
down_revision = 'bf20261019'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('nodes', sa.Column('control_channel', postgresql.JSONB(), nullable=True))


def downgrade():
    # Back up control_channel before downgrade if samples must be retained.
    op.drop_column('nodes', 'control_channel')
