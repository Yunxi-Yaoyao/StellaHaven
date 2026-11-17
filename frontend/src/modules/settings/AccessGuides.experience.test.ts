import {createApp,nextTick,type App} from 'vue';
import {it,expect,afterEach} from 'vitest';
let app:App|undefined;
afterEach(()=>{app?.unmount();document.body.replaceChildren();});
it('shows only selected native OIDC fields, keeps manual endpoints collapsed and never embeds a secret',async()=>{
 const Component=(await import('./OidcClientGuide.vue')).default;
 const root=document.createElement('div');document.body.append(root);app=createApp(Component,{issuer:'https://issuer.test',client:{client_id:'fixture-client',redirect_uris:['https://rp.test/auth/login','https://rp.test/user-settings'],scopes:['openid','profile','email']}});app.mount(root);await nextTick();
 expect(root.textContent).toContain('原生 OIDC 不需要注入脚本');expect(root.textContent).toContain('fixture-client');expect(root.textContent).toContain('https://rp.test/user-settings');expect(root.querySelector('details.manual-endpoints')?.hasAttribute('open')).toBe(false);expect(root.querySelector(':scope > section > dl')?.textContent).not.toContain('oauth/token');expect(root.querySelector('script')).toBeNull();expect(root.querySelector('pre')).toBeNull();expect(root.textContent).not.toContain('client_secret:');
});
it('provides only the complete current loader when it is actually needed, not a protocol excerpt',async()=>{
 const Component=(await import('./WebsiteAccessGuide.vue')).default;
 const root=document.createElement('div');document.body.append(root);app=createApp(Component,{adapter:'immich',mode:'iframe',mainOrigin:'https://actual-parent.test',id:'a'.repeat(32),customEnabled:true,delivery:'loader',authMode:'oidc'});app.component('RouterLink',{template:'<a><slot/></a>'});app.mount(root);await nextTick();
 expect(root.querySelector('pre')?.textContent).toBe('<script src="https://actual-parent.test/website-assets/'+ 'a'.repeat(32)+'.js"></script>');expect(root.querySelector('[aria-label="精确来源消息适配示例"]')).toBeNull();expect(root.textContent).toContain('不需要脚本');expect(root.textContent).toContain('Client Secret');expect(root.querySelector('details')?.open).toBe(false);
});
it('does not ask a normal OpenList connection to install or copy anything',async()=>{
 const Component=(await import('./WebsiteAccessGuide.vue')).default;
 const root=document.createElement('div');document.body.append(root);app=createApp(Component,{adapter:'openlist',mode:'isolated_proxy',mainOrigin:'https://stella.test',id:'a'.repeat(32),customEnabled:true,delivery:'proxy',authMode:'original'});app.component('RouterLink',{template:'<a><slot/></a>'});app.mount(root);await nextTick();expect(root.textContent).toBe('');expect(root.querySelector('button')).toBeNull();
});
