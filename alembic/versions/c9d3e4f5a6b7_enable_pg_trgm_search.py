"""enable pg_trgm and add search indexes on documents

Revision ID: c9d3e4f5a6b7
Revises: a8b2c3d4e5f6
Create Date: 2026-08-09

全文搜索选型：pg_trgm（三字元）而非 tsvector——
PG 原生 tsvector 按空格/标点分词，中文整句连写会被当成一个词，搜不到。
pg_trgm 把文本切成三字元切片，中文子串可命中，GIN 索引可加速 ILIKE '%kw%'。
"""
from typing import Union, Sequence

from alembic import op


revision: str = 'c9d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = 'a8b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    op.execute('CREATE INDEX idx_documents_title_trgm ON documents USING gin (title gin_trgm_ops)')
    op.execute('CREATE INDEX idx_documents_content_trgm ON documents USING gin (content gin_trgm_ops)')


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS idx_documents_content_trgm')
    op.execute('DROP INDEX IF EXISTS idx_documents_title_trgm')
