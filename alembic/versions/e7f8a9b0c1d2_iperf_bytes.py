"""iperf_tasks.bytes（指定数据量 -n，与时长 -t 二选一）

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-08-15 05:25:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('iperf_tasks', sa.Column('bytes', sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column('iperf_tasks', 'bytes')
