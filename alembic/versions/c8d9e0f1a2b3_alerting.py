"""Alert rules, per-rule state slots, event history and in-app notifications.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
"""
from alembic import op
import sqlalchemy as sa

revision = 'c8d9e0f1a2b3'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'alert_rules',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('target', sa.String(128), nullable=False),
        sa.Column('label', sa.String(128), nullable=False, server_default=''),
        sa.Column('link', sa.String(128), nullable=False, server_default='/status'),
        sa.Column('severity', sa.String(16), nullable=False, server_default='warning'),
        sa.Column('debounce', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('repeat_minutes', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('email', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('kind', 'target', name='uq_alert_rule'),
    )
    op.create_table(
        'alert_states',
        sa.Column('rule_id', sa.Integer(), sa.ForeignKey('alert_rules.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('state', sa.String(8), nullable=False, server_default='ok'),
        sa.Column('consecutive', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_change_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_notified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('message', sa.String(256), nullable=True),
    )
    op.create_table(
        'alert_events',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('rule_id', sa.Integer(), sa.ForeignKey('alert_rules.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event', sa.String(8), nullable=False),
        sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('message', sa.String(256), nullable=False, server_default=''),
    )
    op.create_table(
        'notifications',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('rule_id', sa.Integer(), sa.ForeignKey('alert_rules.id', ondelete='SET NULL'), nullable=True),
        sa.Column('title', sa.String(120), nullable=False),
        sa.Column('body', sa.String(500), nullable=False, server_default=''),
        sa.Column('severity', sa.String(16), nullable=False, server_default='warning'),
        sa.Column('kind', sa.String(24), nullable=False, server_default='alert'),
        sa.Column('link', sa.String(128), nullable=True),
        sa.Column('read', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('ts', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('notifications')
    op.drop_table('alert_events')
    op.drop_table('alert_states')
    op.drop_table('alert_rules')
