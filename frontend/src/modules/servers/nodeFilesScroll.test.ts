import {createApp,defineComponent,h,nextTick,reactive} from 'vue';
import {afterEach,expect,test,vi} from 'vitest';
const state=vi.hoisted(()=>({route:{name:'status',query:{view:'files'}}}));
vi.mock('vue-router',()=>({useRoute:()=>reactive(state.route)}));
vi.mock('./ServersSideBar.vue',()=>({default:defineComponent({render:()=>h('aside')})}));
import Page from './ServersPage.vue';
let app:ReturnType<typeof createApp>|undefined,host:HTMLDivElement;
afterEach(()=>{app?.unmount();host?.remove();});
test('only native files route enables the server content scrollport',async()=>{
 const route=reactive(state.route);host=document.createElement('div');document.body.append(host);
 app=createApp(Page);app.component('RouterView',{render:()=>h('section',{class:'node-files'},'files')});app.mount(host);await nextTick();
 expect(host.querySelector('.view-body')?.classList.contains('files-scroll')).toBe(true);
 route.query.view='overview';await nextTick();expect(host.querySelector('.view-body')?.classList.contains('files-scroll')).toBe(false);
 route.name='status-node';route.query.view='files';await nextTick();expect(host.querySelector('.view-body')?.classList.contains('files-scroll')).toBe(false);
});
