"""Reviewed field shapes, with explicit blockers for unvalidated stored slots.

Only response metadata. No business imports and no runtime response filters.
"""
from copy import deepcopy


def register(c):
    obj, array, nullable, optional = (c[k] for k in ('obj','array','nullable','optional'))
    S,I,F,B,N,DATE = (c[k] for k in ('S','I','F','B','N','DATE'))
    success = c['success']
    blockers = {}
    shapes = {}
    def declare(module, names, schema, source, reason=''):
        import json
        schema=deepcopy(schema)
        if '#/$defs/JsonValue' in json.dumps(schema): schema.setdefault('$defs', {}).setdefault('JsonValue', c['JSON_VALUE'])
        success(module,names,schema,'Source-reviewed response projection. '+reason,source)
        if reason:
            for name in names.split(): blockers[module+'.'+name]=reason

    location=obj(id=I,name=S,status=S,latitude=nullable(F),longitude=nullable(F),
        location_label=nullable(S),location_source={'enum':['unknown','manual','nat']},
        location_reason=nullable(S),location_observed_at=nullable(DATE),public_ip=nullable(S),
        location_provider=nullable(S),wireguard_status={'enum':['ok','unavailable','permission_denied']})
    probe=obj(checked_at=DATE,status={'enum':['ok','degraded','failed','unknown']},sent=I,received=I,
              loss_pct=nullable(F),rtt_ms=nullable(F),target=S,reason=nullable(S))
    observation=obj(source=I,target=nullable(I),interface=S,peer_key_id=S,probe=nullable(probe),
        health=S,reason=nullable(S),latest_handshake_at=I,rx_bytes=I,tx_bytes=I)
    link=obj(id=S,source=I,target=nullable(I),source_interface=S,target_interface=nullable(S),
        state=S,latest_handshake_at=I,rx_bytes=I,tx_bytes=I,peer_label=S,reason=nullable(S),
        observations=array(observation),health=S,health_checked_at=nullable(DATE),health_reason=nullable(S))
    declare('monitor','read_map_topology',obj(generated_at=DATE,nodes=array(location),links=array(link),
        stats=obj(located=I,unknown=I,links=I,node_pairs=I,matched_tunnels=I,unmatched_peers=I)), 'app/services/server_map.py')
    declare('monitor','update_map_location',location,'app/services/server_map.py')
    declare('monitor','agent_map_targets',obj(targets=array({'anyOf':[obj(interface=S,peer_key_id=S,target=S),
        obj(interface=S,interface_key_id=S,peer_key_id=S,target=S,manual={'const':True})]})),'app/services/server_map.py')
    injection=obj(enabled=B,css=S,js=S,timing={'enum':['dom_ready','document_start']},csp_policy={'enum':['reject','controlled']})
    declare('integrations','validate_injection',obj(valid=B,errors=array(S),draft=injection),'app/services/integrations_injection.py')
    check=obj(configuration_valid=B,server_reachable=nullable(B),http_status=nullable(I),
        browser_status={'const':'unobservable'},ready={'const':False},injection_version=nullable(S),reason=S)
    declare('integrations','check',check,'app/routers/integrations.py')
    shapes.update(MapLocation=location,MapProbe=probe,InjectionDraft=injection,IntegrationCheck=check)

    def mapping(value): return {'type':'object','additionalProperties':value}
    def union(*values): return {'anyOf':list(values)}
    def partial(**fields): return optional(obj(**fields),*fields)
    config=deepcopy(c['JSON_OBJECT'])
    config['description']='User-configured interface display preferences, preserved by NodeUpdate.monitored_ifaces and update_monitored_ifaces; interface keys and JSON values are intentional extension points.'
    component=union(B,obj(installed=B,version=S))  # pre-0.6.2 boolean retained
    components=partial(iperf3=component,speedtest=component,mtr=component,
        docker=obj(installed=B,running=B,version=S),firewall=obj(ufw=optional(obj(installed=B,active=B,version=S),'version'),iptables=obj(installed=B)))
    machine=obj(kind={'enum':['physical','virtual','container','unknown']},vendor=nullable(S),model=nullable(S),
        virtualization=nullable(S),evidence=array(S),detected_at=nullable(DATE))
    physical=obj(board=obj(vendor=nullable(S),model=nullable(S)),bios=obj(vendor=nullable(S),version=nullable(S)),
        memory_modules=nullable(array(obj(slot=nullable(S),capacity_bytes=nullable(I),speed_mts=nullable(I),configured_speed_mts=nullable(I),vendor=nullable(S),part_number=nullable(S)))),
        disks=nullable(array(obj(name=nullable(S),model=nullable(S),size_bytes=nullable(I),bus=nullable(S),rotational=nullable(B)))))
    platform_inventory=obj(**physical['properties'],source=S,scope=S,state=S,sampled_at=DATE)
    memory=obj(total_bytes=nullable(I),available_bytes=nullable(I),used_bytes=nullable(I),source=nullable(S),scope=S,state=S,sampled_at=nullable(DATE),attempted_at=DATE)
    memory=optional(obj(**memory['properties'],cgroup=deepcopy(memory)),'cgroup')
    cpu=obj(**{k:nullable(S) for k in ['model','base_frequency_source','temperature_source','frequency_source']},
        **{k:nullable(F) for k in ['frequency_mhz','max_frequency_mhz','base_frequency_mhz','temperature_c']},
        physical_cores=nullable(I),logical_cores=nullable(I),sampled_at=nullable(DATE))
    gpu=optional(obj(id=S,name=S,vendor=S,kind=S,source=S,telemetry_status=S,pci_bus=nullable(S),sampled_at=nullable(DATE),
        **{k:nullable(F) for k in ['temperature_c','graphics_clock_mhz','memory_clock_mhz','utilization_pct','memory_used_mib','memory_total_mib','power_w','fan_pct']}),'sampled_at')
    hardware=optional(obj(sampled_at=nullable(DATE),sensors_sampled_at=nullable(DATE),machine=machine,
        physical_inventory=nullable(physical),platform_inventory=nullable(platform_inventory),cpu=cpu,gpus=array(gpu),
        memory=memory,sensors=array(optional(obj(name=S,kind=S,value=F,unit=S,source=S,scope=S),'scope')),
        availability=optional(obj(cpu_temperature=S,gpu_presence=S,gpu=S,gpu_query=S),'gpu_query')),'memory','platform_inventory')
    storage=optional(obj(device=S,mount=S,fstype=S,kind=S,total=I,used=nullable(I),percent=nullable(F),model=nullable(S),bus=nullable(S),
        volume_mounts=array(S),pool_mounts=array(S),usage_scope=S,sampled_at=DATE),'model','bus','volume_mounts','pool_mounts','usage_scope','sampled_at')
    sys_info=partial(**{k:nullable(S) for k in ['os_name','kernel','arch','cpu_model']},cpu_cores=nullable(I),cpu_logical_cores=nullable(I),
        load1=nullable(F),load5=nullable(F),load15=nullable(F),boot_time=nullable(F),hardware=hardware,
        storage_status=obj(state=S,sampled_at=nullable(DATE),attempted_at=nullable(DATE)))
    interfaces=mapping(partial(is_default=B,up=B,is_physical=B,docker=B,ip=nullable(S)))
    shapes.update(Hardware=hardware,SystemMemory=memory,NodeSystemInfo=sys_info,NodeStorage=storage,NodeInterfaces=interfaces,NodeComponents=components)

    err=obj(error=S)
    iptables_rule=obj(raw=S,**{k:nullable(S) for k in ['chain','target','proto','sport','dport','source','dest','in_iface','out_iface']})
    absent=obj(installed={'const':False})
    iptables=union(absent,obj(installed={'const':True},error=S),obj(installed={'const':True},raw=S,tables=mapping(obj(
        chains=array(obj(name=S,policy=nullable(S),packets=I,bytes=I)),rules=array(iptables_rule)))))
    ufw=union(absent,obj(installed={'const':True},active=B,defaults=nullable(S),logging=nullable(S),raw=S,
        rules=array(obj(num=I,to=S,action=S,v6=B,**{'from':S}))))
    # Docker's raw external fields have documented current types; no secret
    # redaction is implied (inspect env and logs may contain sensitive strings).
    net_results={
        'ip_change':union(err,optional(obj(error=S,rolled_back=B,old_ip=S,new_ip=S),'new_ip'),obj(ok=B,old_ip=S,new_ip=S,persisted=B,backend=S)),
        'firewall_scan':union(err,obj(ufw=ufw,iptables=iptables)),
        'docker_scan':union(err,absent,obj(installed={'const':True},error=S),obj(installed={'const':True},containers=array(obj(
            id=nullable(S),name=nullable(S),image=nullable(S),status=nullable(S),state=nullable(S),ports=S,created=S)))),
        'docker_ctl':union(err,obj(ok=B,action=S,container=S)),
        'docker_logs':union(err,obj(container=S,lines=S,tail=I)),
        'docker_inspect':union(err,obj(container=S,image=nullable(S),created=nullable(S),cmd=nullable(S),entrypoint=nullable(S),env=array(S),
            mounts=array(obj(source=nullable(S),target=nullable(S),mode=nullable(S),rw=nullable(B))),ports=array(obj(container=S,host=S)),
            restart_policy=nullable(S),networks=array(S),state=nullable(S))),
        'pbr_scan':union(err,obj(rules=array(union(err,obj(pref=I,mark=nullable(S),table=nullable(S),raw=S,**{'from':nullable(S)}))),
            tables=mapping(array(obj(dst=S,via=nullable(S),dev=nullable(S),scope=nullable(S),raw=S))),
            marks=array(obj(chain=nullable(S),uid=nullable(S),mark=nullable(S),raw=S))))}
    shapes['NetResults']=net_results
    hub=obj(count=I,host=S,snt=I,**{'loss%':F},**{k:nullable(F) for k in ['last','avg','best','wrst','stdev']})
    mtr_result=union(err,obj(report=obj(mtr=obj(dst=S,tos=I,psize=I,bitpattern=I,tests=I),hubs=array(hub))))
    progress=optional(obj(ts=S,bitrate=F,role=S,note=S,lost_pct=F,jitter_ms=F,retry={'const':True},attempt=I,reason=S),
        'note','lost_pct','jitter_ms','retry','attempt','reason')
    shapes.update(MtrResult=mtr_result,MtrLive=obj(hops=array(hub)),IperfProgress=progress)
    model_blockers={}
    c['MODEL_BLOCKERS']=model_blockers
    def visit(value):
        if not isinstance(value,dict): return
        props=value.get('properties',{})
        if value.get('title')=='AgentConfig': props['monitored_ifaces']=nullable(config)
        for key,child in value.items():
            if key.startswith('x-'):continue
            if isinstance(child,dict):visit(child)
            elif isinstance(child,list):
                for item in child:visit(item)
    for name,model in c['MODELS'].items():
        visit(model)

    shapes['NodePublic']=deepcopy(c['MODELS']['NodeRead excluding token'])

    # Actual scoped projections validate stored values and discard unknown keys.
    J={'$ref':'#/$defs/JsonValue'}
    for names, model in [('modules','list[PublicModule]'), ('module patch create','PublicModule'),
                         ('targets','list[PublicTarget]'), ('create_target','PublicTarget'),
                         ('navigation save_navigation','PublicNavigation'),
                         ('apply_injection rollback_injection','PublicInjectionVersions')]:
        declare('integrations',names,c['MODELS'][model],'app/public_website.py')
    declare('website_settings','create update',c['MODELS']['PublicWebsiteResult'],'app/public_website.py')
    declare('auth','avatar_history',array(S),'app/services/small_public_outputs.py')
    declare('admin_email','get_config',c['MODELS']['PublicSMTPConfig'],'app/services/small_public_outputs.py')
    declare('operations_status','change_audit',c['MODELS']['PublicChangeAudit'],'app/services/small_public_outputs.py')
    declare('monitor','change_ip',c['MODELS']['NetTaskRead'],'app/schemas/public_task.py')
    declare('task','poll_tasks',c['MODELS']['AgentTasksRead'],'app/schemas/public_task.py')
    declare('oidc','jwks',c['MODELS']['PublicJWKS'],'app/services/small_public_outputs.py')
    point=obj(value=nullable(F),timestamp=dict(J,description='Raw Prometheus response timestamp, passed through by _point; not normalized by adapter.'),
        sampleTimestamp=dict(J,description='Raw scrape timestamp from external Prometheus, or null.'),timestampKind={'enum':['sample','evaluation']},source={'const':'prometheus'})
    snapshot=obj(source={'const':'prometheus'},job=S,instance=S,evaluatedAt=F,freshness={'enum':['no_sample','stale','up','down']},
        scrapeUp=point,cpuPct=point,memoryPct=point,
        filesystems=array(obj(mountpoint=dict(J,description='External Prometheus label'),device=dict(J,description='External Prometheus label'),fstype=dict(J,description='External Prometheus label'),sizeBytes=point,freeBytes=point,usedPct=point)),
        networks=array(obj(device=dict(J,description='External Prometheus device label'),**{k:point for k in ['receiveBytes','transmitBytes','receiveBytesPerSecond','transmitBytesPerSecond']})))
    comparison=obj(nodeId=I,comparedAt=F,legacy=obj(source={'const':'legacy'},latestSys=nullable(obj(timestamp=F,cpuPct=nullable(F),memoryPct=nullable(F),diskPct=nullable(F))),sysSampleSpacingSeconds=nullable(F),expectedSysIntervalSeconds={'const':60},trafficIntervalSeconds={'const':5}),
        prometheus=obj(snapshot=snapshot,sampleSpacing=obj(source={'const':'prometheus'},sampleTimestamps=array(F),spacingSeconds=array(F))),
        equivalence=obj(status={'const':'not_equivalent'},reason=S,requiredSpacingSeconds={'const':5},cadenceMatches=B,note=S))
    declare('metrics_source','compare_metrics',comparison,'app/services/prometheus_metrics.py')
    declare('alerts','metric_rules',c['MODELS']['list[PublicMetricRule]'],'app/public_alert_metrics.py')
    return blockers, shapes
