import {expect,it} from 'vitest';
import {pages,apiCoverage} from './catalog';
import api from './apiSnapshot';
it('covers the exact HTTP inventory and keeps WebSocket separately documented',()=>{
 const actual=pages.filter(p=>p.section==='api'&&/^(get|post|patch|put|head|options|delete|trace):/.test(p.id)).map(p=>p.title).sort();
 expect(actual).toEqual(api.operations.map(o=>`${o.method} ${o.path}`).sort());
 expect(actual.length).toBe(apiCoverage.http_operations);expect(apiCoverage.missing).toEqual([]);expect(apiCoverage.extra).toEqual([]);
 expect(pages.find(p=>p.id==='websockets')!.body).toContain('/ws/list/{workspace_id}');
});
it('makes every referenced schema model available in the built reader',()=>{
 const models=Object.keys(api.schema.components.schemas).sort();
 expect(pages.filter(p=>p.id.startsWith('model:')).map(p=>p.id.slice(6)).sort()).toEqual(models);
});
it('shows constrained parameters and labelled response examples without execution claims',()=>{
 const read=pages.find(p=>p.id==='get:/documents/')!;
 expect(read.body).toContain('完整参数定义');
 const login=pages.find(p=>p.id==='post:/auth/login')!;
 expect(login.body).toContain('响应字段示意');
 expect(login.body).toContain('<REPLACE_ME>');
 expect(login.body).not.toContain('Bearer eyJ');
});
it('explains actual menus, same-side entry limits and practical website/OIDC setup',()=>{
 const guide=(id:string)=>pages.find(p=>p.id===id)!.body;
 expect(guide('start')).toContain('侧栏底部');
 expect(guide('websites')).toContain('编辑网站与删除入口');
 expect(guide('websites')).toContain('保存 CSS / JavaScript');
 expect(guide('services')).toContain('网盘入口与相册入口');
 expect(guide('services')).toContain('/.well-known/openid-configuration');
 expect(guide('services')).toContain('openid profile email');
 expect(guide('services')).toContain('https://stella.p.xiya.live');
 expect(guide('services')).toContain('不代表此刻部署已验证');
 expect(guide('web-projects')).toContain('独立 pages 入口');
});
