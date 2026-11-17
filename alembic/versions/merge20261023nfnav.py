"""Join independently reviewed navigation and node-file additive schemas.

This revision creates no extra grants, roots, file jobs, or migrated user data.
"""
revision = 'merge20261023nfnav'
down_revision = ('cf20261023nav', 'nf20261023')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
