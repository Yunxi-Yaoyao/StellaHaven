"""iperf_tasks：看门狗 started_at + 结果摘要落列（avg/peak Mbps、丢包、抖动）

Revision ID: d7e8f9a0b1c2
Revises: c5d6e7f8a9b0
Create Date: 2026-08-19 15:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('iperf_tasks', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('iperf_tasks', sa.Column('avg_mbps', sa.Float(), nullable=True))
    op.add_column('iperf_tasks', sa.Column('peak_mbps', sa.Float(), nullable=True))
    op.add_column('iperf_tasks', sa.Column('lost_pct', sa.Float(), nullable=True))
    op.add_column('iperf_tasks', sa.Column('jitter_ms', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('iperf_tasks', 'jitter_ms')
    op.drop_column('iperf_tasks', 'lost_pct')
    op.drop_column('iperf_tasks', 'peak_mbps')
    op.drop_column('iperf_tasks', 'avg_mbps')
    op.drop_column('iperf_tasks', 'started_at')
