import {createApp,nextTick} from 'vue'
import {afterEach,expect,test,vi} from 'vitest'
import Files from './NodeFilesView.vue'
let app:ReturnType<typeof createApp>|undefined,host:HTMLDivElement
async function settle(){for(let i=0;i<30;i++)await Promise.resolve();await nextTick()}
afterEach(()=>{app?.unmount();host?.remove();vi.unstubAllGlobals();sessionStorage.clear()})
test('actual node permission denial is not described as an offline or network failure',async()=>{
 const calls:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>{calls.push(url);return new Response(JSON.stringify(url==='/node-files/nodes'?[{id:19,name:'Linux fixture',online:true,roots:[{id:'system',label:'/',write:false,blocked:false}]}]:{id:'owned-list',state:'failed',error:'permission_denied'}),{status:200,headers:{'Content-Type':'application/json'}})}))
 host=document.createElement('div');document.body.append(host);app=createApp(Files,{scopeKey:'owned:1:1'});app.mount(host);await settle()
 expect(calls).toContain('/node-files/requests')
 expect(host.textContent).toContain('节点当前运行用户无权读取此文件或目录（EACCES/EPERM）；未提权。')
 expect(host.textContent).not.toContain('节点离线')
 expect(host.textContent).not.toContain('permission_denied')
})
