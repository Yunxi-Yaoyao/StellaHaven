"""Non-destructive persisted monitor visibility and scheduling switches.

Revision ID: ce20261021
Revises: cd20261020
"""
from alembic import op
import sqlalchemy as sa

revision = 'ce20261021'
down_revision = 'cd20261020'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('monitors', 'monitor_groups'):
        for flag in ('visible', 'enabled'):
            op.add_column(table, sa.Column(flag, sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    # Dropping false flags would silently reveal/restart measurements. Require an
    # explicit operator decision first; inspect BOTH tables before any DDL.
    conn = op.get_bind()
    for name in ('monitors', 'monitor_groups'):
        table = sa.table(name, sa.column('visible', sa.Boolean()), sa.column('enabled', sa.Boolean()))
        if conn.execute(sa.select(sa.literal(1)).select_from(table).where(
                sa.or_(table.c.visible.is_(False), table.c.enabled.is_(False))).limit(1)).first():
            raise RuntimeError('拒绝降级：仍有隐藏或停用监控，请先明确恢复开关或保留此版本')
    for table in ('monitor_groups', 'monitors'):
        with op.batch_alter_table(table) as batch:
            batch.drop_column('enabled')
            batch.drop_column('visible')
