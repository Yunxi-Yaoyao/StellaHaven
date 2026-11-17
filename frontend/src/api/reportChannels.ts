import {api} from './client';
export type ChannelMode = 'default' | 'fixed' | 'auto';
export interface ChannelEntry {entry_id:'public'|'private'; origin:string}
export interface ChannelNode {
 node_id:number;name:string;mode:ChannelMode;entry_id:ChannelEntry['entry_id']|null;revision:number;
 state:'pending'|'applied'|'failed';actual_origin:string|null;http_ms:number|null;sampled_at:string|null;
 http_origin:string|null;http_status:'ok'|'error'|null;
 error:'probe_failed'|'invalid_config'|null;online:boolean;
}
export interface ReportChannels {revision:number;default_entry_id:'public';entries:ChannelEntry[];nodes:ChannelNode[]}
export interface ChannelWrite {revision:number;node_ids:number[];mode:ChannelMode;entry_id:ChannelEntry['entry_id']|null}
export const getReportChannels=(signal?:AbortSignal)=>api<ReportChannels>('/nodes/report-channels',{signal});
export const putReportChannels=(data:ChannelWrite,signal?:AbortSignal)=>api<ReportChannels>('/nodes/report-channels',{method:'PUT',body:JSON.stringify(data),signal});
