"""nodes.components（组件检测状态）+ iperf_tasks.progress_json（实时打流进度）+ component_tasks（组件代装任务）

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-08-15 05:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 节点组件检测状态：{"iperf3": true, "speedtest": false}，agent 心跳上报
    op.add_column('nodes', sa.Column('components', JSONB(), nullable=True))
    # 打流实时进度：[{ts, bitrate}, ...]，client agent 每秒回传一个点
    op.add_column('iperf_tasks', sa.Column('progress_json', JSONB(), nullable=True))
    # 组件代装任务：前端「安装」按钮 → agent 轮询领取执行
    op.create_table(
        'component_tasks',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('node_id', sa.Integer(), sa.ForeignKey('nodes.id'), nullable=False),
        sa.Column('component', sa.String(16), nullable=False),  # iperf3 / speedtest
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),  # pending/running/done/failed
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('component_tasks')
    op.drop_column('iperf_tasks', 'progress_json')
    op.drop_column('nodes', 'components')
