import type {Monitor} from '../../api/servers';
const reasons:Record<NonNullable<Monitor['status_reason']>,string>={healthy:'',failure:'目标探测失败',pending:'尚未取得探测结果',source_pending:'探测节点尚未接入',source_offline:'探测节点离线',dns_error:'域名解析失败',dns_timeout:'域名解析超时',outside_scope:'目标范围受限',too_many_ips:'解析地址过多',budget_exceeded:'检测超出时限',unavailable:'探测不可用',restricted:'探测受限',stale:'过久未取得有效采样',entry_removed:'入口已停用',invalid_target:'配置无效',unsupported:'节点不支持此探测',scope_pending:'尚未取得探测结果（待节点确认目标范围）'};
export function monitorStatusLabel(m:Monitor):string{return m.status==='up'?'正常':'异常';}
export function monitorStatusReason(m:Monitor):string{return m.status==='up'?'':m.status_reason?reasons[m.status_reason]:'尚未取得探测结果';}
