"""add draft slot to documents

Revision ID: f7a1c2d3e4b5
Revises: 3e2e3c14e179
Create Date: 2026-08-09

草稿槽设计：每文档一格，覆写不追加。
- draft_content     草稿内容（手动保存时清空）
- draft_updated_at  最后一次草稿同步时间（10 分钟惰性过期）
- draft_device      哪台设备留下的
"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'f7a1c2d3e4b5'
down_revision: Union[str, Sequence[str], None] = '3e2e3c14e179'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('draft_content', sa.Text(), nullable=True))
    op.add_column('documents', sa.Column('draft_updated_at', sa.DateTime(), nullable=True))
    op.add_column('documents', sa.Column('draft_device', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'draft_device')
    op.drop_column('documents', 'draft_updated_at')
    op.drop_column('documents', 'draft_content')
