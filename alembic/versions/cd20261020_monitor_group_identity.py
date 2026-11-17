"""Persistent identity for exact settings archive group restores.

Revision ID: cd20261020
Revises: cc20261020
"""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = 'cd20261020'
down_revision = 'cc20261020'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('monitor_groups', sa.Column('stable_uuid', sa.String(36), nullable=True))
    groups = sa.table('monitor_groups', sa.column('id', sa.Integer()), sa.column('stable_uuid', sa.String(36)))
    conn = op.get_bind()
    for group_id in conn.execute(sa.select(groups.c.id)).scalars():
        conn.execute(groups.update().where(groups.c.id == group_id).values(stable_uuid=str(uuid4())))
    with op.batch_alter_table('monitor_groups') as batch:
        batch.alter_column('stable_uuid', existing_type=sa.String(36), nullable=False)
        batch.create_unique_constraint('uq_monitor_groups_stable_uuid', ['stable_uuid'])


def downgrade():
    with op.batch_alter_table('monitor_groups') as batch:
        batch.drop_constraint('uq_monitor_groups_stable_uuid', type_='unique')
        batch.drop_column('stable_uuid')
