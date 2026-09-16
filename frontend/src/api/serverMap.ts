import { api } from './client';

export interface MapNode {
  id: number;
  name: string;
  status: string;
  latitude: number | null;
  longitude: number | null;
  location_label: string | null;
  location_source: 'manual' | 'nat' | 'unknown';
  location_provider?: 'ip2location' | null;
  location_reason: string | null;
  location_observed_at: string | null;
  public_ip: string | null;
  wireguard_status: string | null;
}
export type MapLinkState = 'recent' | 'stale' | 'never' | 'unknown';
export type MapLinkHealth = 'ok' | 'degraded' | 'failed' | 'unknown';
export interface MapLinkObservation {
  source: number; target: number | null; interface: string;
  health?: MapLinkHealth;
  probe: { checked_at: string; status: MapLinkHealth; sent: number; received: number; loss_pct: number | null; rtt_ms: number | null; target: string; reason: string | null } | null;
}
export interface MapLink {
  id: string;
  source: number;
  target: number | null;
  source_interface: string;
  target_interface: string | null;
  state: MapLinkState;
  health?: MapLinkHealth;
  health_checked_at?: string | null;
  health_reason?: string | null;
  observations?: MapLinkObservation[];
  latest_handshake_at: number | null;
  rx_bytes: number | null;
  tx_bytes: number | null;
  peer_label: string;
  reason: string | null;
}
export interface MapTopology {
  generated_at: string;
  nodes: MapNode[];
  links: MapLink[];
  stats: { located: number; unknown: number; links: number };
}
export interface MapLocationInput {
  latitude: number | null;
  longitude: number | null;
  label: string | null;
}
export const getMapTopology = (signal?: AbortSignal) => api<MapTopology>('/nodes/map-topology', { signal });
export const updateMapLocation = (id: number, location: MapLocationInput) =>
  api<unknown>(`/nodes/${id}/map-location`, { method: 'PATCH', body: JSON.stringify(location) });
