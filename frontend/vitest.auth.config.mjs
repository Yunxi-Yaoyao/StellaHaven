import { defineConfig } from 'vitest/config';
export default defineConfig({ test: { include: ['src/modules/home/auth.test.ts'], environment: 'jsdom' } });
