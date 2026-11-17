import vue from '@vitejs/plugin-vue';
export default {plugins:[vue()],test:{include:['src/stores/navigation.save-light.test.ts','src/modules/settings/WebsiteSettings.save-light.test.ts'],environment:'jsdom',pool:'forks',maxWorkers:1,minWorkers:1},cacheDir:'node_modules/.cache/save-light'};
