"""Persist one-shot MTR fan-out identity, retaining legacy task IDs/history.

Revision ID: 83b5f190a621
Revises: 62a4d9c0e871
"""
from alembic import op
import sqlalchemy as sa
revision = '83b5f190a621'
down_revision = '62a4d9c0e871'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('mtr_tasks', sa.Column('job_id', sa.String(32), nullable=True))
    op.create_index('ix_mtr_tasks_job_id', 'mtr_tasks', ['job_id'])


def downgrade():
    op.drop_index('ix_mtr_tasks_job_id', table_name='mtr_tasks')
    op.drop_column('mtr_tasks', 'job_id')
