import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parse} from '@vue/compiler-sfc';
import {baseParse} from '@vue/compiler-dom';
const cases=[
 ['settings/SettingsPage.vue','网站外发邮件'],
 ['settings/SettingsPage.vue','站内通知通过侧栏铃铛查看'],
 ['settings/ClientCallbackEditor.vue','分别填写此应用'],
 ['settings/ClientCallbackEditor.vue','完整原生回调'],
 ['settings/AuthProviderSettings.vue','默认提供身份识别'],
 ['settings/NavigationSettings.vue','所有条目在一处管理'],
 ['servers/ToolsView.vue','客户端要直连服务端'],
 ['settings/PerformanceSettings.vue','背景画质仅保存'],
 ['settings/SecuritySettings.vue','日常密码用于登录'],
 ['settings/NodeMonitoringPolicySettings.vue','明确选择 Stella 的默认探测源'],
 ['settings/NodeMonitoringPolicySettings.vue','绑定只声明节点角色'],
 ['settings/NodeMonitoringPolicySettings.vue','暂停或关闭只停止'],
 ['settings/AuthProviderSettings.vue','在原应用官方 OIDC 设置中'],
 ['servers/AlertsView.vue','发现候选不会自动新增规则'],
 ['servers/NodeDetailView.vue','增删在总览页'],
 ['notes/NotesSettings.vue','附件引用与草稿保护'],
 ['notes/NotesSettings.vue','回收站单篇删除和清空'],
 ['notes/ProjectFiles.vue','项目内移动或重命名'],
 ['notes/WebProjectPane.vue','网页与主站隔离'],
];
for(const [file,phrase] of cases)test(`${file}: ${phrase} is contextual help`,()=>{
 const source=readFileSync(new URL('../src/modules/'+file,import.meta.url),'utf8');
 const ast=baseParse(parse(source).descriptor.template.content);let found=false;
 function visit(n,help=false){const inside=help||n.tag==='HelpHint';if(n.type===2&&n.content.includes(phrase)){found=true;assert.equal(inside,true,'ordinary explanatory text must not occupy the scene body');}for(const c of n.children||[])visit(c,inside);}
 visit(ast);assert.equal(found,true,'retain help content, do not silently delete it');
});
