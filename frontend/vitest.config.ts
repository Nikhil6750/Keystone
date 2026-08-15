import path from 'node:path';
import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': dirname,
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    globals: true,
    css: false,
    // Vitest's 5s default was observed to intermittently time out
    // individual tests (not consistently the same one) when the full
    // suite runs under heavy concurrent machine load -- every test that
    // hit it passed reliably in isolation, confirming resource
    // contention rather than a hang. 15s keeps a real ceiling against a
    // genuine infinite loop/hang while giving normal tests headroom under
    // load; tests/routes/routes.test.tsx sets its own longer per-test
    // timeout for its slower cold dynamic-import case.
    testTimeout: 15_000,
  },
});
