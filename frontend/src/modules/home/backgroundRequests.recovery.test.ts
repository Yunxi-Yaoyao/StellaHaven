// @vitest-environment jsdom
import {test,expect,vi,afterEach} from 'vitest';
import {auth} from './auth';
import {backgroundEntries,loadBackgroundEntries,backgroundMedia,reloadBackgroundMedia} from './backgroundMedia';
const owner={id:'a',username:'a',display_name:'A',is_admin:false,avatar_url:'',home_bg:'',email:'',email_verified:false};
afterEach(()=>{vi.unstubAllGlobals();});
test.each(['entries','media'] as const)('shared %s read cannot publish after an owner change',async kind=>{
 Object.assign(auth,{me:{...owner},sessionGeneration:0,requestEpoch:0,suspended:false,sessionClosing:false});
 let release!:(r:Response)=>void;vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(r=>release=r)));
 const pending=kind==='entries'?loadBackgroundEntries():reloadBackgroundMedia('/assets/homebg/a.png');
 auth.me={...owner,id:'b'};backgroundEntries.value=[];delete backgroundMedia['/assets/homebg/a.png'];
 release(new Response(JSON.stringify(kind==='entries'?[{id:'a',name:'A',url:'/a.png'}]:{url:'/assets/homebg/a.png',status:'ready',variants:{original:'/assets/homebg/a.png'}})));
 await pending.catch(()=>{});expect(backgroundEntries.value).toEqual([]);expect(backgroundMedia['/assets/homebg/a.png']).toBeUndefined();
});
