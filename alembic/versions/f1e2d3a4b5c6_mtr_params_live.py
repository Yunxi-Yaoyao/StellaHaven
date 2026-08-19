"""mtr_tasks 加 params_json（探测参数）+ live_json（实时逐跳快照，槽位覆写）

Revision ID: f1e2d3a4b5c6
Revises: 9f1e2d3c4b5a
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f1e2d3a4b5c6"
down_revision = "9f1e2d3c4b5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mtr_tasks", sa.Column("params_json", postgresql.JSONB(), nullable=True))
    op.add_column("mtr_tasks", sa.Column("live_json", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("mtr_tasks", "live_json")
    op.drop_column("mtr_tasks", "params_json")
