import type { MonitorCheckPoint } from '../../api/servers';
export function summarizeMonitorPoints(points: readonly MonitorCheckPoint[]) {
  let total=0, success=0, latencySum=0, latencyCount=0, lossSum=0, lossCount=0;
  for (const p of points) {
    const count=p.sample_count ?? 1;
    total+=count; success+=p.success_count ?? (p.success?count:0);
    const lc=p.latency_count ?? (p.success && p.latency_ms!=null?count:0);
    if(p.latency_ms!=null) { latencySum+=p.latency_ms*lc; latencyCount+=lc; }
    const pc=p.loss_count ?? (p.loss_pct!=null?count:0);
    if(p.loss_pct!=null) { lossSum+=p.loss_pct*pc; lossCount+=pc; }
  }
  return {total,avail:total?success/total*100:0,avgLat:latencyCount?latencySum/latencyCount:null,
    loss:lossCount?lossSum/lossCount:total?(total-success)/total*100:0};
}
