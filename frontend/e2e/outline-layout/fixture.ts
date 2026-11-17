// Isolated real components; synthetic account and service data, no live API.
import {createApp, h, ref} from 'vue';
import {createRouter, createWebHistory} from 'vue-router';
import SettingsNavigation from '../../src/modules/settings/SettingsNavigation.vue';
import ProfileSettings from '../../src/modules/settings/ProfileSettings.vue';
import ServiceSettings from '../../src/modules/settings/ServiceSettings.vue';
import SecuritySettings from '../../src/modules/settings/SecuritySettings.vue';
import ServersSideBar from '../../src/modules/servers/ServersSideBar.vue';
import '../../src/style.css';
import '../../src/modules/settings/settings-experience.css';
const profile={id:'fixture-owner',display_name:'云曦',username:'yunxi',email:'long-address-for-layout-check@example.test',email_verified:false,avatar_url:'/avatar.png'};
const router=createRouter({history:createWebHistory(),routes:[{path:'/:pathMatch(.*)*',component:{render:()=>null}}]});
const section=ref(new URLSearchParams(location.search).get('section')||'profile');
const request:typeof fetch=async(path,init)=>{
 if(String(path)==='/auth/email-service')return new Response(JSON.stringify({ready:false}));
 if(String(path)==='/auth/me'&&init?.method==='PATCH'){await new Promise<void>(resolve=>(window as any).__layoutReleaseName=resolve);return new Response(JSON.stringify({detail:'名称未能保存。请检查网络连接后重试；当前输入已保留，不会覆盖更新的草稿。'}),{status:400});}
 throw Error('Unrecognized profile fixture request '+path);
};
const scene=new URLSearchParams(location.search).get('scene');
const controls=()=>h('div',{class:'control-specimens'},[
 h('h1','共用控件状态'),h('div',{class:'specimen-row'},[
 h('button',{class:'st-button is-primary'},'应用设置'),h('button',{class:'st-button'},'取消'),h('button',{class:'st-button is-ghost'},'稍后再说'),h('button',{class:'st-button is-danger'},'删除示例'),h('button',{class:'st-button is-icon','aria-label':'图标动作'},'×'),
 h('button',{class:'st-button is-primary',disabled:true},'不可用'),h('button',{class:'st-button is-primary','aria-busy':true,disabled:true},[h('span',{class:'st-button-label'},'应用设置')]),h('button',{class:'st-button'},'保存当前配置并继续编辑新的中文草稿'),
 h('button',{class:'st-button neutral-submit',type:'submit'},'普通提交'),
 ])]);
const app=createApp({setup(){return()=>h('main',{class:'fixture-content'},scene==='controls'?controls():scene==='servers'?[h('div',{class:'servers-fixture'},[h(ServersSideBar),h('section',{class:'server-content'},[h('h1','服务器概览'),h('p','当前节点与工具任务')])])]:h(SettingsNavigation,{section:section.value,onNavigate:(v:string)=>section.value=v},()=>section.value==='authentication'?h(SecuritySettings):section.value==='services'?h(ServiceSettings,{site:'drive'}):h(ProfileSettings,{initialProfile:profile,avatars:[],request})));}});
app.use(router);await router.isReady();app.mount('#app');
