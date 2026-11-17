import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],test:{environment:'jsdom',include:['src/modules/auth/oidcLoginContinuation.test.ts','src/router/startup.test.ts','src/modules/auth/loginPolish.test.ts','src/modules/auth/browserLogin.test.ts','src/modules/auth/loginStatusRace.test.ts'],pool:'forks',maxWorkers:1,minWorkers:1}});
