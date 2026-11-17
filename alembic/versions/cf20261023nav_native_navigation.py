"""Native navigation owner aggregate and bounded assets (no data migration)."""
from alembic import op
import sqlalchemy as sa
revision = 'cf20261023nav'
down_revision = 'ce20261021'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('nav_states',
        sa.Column('owner_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('data',sa.JSON(),nullable=False),
        sa.Column('mutation_id',sa.String(36),nullable=False),
        sa.Column('mutation_hash',sa.String(64),nullable=False))
    op.create_table('nav_assets',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('owner_id',sa.Uuid(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('name',sa.String(120),nullable=False),
        sa.Column('mime',sa.String(40),nullable=False),
        sa.Column('size',sa.Integer(),nullable=False),
        sa.Column('content',sa.LargeBinary(),nullable=False))
    op.create_index('ix_nav_assets_owner_id','nav_assets',['owner_id'])

def downgrade():
    op.drop_index('ix_nav_assets_owner_id',table_name='nav_assets')
    op.drop_table('nav_assets')
    op.drop_table('nav_states')
