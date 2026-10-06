from app.models.node import NodeMetric

def test_cross_interface_time_queries_have_node_ts_index():
    indexes = {tuple(c.name for c in i.columns): i.name for i in NodeMetric.__table__.indexes}
    assert indexes.get(('node_id', 'ts')) == 'ix_node_metrics_node_ts'
