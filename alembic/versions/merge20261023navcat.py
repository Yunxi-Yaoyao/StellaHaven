"""Join navigation category follow-up with the file/navigation schema merge.

No additional DDL, permissions, jobs, or production data migration.
"""
revision = 'merge20261023navcat'
down_revision = ('merge20261023nfnav', 'd020261023navcat')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
