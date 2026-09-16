

def test_snapshot_total_size_is_bounded():
    import json
    from app.services.server_map import validate_snapshot
    payload={'observed_at':'2026-09-16T00:00:00+00:00','location':{'status':'unknown','source':'unknown'},'wireguard':{'status':'ok','interfaces':[]}}
    peer={'public_key_id':'a'*64,'allowed_ips':['10.0.0.0/24']*128,'latest_handshake_at':0,'rx_bytes':0,'tx_bytes':0}
    payload['wireguard']['interfaces']=[{'name':'wg0','public_key_id':'b'*64,'peers':[dict(peer,public_key_id=f'{i:064x}') for i in range(256)]}]
    assert len(json.dumps(payload))>262144
    import pytest
    with pytest.raises(ValueError,match='snapshot'):
        validate_snapshot(payload)
