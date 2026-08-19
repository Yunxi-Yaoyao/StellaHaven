"""mtr_tasks 挂监控项：monitor_id + trigger

Revision ID: 9f1e2d3c4b5a
Revises: f0a1b2c3d4e5
Create Date: 2026-08-19

MTR 历史挂到监控项上：monitor_id 非空=监控项的 MTR 历史（定时/失败/浮窗手动），
为空=工具页一次性 MTR（存量行默认 manual）。
"""
from alembic import op
import sqlalchemy as sa

revision = "9f1e2d3c4b5a"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mtr_tasks", sa.Column("monitor_id", sa.Integer(), sa.ForeignKey("monitors.id"), nullable=True))
    op.add_column("mtr_tasks", sa.Column("trigger", sa.String(16), nullable=False, server_default="manual"))


def downgrade() -> None:
    op.drop_column("mtr_tasks", "trigger")
    op.drop_column("mtr_tasks", "monitor_id")
