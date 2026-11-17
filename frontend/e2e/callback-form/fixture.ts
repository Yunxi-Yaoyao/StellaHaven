// Synthetic fixture only. run.mjs replaces home/auth and api/client modules.
import {createApp} from 'vue';
import AuthProviderSettings from '../../src/modules/settings/AuthProviderSettings.vue';
createApp(AuthProviderSettings).mount('#app');
