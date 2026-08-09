"""add last_viewed_at to documents

Revision ID: d1e2f3a4b5c6
Revises: c9d3e4f5a6b7
Create Date: 2026-08-10

最近查看：打开页面时戳一下，侧边栏「最近查看」区块按它倒序。
与 updated_at（正文保存时间）互不干扰。
"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c9d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('last_viewed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'last_viewed_at')
