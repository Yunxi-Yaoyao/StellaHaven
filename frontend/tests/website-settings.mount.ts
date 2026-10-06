import '../src/style.css';
import {createApp,defineComponent,h} from 'vue';
import {createRouter,createMemoryHistory} from 'vue-router';
import ExternalModulePage from '../src/shell/ExternalModulePage.vue';
import SettingsPage from '../src/modules/settings/SettingsPage.vue';
import {auth} from '../src/modules/home/auth';
import NavigationSettings from '../src/modules/settings/NavigationSettings.vue';
import Icon from '../src/shell/Icon.vue';
import {navigationRows} from '../src/stores/navigation';
const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{render:()=>null}}]});
await router.push('/settings?section=navigation'+(new URLSearchParams(location.search).get('module')?'&module='+new URLSearchParams(location.search).get('module'):''));
// Test-only current-user context, not actual login acceptance or production credentials.
auth.me={id:'fixture-owner',username:'fixture',display_name:'Fixture Owner',is_admin:true,avatar_url:''} as any;
createApp(defineComponent({setup:()=>()=>h('main',[h('aside',{'aria-label':'实际侧栏'},navigationRows.value.filter(x=>x.visible).map(x=>h('div',{'data-nav-id':x.id},[h(Icon,{name:x.icon}),x.label]))),h(new URLSearchParams(location.search).has('full')?SettingsPage:NavigationSettings),new URLSearchParams(location.search).has('external')?h(ExternalModulePage,{id:'quota'}):null,h('div',{style:'display:none'},['file-text','hard-drive','unknown-icon'].map(name=>h(Icon,{name,'data-icon-test':name})))])})).use(router).mount('#app');
