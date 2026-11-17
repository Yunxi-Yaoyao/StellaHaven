import '../src/style.css';
import {createApp,h} from 'vue';
import {createMemoryHistory,createRouter,RouterView} from 'vue-router';
import SettingsPage from '../src/modules/settings/SettingsPage.vue';
import {auth,security,securityChecked} from '../src/modules/home/auth';
// Explicit synthetic owner/elevation; this fixture never authenticates to a real service.
auth.me={id:'fixture-owner',username:'fixture',display_name:'Fixture Owner',is_admin:true,avatar_url:'',home_bg:'',email:'',email_verified:false};
Object.assign(security,{enabled:true,configured:true,elevated:true,expires_at:null,single_user:true,setup_required:false});securityChecked.value=true;
const router=createRouter({history:createMemoryHistory(),routes:[{path:'/settings',component:SettingsPage},{path:'/:pathMatch(.*)*',component:{render:()=>null}}]});
await router.push('/settings?section='+(new URLSearchParams(location.search).get('section')||'services'));
createApp({render:()=>h('main',[h(RouterView)])}).use(router).mount('#app');
