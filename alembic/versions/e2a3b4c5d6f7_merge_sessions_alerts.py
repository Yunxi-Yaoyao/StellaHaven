"""Join independently authored browser metadata and alert metric branches.

No data/schema operations: both parent upgrades must finish before this head.
Reverting this merge does not remove either branch's data. Alert downgrade is
intentionally guarded; production rollback requires the documented forward-
compatible application rollback, not an automatic destructive schema downgrade.
"""
revision = 'e2a3b4c5d6f7'
down_revision = ('c1d2e3f4a5b6', 'd1a2b3c4d5e6')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
