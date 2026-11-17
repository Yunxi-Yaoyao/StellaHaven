import {expect,it,vi} from 'vitest';
import {createNavController,defaults} from './controller';

it.each([500,502,503,408,undefined])('review R3: unknown ACK %s blocks every mutation until a successful GET',async status=>{
 let writes=0,failRead=false;const methods:string[]=[];
 const c=createNavController(async<T>(_p:string,o?:RequestInit)=>{methods.push(o?.method||'GET');if(o?.method){writes++;throw {status};}if(failRead)throw {status:403};return {revision:0,data:defaults()} as T;},()=> 'owner');
 await c.load();await c.save(defaults(),0);expect(c.uncertain.value).toBe(true);
 await c.save(defaults(),0);await c.save(defaults(),0,{source:'{}',digest:'digest',confirmed:true});expect(writes).toBe(1);
 failRead=true;await c.load();expect(c.uncertain.value).toBe(true);await c.save(defaults(),0);expect(writes).toBe(1);
 failRead=false;await c.load();expect(c.uncertain.value).toBe(false);await c.save(defaults(),0);expect(writes).toBe(2);
 expect(methods).toEqual(['GET','PUT','GET','GET','PUT']);
});
it.each([401,403,409,413,422])('review R3: explicit pre-ACK rejection %s is not permanently locked',async status=>{
 let writes=0;
 const c=createNavController(async<T>(_p:string,o?:RequestInit)=>{if(o?.method){writes++;throw {status};}return {revision:0,data:defaults()} as T;},()=> 'owner');
 await c.load();await c.save(defaults(),0);expect(c.uncertain.value).toBe(false);expect(c.conflict.value).toBe(status===409);
 await c.save(defaults(),0);expect(writes).toBe(2);
});
it.each([401,403,409,422,500,502,503])('review R3: successful ACK then failed readback %s is unknown',async status=>{
 let reads=0,writes=0;
 const c=createNavController(async<T>(_p:string,o?:RequestInit)=>{if(o?.method){writes++;return {revision:1,data:defaults()} as T;}if(++reads>1)throw {status};return {revision:0,data:defaults()} as T;},()=> 'owner');
 await c.load();await c.save(defaults(),0);expect(c.uncertain.value).toBe(true);await c.save(defaults(),0);expect(writes).toBe(1);
});
it('review R3: actual abort deadline is unknown, not a retry permission',async()=>{
 vi.useFakeTimers();let writes=0;
 try{
  const c=createNavController(async<T>(_p:string,o?:RequestInit)=>{if(o?.method){writes++;return await new Promise<T>((_,reject)=>o.signal?.addEventListener('abort',()=>reject(new DOMException('timeout','AbortError'))));}return {revision:0,data:defaults()} as T;},()=> 'owner');
  await c.load();const task=c.save(defaults(),0);await vi.advanceTimersByTimeAsync(15001);expect(await task).toBe(false);expect(c.uncertain.value).toBe(true);await c.save(defaults(),0);expect(writes).toBe(1);
 }finally{vi.useRealTimers();}
});
