"""nodes 网络标记字段：net_type（内网/公网）+ public_ip + ip_version + region + source

Revision ID: b3c4d5e6f7a8
Revises: e7f8a9b0c1d2
Create Date: 2026-08-15 17:15:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 内网/公网标记（默认 internal，已有行安全回填）
    op.add_column('nodes', sa.Column('net_type', sa.String(16), nullable=False, server_default='internal'))
    op.add_column('nodes', sa.Column('public_ip', sa.String(64), nullable=True))
    op.add_column('nodes', sa.Column('public_ip_source', sa.String(16), nullable=True))  # auto / manual
    op.add_column('nodes', sa.Column('ip_version', sa.String(8), nullable=True))         # IPv4 / IPv6
    op.add_column('nodes', sa.Column('region', sa.String(64), nullable=True))            # 地区（中文）


def downgrade() -> None:
    op.drop_column('nodes', 'region')
    op.drop_column('nodes', 'ip_version')
    op.drop_column('nodes', 'public_ip_source')
    op.drop_column('nodes', 'public_ip')
    op.drop_column('nodes', 'net_type')
