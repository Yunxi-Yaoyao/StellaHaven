"""Owner-scoped project attachments can survive removal of their document.

Requires coordinated writer stop. No blob key/content changes; no fake documents.
Downgrade is deliberately refused while detached objects exist.
"""
import json
from uuid import UUID
from alembic import op
import sqlalchemy as sa

revision = '62a4d9c0e871'
down_revision = '47c1d9e2ab60'
branch_labels = None
depends_on = None


def _backfill_projects(connection):
    # Metadata was server-owned before this migration. Still verify every live
    # association against real document/workspace ownership, never trust JSON
    # alone to convert an ordinary/foreign attachment into a project object.
    rows = connection.execute(sa.text("SELECT key, value FROM app_config WHERE key LIKE 'web-project:%' ORDER BY key"))
    for key, value in rows:
        try:
            root = UUID(key.removeprefix('web-project:'))
            meta = json.loads(value)
            owner = UUID(meta['owner_id'])
            pairs = [(root, UUID(meta['original_attachment']))]
            pairs.extend((UUID(doc_id), UUID(record['attachment_id']))
                         for doc_id, record in meta['files'].items() if 'attachment_id' in record)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise RuntimeError('Invalid project attachment provenance; migration requires audit') from None
        root_owner = connection.execute(sa.text('SELECT w.user_id FROM documents d JOIN workspaces w ON w.id=d.workspace_id WHERE d.id=:id'), {'id': root}).scalar()
        if root_owner != owner:
            raise RuntimeError('Invalid project owner; migration requires audit')
        for doc_id, att_id in pairs:
            row = connection.execute(sa.text('''SELECT a.doc_id, w.user_id, a.owner_id FROM attachments a
                JOIN documents d ON d.id=a.doc_id JOIN workspaces w ON w.id=d.workspace_id
                WHERE a.id=:id'''), {'id': att_id}).first()
            if row is None:
                # Project members may already have been permanently removed.
                continue
            if row[0] != doc_id or row[1] != owner or row[2] not in (None, owner):
                raise RuntimeError('Invalid project attachment owner; migration requires audit')
            connection.execute(sa.text('UPDATE attachments SET owner_id=:owner WHERE id=:id'), {'owner': owner, 'id': att_id})


def upgrade():
    op.add_column('attachments', sa.Column('owner_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('attachments_owner_id_fkey', 'attachments', 'users', ['owner_id'], ['id'])
    _backfill_projects(op.get_bind())
    op.alter_column('attachments', 'doc_id', existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint('attachment_has_custodian', 'attachments', 'doc_id IS NOT NULL OR owner_id IS NOT NULL')
    op.create_index('ix_attachments_detached_owner', 'attachments', ['owner_id', 'id'], postgresql_where=sa.text('doc_id IS NULL'))


def downgrade():
    connection = op.get_bind()
    # Check before any DDL. Rehome requires a separately approved real owner
    # document; silently deleting retained objects or inventing one is forbidden.
    if connection.execute(sa.text('SELECT EXISTS(SELECT 1 FROM attachments WHERE doc_id IS NULL)')).scalar():
        raise RuntimeError('Cannot downgrade with detached project attachments; retain this schema or restore the complete pre-upgrade backup')
    op.drop_index('ix_attachments_detached_owner', table_name='attachments')
    op.drop_constraint('attachment_has_custodian', 'attachments', type_='check')
    op.alter_column('attachments', 'doc_id', existing_type=sa.Uuid(), nullable=False)
    op.drop_constraint('attachments_owner_id_fkey', 'attachments', type_='foreignkey')
    op.drop_column('attachments', 'owner_id')
