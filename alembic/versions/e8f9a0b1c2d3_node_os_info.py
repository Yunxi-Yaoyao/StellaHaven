"""nodes 加 os_name + sys_info（OS 采集，第三批）

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nodes", sa.Column("os_name", sa.String(128), nullable=True))
    op.add_column("nodes", sa.Column("sys_info", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("nodes", "sys_info")
    op.drop_column("nodes", "os_name")
