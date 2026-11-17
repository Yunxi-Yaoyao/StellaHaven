"""Dedicated bounded file journal; no OS root grants are created."""
from alembic import op
import sqlalchemy as sa

revision = 'nf20261023'
down_revision = 'ce20261021'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('node_file_agents', sa.Column('node_id', sa.Integer(), primary_key=True), sa.Column('seen', sa.Float(), nullable=False), sa.Column('roots', sa.JSON(), nullable=False))
    op.create_table('node_file_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('owner', sa.String(36), nullable=False),
        sa.Column('session', sa.String(36), nullable=False),
        sa.Column('request_key', sa.String(36), nullable=False),
        sa.Column('node_id', sa.Integer(), nullable=False),
        sa.Column('root', sa.String(64), nullable=False),
        sa.Column('policy', sa.String(64), nullable=False),
        sa.Column('request', sa.JSON(), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('expires', sa.Float(), nullable=False),
        sa.Column('lease', sa.String(64)),
        sa.Column('result', sa.JSON()),
        sa.Column('error', sa.String(64)),
        sa.Column('bytes_received', sa.Integer(), nullable=False),
        sa.UniqueConstraint('owner', 'session', 'request_key'))
    for column in ('owner', 'node_id', 'state'):
        op.create_index('ix_node_file_jobs_' + column, 'node_file_jobs', [column])


def downgrade():
    op.drop_table('node_file_jobs')
    op.drop_table('node_file_agents')
