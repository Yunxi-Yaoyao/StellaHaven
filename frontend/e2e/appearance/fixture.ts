import {createApp,defineComponent,h,ref} from 'vue';
import AppearanceSettings from '../../src/modules/settings/AppearanceSettings.vue';
import {startClientPreferenceSync,clientPreferenceSync} from '../../src/modules/settings/clientPreferenceSync';
import * as appearance from '../../src/stores/appearance';
import {auth} from '../../src/modules/home/auth';
import '../../src/style.css';
const show=ref(true);startClientPreferenceSync();
createApp(defineComponent({setup:()=>()=>h('div',[h('nav',{class:'fixture-navigation'},[h('button',{onClick:()=>show.value=!show.value},'切换页面')]),show.value?h(AppearanceSettings):h('p','其他设置页面')])})).mount('#app');
Object.assign(window,{appearanceFixture:{appearance,clientPreferenceSync,auth}});
