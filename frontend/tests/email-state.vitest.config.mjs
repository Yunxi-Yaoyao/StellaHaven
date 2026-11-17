import config from '../vitest.full.config.mjs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
export default {...config,cacheDir:join(tmpdir(),'stella-email-state-worker-vite')};
