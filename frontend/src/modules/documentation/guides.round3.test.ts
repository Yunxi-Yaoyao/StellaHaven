import {expect,it} from 'vitest';
import {guides} from './guides';
const body=(id:string)=>guides.find(g=>g.id===id)!.body;
it('documents editable nickname and username without changing UUID or OIDC subject',()=>{
 const text=body('settings');expect(text).toContain('昵称');expect(text).toContain('用户名可编辑');expect(text).toContain('UUID');expect(text).toContain('preferred_username');expect(text).toContain('旧用户名仍可能通过昵称登录');expect(text).toContain('保存与取消');expect(text).not.toMatch(/用户名在此只读|暂不验证并保存|网站默认切页卸载|明确启用保留现场/);
});
it('explains upstream paths, generated entries and direct alternatives as different objects',()=>{
 const text=body('websites');expect(text).toContain('网站地址可包含路径、查询与锚点');expect(text).toContain('系统自动选择已登记的隔离入口');expect(text).not.toMatch(/更多连接选项|其他访问地址（可选）|相邻显示/);expect(text).toContain('自定义请求头');expect(text).toContain('Authorization');expect(text).toContain('始终使用默认入口');expect(text).toContain('不是任意多入口');expect(text).toContain('统一初始路径');expect(text).toContain('最多 3 个页面');expect(text).not.toContain('内网地址（可选）');
});
it('describes the candidate monitoring mechanism without claiming preview samples or a fleet rollout',()=>{
 const text=body('servers');expect(text).not.toContain('新机制尚未实现');expect(text).toContain('候选版本');expect(text).toContain('每 60 秒');expect(text).toContain('默认入口');expect(text).toContain('其他入口');expect(text).toContain('上一笔已完成');expect(text).toContain('汇报请求耗时');expect(text).toContain('未知');expect(text).toContain('不代表当前预览已采集到真实样本');expect(text).toContain('不自动切换');
});
