import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * The specimen gallery's own Vite config.
 *
 * `vite specimens` resolves its config from the root it is given (`design/specimens`), not
 * from the package directory, so the package-level `vite.config.ts` — which is the vitest
 * config — is never loaded here and the React plugin would be missing without this file.
 * Keeping them separate also stops the gallery's build options leaking into the test run.
 */
export default defineConfig({
  plugins: [react()],
  server: { open: false },
  build: { emptyOutDir: true },
});
