import {it,expect} from 'vitest';
import {guides} from './guides';
it('provides in-app setting help for grouped navigation, confirmed profile writes, sessions and performance limits',()=>{
 const guide=guides.find(g=>g.id==='settings');expect(guide).toBeDefined();
 for(const text of ['我的资料','安全与会话','未验证','回读','Performance API','SMTP','笔记页内'])expect(guide!.body).toContain(text);
});
