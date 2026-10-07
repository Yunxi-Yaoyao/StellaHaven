import { expect, it } from 'vitest';
import * as navigation from './navigation';
it('separates service category from builtin routing without sending services to website APIs',()=>{
 const rows=navigation.resolveNavigation({entries:[]},[]);
 for(const site of ['drive','gallery'])expect(rows.find(x=>x.id===site)).toMatchObject({kind:'service',builtin:true,to:'/'+site});
 expect(rows.find(x=>x.id==='notes')).toMatchObject({kind:'page',builtin:true});
});
it('merges stable navigation IDs without allowing a builtin route override', () => {
  expect((navigation as any).resolveNavigation).toBeTypeOf('function');
  const rows = (navigation as any).resolveNavigation({entries:[{id:'status',title:'节点',icon:'server',visible:true,route:'https://evil.test'},{id:'settings',visible:false}]}, [{id:'demo',name:'演示',icon:'globe',mode:'iframe',url:'https://demo.test',visible:true}]);
  expect(rows[0]).toMatchObject({id:'status',label:'节点',to:'/status'});
  expect(rows.find((x:any)=>x.id==='demo')).toMatchObject({to:'/apps/demo'});
  expect(rows.find((x:any)=>x.id==='settings').visible).toBe(false);
  expect((navigation as any).isNavigationActive('/status/42', '/status')).toBe(true);
  expect((navigation as any).isNavigationActive('/status-other', '/status')).toBe(false);
});
