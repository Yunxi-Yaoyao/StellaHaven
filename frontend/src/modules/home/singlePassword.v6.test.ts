import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createApp,nextTick} from 'vue';
import {auth,isAdmin,clearSecurity,security,securityChecked,acceptLogin} from './auth';
import {api,setElevationHandler} from '../../api/client';
import RetiredElevation from '../../shell/AdminElevationModal.vue';
import RetiredSecurity from '../settings/SecuritySettings.vue';
vi.mock('./settings',()=>({homeSettings:{},siteBackground:{value:''},DEFAULT_HOME_BG:''}));
beforeEach(()=>{auth.me=null;auth.suspended=false;auth.sessionClosing=false;auth.checked=true;clearSecurity();});
afterEach(()=>{vi.unstubAllGlobals();document.body.innerHTML='';});
it('only authenticated owner can manage, without a security request or legacy grant',()=>{
 const fetch=vi.fn();vi.stubGlobal('fetch',fetch);expect(isAdmin.value).toBe(false);
 acceptLogin({id:'owner',is_admin:false} as never);expect(isAdmin.value).toBe(true);
 clearSecurity();expect(isAdmin.value).toBe(true);
 auth.suspended=true;expect(isAdmin.value).toBe(false);
 auth.suspended=false;auth.sessionClosing=true;expect(isAdmin.value).toBe(false);
 auth.sessionClosing=false;auth.me=null;
 Object.assign(security,{enabled:false,elevated:true});securityChecked.value=true;
 expect(isAdmin.value).toBe(false);expect(fetch).not.toHaveBeenCalled();
});
it.each(['admin_setup_required','admin_elevation_required','resource_forbidden'])('403 %s is visible and never unlocks or replays',async code=>{
 acceptLogin({id:'owner'} as never);const unlock=vi.fn(async()=>true);setElevationHandler(unlock);
 const fetch=vi.fn(async()=>Response.json({detail:{code,message:'仍然拒绝'}},{status:403}));vi.stubGlobal('fetch',fetch);
 await expect(api('/integration-targets/resolve',{method:'POST',body:'{}'})).rejects.toMatchObject({status:403,detail:{code,message:'仍然拒绝'}});
 expect(fetch).toHaveBeenCalledTimes(1);expect(unlock).not.toHaveBeenCalled();expect(document.querySelector('[role=dialog]')).toBeNull();
});
it('legacy component imports are inert and never expose or submit a second password',async()=>{
 acceptLogin({id:'owner'} as never);const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
 const root=document.createElement('div');document.body.append(root);const app=createApp({components:{RetiredElevation,RetiredSecurity},template:'<RetiredElevation/><RetiredSecurity/>'});app.mount(root);await nextTick();
 expect(root.querySelector('input,form,[role=dialog]')).toBeNull();expect(root.textContent).not.toContain('管理密码');expect(fetch).not.toHaveBeenCalled();app.unmount();
});
