import {api} from './client';
export interface NodeMonitoringPolicyWrite {revision:number;enabled:boolean;source_node_id:number|null;host_node_id:number|null;interval:number}
export interface ManagedNodeMonitor {target_node_id:number;source_node_id:number;monitor_id:number;suppressed:boolean;exists:boolean;paused:boolean}
export interface NodeMonitoringPolicy extends NodeMonitoringPolicyWrite {source_ready:boolean;source_scope:string[]|null;source_test_targets?:{type:'ping'|'tcp';target:string;description:string}[];managed:ManagedNodeMonitor[];pending:{node_id:number;reason:string}[]}
export const getNodeMonitoringPolicy=()=>api<NodeMonitoringPolicy>('/nodes/monitoring-policy');
export const putNodeMonitoringPolicy=(data:NodeMonitoringPolicyWrite)=>api<NodeMonitoringPolicy>('/nodes/monitoring-policy',{method:'PUT',body:JSON.stringify(data)});
export const pauseNodeMonitoring=(id:number,suppressed:boolean)=>api<NodeMonitoringPolicy>(`/nodes/monitoring-policy/targets/${id}`,{method:'PATCH',body:JSON.stringify({suppressed})});

// v1 policy APIs remain legacy compatibility only, not the automatic mechanism.
export interface ManagementEntry {entry_id:'public'|'private';origin:string;hostname:string;version:string}
export interface ReportTransaction {entry_id:'public'|'private'|null;origin:string;duration_ms:number;status:'ok'|'error';http_status:number|null;error:'http'|'timeout'|'transport'|'invalid_response'|null;sampled_at:string}
export interface EntryIPSample {ip:string;family:4|6;status:'up'|'down'|'unavailable';latency_ms:number|null;loss_pct:number|null}
export interface EntrySample {entry_id:'public'|'private';version:string;hostname:string;sampled_at:string;status:'complete'|'dns_error'|'dns_timeout'|'outside_scope'|'too_many_ips'|'budget_exceeded'|'unavailable';results:EntryIPSample[]}
export interface ControlChannel {report:ReportTransaction|null;icmp:EntrySample[]}
export const getEntryMonitoring=()=>api<ManagementEntry[]>('/nodes/entry-monitoring');
