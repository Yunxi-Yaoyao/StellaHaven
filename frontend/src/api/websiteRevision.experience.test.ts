import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {getWebsite} from './integrations';
import {auth} from '../modules/home/auth';
const item={id:'revision-site',name:'Site',icon:'globe',enabled:true,mode:'iframe',adapter:'generic',browser_url:'https://site.test/'};
beforeEach(()=>{Object.assign(auth,{me:{id:'revision-owner'},sessionClosing:false,suspended:false,sessionGeneration:1,requestEpoch:1});});
afterEach(()=>{vi.unstubAllGlobals();});
it('binds the exact detail response ETag rather than current navigation revision',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(item),{status:200,headers:{'Content-Type':'application/json',ETag:'"7"'}})));
 const got=await getWebsite(item.id);expect(got).toMatchObject({...item,read_revision:7});
});
it('retains the valid zero revision for an unedited aggregate',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(item),{status:200,headers:{ETag:'"0"'}})));
 expect((await getWebsite(item.id)).read_revision).toBe(0);
});
it.each(['W/"7"','"-1"','"7.5"','"9007199254740993"',' 7 '])('does not accept malformed or weak edit ETag %s',async(tag)=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(item),{status:200,headers:{ETag:tag}})));
 await expect(getWebsite(item.id)).rejects.toThrow('版本');
});
it('does not accept version metadata from a response arriving after an owner change',async()=>{
 let finish!:(v:Response)=>void;vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(r=>{finish=r;})));
 const pending=getWebsite(item.id);auth.requestEpoch++;
 finish(new Response(JSON.stringify(item),{status:200,headers:{ETag:'"7"'}}));
 await expect(pending).rejects.toThrow();
});
