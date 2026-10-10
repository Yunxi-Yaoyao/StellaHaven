import type { NodeDetail } from '../../api/servers';

// Physical detection is Linux-specific. Windows/cloud interfaces remain selectable.
export function overviewInterfaces(detail: NodeDetail | undefined): string[] {
  return Object.entries(detail?.interfaces || {})
    .filter(([name, meta]) => meta.up && !meta.docker && !/^(?:lo(?:\d+)?$|loopback|docker|cni|veth|bridge|br[-\d])/i.test(name))
    .map(([name]) => name);
}

export function overviewDefaultInterface(detail: NodeDetail | undefined): string {
  const available = overviewInterfaces(detail);
  const configured = Object.keys(detail?.monitored_ifaces || {}).filter(name => available.includes(name));
  if (configured.length) return configured[0]!;
  const score = (name: string) => {
    const meta = detail!.interfaces![name]!;
    const latest = detail!.latest_metrics?.find(point => point.iface === name);
    return (meta.is_default ? 1000 : 0) + (meta.is_physical ? 100 : 0)
      + (latest && latest.rx_delta + latest.tx_delta > 0 ? 30 : latest ? 20 : 0)
      + (/^(?:wlan|wi-?fi|ethernet|eth\d|en[opsx])/i.test(name) ? 10 : 0);
  };
  return available.sort((a, b) => score(b) - score(a))[0] || '';
}
