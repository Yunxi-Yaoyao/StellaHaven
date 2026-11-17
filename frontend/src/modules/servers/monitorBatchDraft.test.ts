import {expect,test} from 'vitest';
import {batchTargets,defaultPorts,portTypes,joinMonitorTarget,splitMonitorTarget} from './monitorBatchDraft';
test('editing splits endpoints without silently dropping legacy URL path, query or fragment',()=>{
 const parts=splitMonitorTarget('https','https://example.com:8443/a%2Fb?q=1#x');
 expect(parts).toEqual({host:'example.com',port:'8443',suffix:'/a%2Fb?q=1#x',legacy:false});
 expect(joinMonitorTarget('https','new.example',parts.port,parts.suffix)).toBe('https://new.example:8443/a%2Fb?q=1#x');
 expect(splitMonitorTarget('tcp','[2001:db8::1]:443')).toEqual({host:'2001:db8::1',port:'443',suffix:'',legacy:false});
 expect(splitMonitorTarget('tcp','old-invalid-target').legacy).toBe(true);
 for(const [host,ports] of [['https://example.com','80'],['example.com/a','80'],['127.1','80'],['example.com','0'],['example.com','65536'],['example.com','80/53'],['example.com','1e2']])expect(()=>batchTargets(['tcp'],host!,ports!)).toThrow();
});
test('fixed type ordering maps actual defaults; Ping has no port; IPv6 is bracketed only in endpoint',()=>{
 const types=['https','ping','udp','http','tcp'];
 expect(portTypes(types)).toEqual(['tcp','udp','http','https']);
 expect(portTypes(types).map(t=>defaultPorts[t]).join('/')).toBe('80/53/80/443');
 expect(batchTargets(types,'2001:db8::1','80/53/80/443')).toEqual([
 {type:'ping',target:'2001:db8::1'},{type:'tcp',target:'[2001:db8::1]:80'},{type:'udp',target:'[2001:db8::1]:53'},{type:'http',target:'http://[2001:db8::1]:80'},{type:'https',target:'https://[2001:db8::1]:443'}]);
});
