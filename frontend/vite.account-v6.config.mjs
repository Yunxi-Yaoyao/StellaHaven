import base from './vite.config';
export default {...base,cacheDir:process.env.STELLA_ACCOUNT_CACHE||'/root/.hermes/cache/scratch/account-v6/vite-build',build:{...base.build,outDir:process.env.STELLA_ACCOUNT_DIST||'/root/.hermes/cache/scratch/account-v6/dist',emptyOutDir:true}};
