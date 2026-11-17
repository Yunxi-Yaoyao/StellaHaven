"""Explicit monitor parents and membership; no probe or history migration.
Revision ID: 94c6a201b732
Revises: 83b5f190a621
"""
from alembic import op
import sqlalchemy as sa
revision = '94c6a201b732'
down_revision = '83b5f190a621'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('monitor_groups',
        sa.Column('id',sa.Integer(),primary_key=True,autoincrement=True),
        sa.Column('name',sa.String(64),nullable=False),
        sa.Column('failure_policy',sa.String(8),nullable=False),
        sa.Column('rotation_seconds',sa.Integer(),nullable=False))
    op.create_table('monitor_group_members',
        sa.Column('group_id',sa.Integer(),sa.ForeignKey('monitor_groups.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('monitor_id',sa.Integer(),sa.ForeignKey('monitors.id',ondelete='CASCADE'),primary_key=True,unique=True),
        sa.Column('position',sa.Integer(),nullable=False))


def downgrade():
    op.drop_table('monitor_group_members')
    op.drop_table('monitor_groups')
