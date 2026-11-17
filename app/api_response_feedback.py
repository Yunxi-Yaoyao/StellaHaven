"""Scoped feedback response review; schema metadata only, never runtime filters."""

def register(c):
    obj,array,nullable,optional=(c[k] for k in ('obj','array','nullable','optional'))
    S,I,B,N,DATE=(c[k] for k in ('S','I','B','N','DATE'))
    success=c['success']
    uuid={'type':'string','format':'uuid'}
    asset=obj(root=uuid,file=uuid,path=S,mime=S)
    identity=optional(obj(id=uuid,workspace_id=uuid,members=array(uuid),assets=array(asset)),'assets')
    success('web_projects','identities',array(identity),'Owner-authorized workspace ancestry index; optional image hints are not manifest validation. No content or provenance.','app/services/web_projects.py')
    incident=obj(id=I,rule_id=I,label=S,kind=S,severity=S,node_id=nullable(I),message=S,
        started_at=nullable(DATE),resolved_at=nullable(DATE),duration_seconds=nullable(I),
        status={'enum':['unresolved','resolved','incomplete']},metadata_source={'enum':['snapshot','legacy_rule']},
        start_missing=B,recovery_unconfirmed=B,evaluated_at=nullable(DATE),watermark=nullable(DATE),
        enabled=nullable(B),archived=nullable(B),observation={'enum':['recent','unknown']})
    note=obj(id=I,rule_id=nullable(I),title=S,body=S,severity=S,kind=S,link=nullable(S),read=B,ts=DATE,
        context=nullable({'$ref':'#/$defs/JsonValue'}))
    note['$defs']={'JsonValue':c['JSON_VALUE']}
    success('alerts','incident_list',obj(items=array(incident),total=I,limit=I,offset=I,
        untracked=array(obj(rule_id=I,label=S,message=S))),'Windowed original transitions before pagination; missing evidence remains incomplete.','app/services/alert_history.py')
    success('alerts','incident_detail',obj(**incident['properties'],timeline=array(obj(id=I,event=S,ts=DATE,message=S)),notifications=array(note)),
        'Original adjacent transitions and exactly attributed notifications; no guessed recovery.','app/services/alert_history.py')
    success('alerts','list_notifications',array(note),'Stored notifications including nullable context; historical JSONB remains unvalidated.','app/services/alert_history.py')
    detail = obj(**note['properties'],entities=array(obj(type={'const':'node'},id=I,label=S,available=B)))
    detail['$defs'] = note['$defs']
    success('alerts','notification_detail',detail,
        'Exact notification with existing/missing node references; historical context remains unvalidated.','app/services/alert_history.py')
    reason='Persisted notification context is an unvalidated internal JSONB slot; known current writers do not prove every historical shape.'
    return {'alerts.'+name:reason for name in ('list_notifications','notification_detail','incident_detail')}
