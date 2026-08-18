"""monitors.node_id NOT NULL + app_config table

Revision ID: b2c3d4e5f6a7
Revises: a9f3e5c7d1b2
Create Date: 2026-08-14 03:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a9f3e5c7d1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 去掉中心探测：node_id 必填
    op.alter_column('monitors', 'node_id', existing_type=sa.Integer(), nullable=False)
    # 全局配置表（公网地址 + 监控版本号）
    op.create_table('app_config',
        sa.Column('key', sa.String(64), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )


def downgrade() -> None:
    op.drop_table('app_config')
    op.alter_column('monitors', 'node_id', existing_type=sa.Integer(), nullable=True)
