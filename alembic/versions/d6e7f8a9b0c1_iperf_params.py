"""iperf_tasks 补全打流参数（udp/bitrate/port/window/length/omit/zerocopy）

Revision ID: d6e7f8a9b0c1
Revises: c4d5e6f7a8b9
Create Date: 2026-08-15 05:50:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('iperf_tasks', sa.Column('udp', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('iperf_tasks', sa.Column('bitrate', sa.String(16), nullable=True))
    op.add_column('iperf_tasks', sa.Column('port', sa.Integer(), nullable=False, server_default='5201'))
    op.add_column('iperf_tasks', sa.Column('window', sa.String(16), nullable=True))
    op.add_column('iperf_tasks', sa.Column('length', sa.String(16), nullable=True))
    op.add_column('iperf_tasks', sa.Column('omit', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('iperf_tasks', sa.Column('zerocopy', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('iperf_tasks', 'zerocopy')
    op.drop_column('iperf_tasks', 'omit')
    op.drop_column('iperf_tasks', 'length')
    op.drop_column('iperf_tasks', 'window')
    op.drop_column('iperf_tasks', 'port')
    op.drop_column('iperf_tasks', 'bitrate')
    op.drop_column('iperf_tasks', 'udp')
