import config from './vitest.full.config.mjs';
// Exclusive worker cache: do not publish optimizer artifacts into the common full-suite cache.
export default {...config,cacheDir:'node_modules/.cache/profile-actions'};
