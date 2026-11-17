import raw from './api.generated.json?raw';

// Treat the generated document as data, not a 29MB TypeScript literal AST.
// Exact schema/model equality is enforced by the offline exporter acceptance.
interface ApiSnapshot {
  schema: {paths: Record<string, unknown>; components: {schemas: Record<string, unknown>}};
  operations: {method: string; path: string; endpoint?: string}[];
  websockets: {path: string; source: string; handler: string}[];
  coverage: {http_operations: number; missing: unknown[]; extra: unknown[]; websocket_declarations: number};
}
const snapshot = JSON.parse(raw) as ApiSnapshot;
export default snapshot;
