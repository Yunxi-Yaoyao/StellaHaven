"""iperf_tasks 加 speedtest_server（speedtest 测速服务器选择，第三批）

Revision ID: f0a1b2c3d4e5
Revises: e8f9a0b1c2d3
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa

revision = "f0a1b2c3d4e5"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("iperf_tasks", sa.Column("speedtest_server", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("iperf_tasks", "speedtest_server")
