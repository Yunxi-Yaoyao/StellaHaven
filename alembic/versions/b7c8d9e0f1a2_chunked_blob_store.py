"""Transactional chunked file objects (optional PG storage).

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
"""
from alembic import op
import sqlalchemy as sa
revision='b7c8d9e0f1a2'
down_revision='a6b7c8d9e0f1'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('blob_objects',sa.Column('key',sa.String(512),primary_key=True),sa.Column('size',sa.BigInteger(),nullable=False),sa.Column('sha256',sa.String(64),nullable=False),sa.Column('mime',sa.String(200),nullable=False),sa.CheckConstraint('size >= 0'))
    op.create_table('blob_chunks',sa.Column('key',sa.String(512),sa.ForeignKey('blob_objects.key',ondelete='CASCADE'),primary_key=True),sa.Column('number',sa.Integer(),primary_key=True),sa.Column('data',sa.LargeBinary(),nullable=False),sa.CheckConstraint('number >= 0'))

def downgrade():
    # Refuse silent data loss; rollback requires an explicit export/cutover plan.
    bind=op.get_bind()
    if bind.execute(sa.text('SELECT EXISTS(SELECT 1 FROM blob_objects)')).scalar():
        raise RuntimeError('Refusing to drop populated blob store; export data before rollback')
    op.drop_table('blob_chunks');op.drop_table('blob_objects')
