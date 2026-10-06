"""Cross-interface node/time index, prepared concurrently before adoption."""
from alembic import op
import sqlalchemy as sa
revision = 'c0d1e2f3a4b5'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None

def upgrade():
    # env.py deliberately owns ONE transaction and an advisory xact lock.
    # autocommit_block() would release that lock. On a populated installation,
    # prepare CONCURRENTLY in a separate session under the same session lock,
    # then this transactional revision validates/adopts it without blocking writes.
    db = op.get_bind()
    row = db.execute(sa.text("""
        SELECT i.indisvalid, i.indisready, i.indisunique, am.amname AS method,
               i.indpred, i.indexprs,
               ARRAY(SELECT a.attname::text FROM unnest(i.indkey) WITH ORDINALITY k(attnum, ord)
                     JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
                     ORDER BY k.ord) AS columns
        FROM pg_index i JOIN pg_class idx ON idx.oid=i.indexrelid
        JOIN pg_am am ON am.oid=idx.relam
        WHERE i.indrelid='node_metrics'::regclass
          AND idx.relname='ix_node_metrics_node_ts'
    """)).mappings().first()
    if row:
        if not (row['indisvalid'] and row['indisready'] and not row['indisunique']
                and row['method'] == 'btree' and row['columns'] == ['node_id', 'ts']
                and row['indpred'] is None and row['indexprs'] is None):
            raise RuntimeError('Monitoring index definition invalid; prepare valid CONCURRENTLY index before migration')
        return
    if db.execute(sa.text('SELECT EXISTS (SELECT 1 FROM node_metrics LIMIT 1)')).scalar():
        raise RuntimeError('Prepare ix_node_metrics_node_ts with CREATE INDEX CONCURRENTLY before migration')
    # Empty/fresh installation has no traffic to block and remains atomic.
    op.create_index('ix_node_metrics_node_ts', 'node_metrics', ['node_id', 'ts'])

def downgrade():
    raise RuntimeError('Application rollback keeps monitoring indexes; no automatic downgrade')
