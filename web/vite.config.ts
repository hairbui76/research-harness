/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The cockpit is served two ways: by the daemon itself from `dist/` (same origin), and by
// this dev server against a daemon started with RESEARCH_HARNESS_DEV=1. Nothing else.
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: { port: 5173, strictPort: true, host: '127.0.0.1' },
  build: { outDir: 'dist', sourcemap: true },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
});
