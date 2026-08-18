"""add user_id to tags + per-user unique + clean orphan tags

Revision ID: 7c4d9a1e2b3f
Revises: c8784f3ca65c
Create Date: 2026-08-13 23:35:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c4d9a1e2b3f'
down_revision: Union[str, Sequence[str], None] = 'c8784f3ca65c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 加 user_id 列（先可空，方便回填）
    op.add_column('tags', sa.Column('user_id', sa.Uuid(), nullable=True))

    # 2. 删孤儿标签（没有任何文档引用的残留标签）
    op.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM doc_tags)")

    # 3. 回填剩余标签的归属（经 doc_tags → documents → workspaces 推导 owner）
    op.execute("""
        UPDATE tags t SET user_id = w.user_id
        FROM doc_tags dt
        JOIN documents d ON d.id = dt.doc_id
        JOIN workspaces w ON w.id = d.workspace_id
        WHERE dt.tag_id = t.id
    """)

    # 4. 理论上不该再有 NULL；若有则是异常数据，一并清掉
    op.execute("DELETE FROM tags WHERE user_id IS NULL")

    # 5. 旧的全局唯一 name → 换成 (user_id, name) 联合唯一
    op.drop_constraint('tags_name_key', 'tags', type_='unique')
    op.create_unique_constraint('uq_tags_user_name', 'tags', ['user_id', 'name'])

    # 6. 设非空 + 外键
    op.alter_column('tags', 'user_id', nullable=False)
    op.create_foreign_key('fk_tags_user_id', 'tags', 'users', ['user_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_tags_user_id', 'tags', type_='foreignkey')
    op.drop_constraint('uq_tags_user_name', 'tags', type_='unique')
    op.drop_column('tags', 'user_id')
    op.create_unique_constraint('tags_name_key', 'tags', ['name'])
