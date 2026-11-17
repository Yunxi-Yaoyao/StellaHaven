import {preview} from 'vite';
// Serve the actual production candidate bundle, not a hand-made fixture page.
// API responses are intercepted by Playwright; there is no live backend proxy.
await preview({configFile:false,preview:{host:'127.0.0.1',port:15316,strictPort:true,proxy:{}}});
