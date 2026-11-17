import {api} from './client';
export type Metric='cpu'|'memory'|'root_disk'|'network.rate'|'network.utilization'|'network.volume';
export type Direction='in'|'out'|'total'|'any';
export interface MetricCondition {
 metric:Metric; interface?:string|null; direction?:Direction|null; threshold:string;
 window?:{kind:'latest'}|{kind:'fixed';start:string;end:string;timezone:string};
 capacity?:{mode:'independent'|'shared';source?:'manual_contract';in_bps?:number|null;out_bps?:number|null;shared_bps?:number|null}|null;
}
export interface MetricPreview {value:string|null;lower:string|null;upper:string|null;quality:string;reason:string;unit:string;watermark:string|null;bad:boolean|null;normalized_condition:MetricCondition}
export interface MetricIntent {node_id:number;label:string;condition:MetricCondition;severity:'warning'|'critical';debounce:number;repeat_minutes:number;email:boolean;enabled:boolean}
export interface MetricRule extends MetricIntent {id:number;revision:number;state:string;preview:MetricPreview|null;evaluated_at:string|null}
export const listMetricRules=()=>api<MetricRule[]>('/alerts/v2/rules');
export const previewMetric=(node_id:number,condition:MetricCondition,signal?:AbortSignal)=>api<MetricPreview>('/alerts/v2/preview',{method:'POST',body:JSON.stringify({node_id,condition}),signal});
export const saveMetric=(data:MetricIntent,id?:number,revision?:number)=>api<{id:number;revision:number}>(id?`/alerts/v2/rules/${id}`:'/alerts/v2/rules',{method:id?'PUT':'POST',body:JSON.stringify({...data,...(id?{revision}:{})})});
export const METRICS:Record<Metric,string>={cpu:'CPU 使用率',memory:'内存使用率',root_disk:'根文件系统使用率','network.rate':'带宽速率','network.utilization':'配置线路带宽利用率','network.volume':'固定日期累计流量'};
export const DIRECTIONS:Record<Direction,string>={in:'入站（接收）',out:'出站（发送）',total:'收发合计',any:'任一方向（取较高）'};
export const REASONS:Record<string,string>={evaluation_lag:'本次评估预算已用完，等待下一次数据到达继续',history_missing:'所选范围没有可用历史',legacy_interval:'旧采样缺少真实间隔，不能计算精确速率',invalid_interval:'采样间隔或计数质量无效',stale:'采样已过期，不能判定恢复',clock_skew:'采样时钟异常',scheduled:'等待开始日期',metric_missing:'该项指标尚无有效采样',boundary_or_gap:'边界或历史覆盖不完整，仅显示已确认下界',target_missing:'节点已移除',interface_missing:'接口已消失，请检查计量口',query_budget:'查询超过输入预算',query_unavailable:'查询超时或暂不可用',overlapping_intervals:'采样区间重叠，无法安全累计'};
