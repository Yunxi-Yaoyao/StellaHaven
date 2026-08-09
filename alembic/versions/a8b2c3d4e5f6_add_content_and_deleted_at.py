"""add content and deleted_at to documents

Revision ID: a8b2c3d4e5f6
Revises: f7a1c2d3e4b5
Create Date: 2026-08-09

- content:    正文进 DB（file_path 退化为逻辑路径）
- deleted_at: 回收站软删除标记（NULL=正常，有值=在回收站）
"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'a8b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f7a1c2d3e4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('content', sa.Text(), nullable=True))
    op.add_column('documents', sa.Column('deleted_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('documents', 'deleted_at')
    op.drop_column('documents', 'content')
