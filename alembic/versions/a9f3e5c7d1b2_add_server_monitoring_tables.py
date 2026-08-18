"""add server monitoring tables

Revision ID: a9f3e5c7d1b2
Revises: 7c4d9a1e2b3f
Create Date: 2026-08-14 00:50:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'a9f3e5c7d1b2'
down_revision: Union[str, Sequence[str], None] = '7c4d9a1e2b3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- 节点域 ----
    op.create_table('nodes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('platform', sa.String(16), nullable=False),
        sa.Column('host', sa.String(128), nullable=False),
        sa.Column('arch', sa.String(32), nullable=True),
        sa.Column('agent_version', sa.String(32), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('token', sa.String(64), nullable=True),
        sa.Column('interfaces', JSONB(), nullable=True),
        sa.Column('monitored_ifaces', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token')
    )

    op.create_table('node_metrics',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=False),
        sa.Column('iface', sa.String(32), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('rx_delta', sa.BigInteger(), nullable=False),
        sa.Column('tx_delta', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['node_id'], ['nodes.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('node_id', 'iface', 'ts', name='uq_node_metric')
    )

    op.create_table('node_sys_metrics',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cpu_pct', sa.Float(), nullable=True),
        sa.Column('mem_pct', sa.Float(), nullable=True),
        sa.Column('disk_pct', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['node_id'], ['nodes.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('node_id', 'ts', name='uq_node_sys_metric')
    )

    op.create_table('node_status_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason', sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(['node_id'], ['nodes.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # ---- 监控项域 ----
    op.create_table('monitors',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=True),
        sa.Column('type', sa.String(16), nullable=False),
        sa.Column('target', sa.String(256), nullable=False),
        sa.Column('interval', sa.Integer(), nullable=False),
        sa.Column('timeout', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('last_check_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_latency_ms', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['node_id'], ['nodes.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('monitor_checks',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('monitor_id', sa.Integer(), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('latency_ms', sa.Float(), nullable=True),
        sa.Column('loss_pct', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['monitor_id'], ['monitors.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('monitor_id', 'ts', name='uq_monitor_check')
    )

    # ---- 任务域 ----
    op.create_table('iperf_tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('server_node_id', sa.Integer(), nullable=True),
        sa.Column('client_node_id', sa.Integer(), nullable=False),
        sa.Column('mode', sa.String(16), nullable=False),
        sa.Column('direction', sa.String(16), nullable=False),
        sa.Column('duration', sa.Integer(), nullable=False),
        sa.Column('parallel', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('result_json', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['server_node_id'], ['nodes.id']),
        sa.ForeignKeyConstraint(['client_node_id'], ['nodes.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('mtr_tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=False),
        sa.Column('target', sa.String(256), nullable=False),
        sa.Column('protocol', sa.String(8), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('result_json', JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['node_id'], ['nodes.id']),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('agent_commands',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=False),
        sa.Column('command', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('stdout', sa.Text(), nullable=True),
        sa.Column('stderr', sa.Text(), nullable=True),
        sa.Column('exit_code', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['node_id'], ['nodes.id']),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('agent_commands')
    op.drop_table('mtr_tasks')
    op.drop_table('iperf_tasks')
    op.drop_table('monitor_checks')
    op.drop_table('monitors')
    op.drop_table('node_status_events')
    op.drop_table('node_sys_metrics')
    op.drop_table('node_metrics')
    op.drop_table('nodes')
