import {defineConfig} from 'vitest/config';
import vue from '@vitejs/plugin-vue';
export default defineConfig({plugins:[vue()],test:{environment:'jsdom',include:['src/modules/auth/loginModal.test.ts','src/modules/auth/sessionSuspension.test.ts','src/router/startup.test.ts','src/modules/home/auth.test.ts','src/modules/auth/reviewRegression.test.ts','src/modules/auth/privateMedia.test.ts']}});
