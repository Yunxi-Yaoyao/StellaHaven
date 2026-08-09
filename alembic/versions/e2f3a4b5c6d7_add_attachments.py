"""add attachments table

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-08-10

附件表：图片粘贴上传。文件本体落磁盘（data/attachments/），DB 记元信息。
"""
from typing import Union, Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'attachments',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('doc_id', sa.Uuid(), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('mime', sa.String(), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('attachments')
