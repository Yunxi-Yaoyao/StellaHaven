"""Capture future document-save events without interpreting raw clocks.

Revision ID: 47c1d9e2ab60
Revises: e2a3b4c5d6f7
"""
from alembic import op
import sqlalchemy as sa

revision = '47c1d9e2ab60'
down_revision = 'e2a3b4c5d6f7'
branch_labels = None
depends_on = None


def upgrade():
    # No default/backfill: an old wall timestamp does not identify an instant.
    op.add_column('documents', sa.Column('saved_event_at', sa.DateTime(timezone=True), nullable=True))
    # Deliberately scoped to this table and INSERT / an explicitly saved raw
    # token. Old writers are covered too: this is a NEW database-observed event,
    # never a declaration that their updated_at value uses UTC. Even equal-token
    # writes produce a new observation instead of reusing stale provenance.
    op.execute('''CREATE FUNCTION stella_document_save_event() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.saved_event_at := clock_timestamp();
            RETURN NEW;
        END;
        $$''')
    op.execute('''CREATE TRIGGER document_save_event
        BEFORE INSERT OR UPDATE OF updated_at ON documents
        FOR EACH ROW EXECUTE FUNCTION stella_document_save_event()''')


def downgrade():
    op.execute('DROP TRIGGER document_save_event ON documents')
    op.execute('DROP FUNCTION stella_document_save_event()')
    op.drop_column('documents', 'saved_event_at')
