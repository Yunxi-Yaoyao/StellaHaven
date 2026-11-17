"""Add nullable browser-session display/group metadata; no guessed backfill.

Revision ID: c1d2e3f4a5b6
Revises: c0d1e2f3a4b5
"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = 'c0d1e2f3a4b5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('auth_sessions', sa.Column('browser_id', sa.Uuid(), nullable=True))
    op.add_column('auth_sessions', sa.Column('browser_name', sa.String(), nullable=True))
    op.add_column('auth_sessions', sa.Column('os_name', sa.String(), nullable=True))
    op.add_column('auth_sessions', sa.Column('login_origin', sa.String(), nullable=True))
    op.create_index('ix_auth_sessions_browser_group', 'auth_sessions', ['user_id', 'login_origin', 'browser_id'])


def downgrade():
    op.drop_index('ix_auth_sessions_browser_group', table_name='auth_sessions')
    for name in ('login_origin', 'os_name', 'browser_name', 'browser_id'):
        op.drop_column('auth_sessions', name)
