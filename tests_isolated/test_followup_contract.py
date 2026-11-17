"""WG/manual-result integration contracts; offline and no live state."""
from test_api_response_contract import response_module, validate_payload


def test_manual_wg_rule_and_agent_targets_closed_shapes():
    from datetime import datetime, timezone
    from jsonschema import ValidationError
    import pytest
    row=dict(id=1,kind='wg_link',target='manual:fixture',label='fixture',link='/status',severity='warning',debounce=2,repeat_minutes=30,email=False,enabled=True,created_at=datetime.now(timezone.utc).isoformat(),state='ok',last_change_at=None,message=None,
             wg_manual=dict(node_id=1,interface='wg0',target='10.0.0.2',interface_key_id='a'*64,peer_key_id='b'*64),wg_observation=dict(health='unknown',reason='agent_upgrade_required',checked_at=None))
    validate_payload('GET','/alerts/rules',[row])
    row['wg_observation']['health']='success'
    with pytest.raises(ValidationError):validate_payload('GET','/alerts/rules',[row])
    # Normal agents retain their old shape; manual targets have explicit identity.
    data=[dict(interface='wg0',peer_key_id='b'*64,target='10.0.0.2'),dict(interface='wg0',interface_key_id='a'*64,peer_key_id='b'*64,target='10.0.0.2',manual=True)]
    from test_api_response_contract import body_namespace
    from types import SimpleNamespace
    route=body_namespace('app/routers/monitor.py',['agent_map_targets'],server_map=SimpleNamespace(get_probe_targets=lambda db,token:data))['agent_map_targets']
    validate_payload('GET','/agent/map-targets',route('fixture',None))
    data[1]['manual']=False
    with pytest.raises(ValidationError):validate_payload('GET','/agent/map-targets',dict(targets=data))


def test_followup_source_chains_include_binding_and_durable_handoff():
    c=response_module()
    for key in [('POST','/alerts/rules'),('GET','/alerts/rules'),('GET','/agent/map-targets')]:
        files={c.SOURCE_EVIDENCE[s]['file'] for s in c.DECLARATIONS[key]['sources']}
        assert {'app/services/wg_manual.py','app/services/server_map.py'} <= files,key
    for key in [('POST','/operations/backups'),('GET','/operations/backups'),('POST','/agent/mtr-tasks/{task_id}/result')]:
        files={c.SOURCE_EVIDENCE[s]['file'] for s in c.DECLARATIONS[key]['sources']}
        assert {'app/services/result_notifications.py','app/services/notifications.py'} <= files,key
    incomplete={key for key,value in c.DECLARATIONS.items() if value['status']=='incomplete'}
    assert incomplete=={('GET','/notifications'),('GET','/notifications/{notification_id}'),('GET','/alerts/incidents/{incident_id}')}
