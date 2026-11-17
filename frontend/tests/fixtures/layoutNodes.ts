import type {Node} from '../../src/api/servers';
// Explicit, token-free API contract; no production node data or credentials.
export const layoutNodes:Node[]=[1,2].map(id=>({
 id,name:id===1?'服务器布局样板':'LongUnbrokenServerNameForNarrowCardRegression0123456789',platform:'linux',host:'192.0.2.'+id,
 arch:'x86_64',agent_version:'0.6.2',last_seen_at:'2026-10-20T00:00:00Z',status:'offline',token:null,
 interfaces:null,monitored_ifaces:null,storage:null,components:null,net_type:'public',public_ip:null,
 public_ip_source:null,ip_version:null,region:null,uninstall_status:null,uninstall_error:null,
 installed:true,os_name:'Debian GNU/Linux 13',sys_info:null,created_at:'2026-10-19T00:00:00Z',
}));
