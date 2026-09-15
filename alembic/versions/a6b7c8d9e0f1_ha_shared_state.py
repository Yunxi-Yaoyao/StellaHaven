"""Opt-in PostgreSQL OIDC and SMTP shared state.

Revision ID: a6b7c8d9e0f1
Revises: f1e2d3a4b5c6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'a6b7c8d9e0f1'
down_revision = 'f1e2d3a4b5c6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ha_shared_state',
                    sa.Column('key', sa.String(128), primary_key=True),
                    sa.Column('payload', JSONB, nullable=False))


def downgrade():
    op.drop_table('ha_shared_state')
