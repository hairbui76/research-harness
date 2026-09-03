import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    // `dist`/`node_modules` are build output; the rest is the legacy Warmline prototype
    // bundle, which stays in place as a design reference until W5 deletes it (see the
    // v1.1 implementation plan). It is not TypeScript and is never imported by `src`.
    ignores: [
      'dist',
      'node_modules',
      'legacy',
      '_ds_bundle.js',
      'components/**',
      'ui_kits/**',
      'guidelines/**',
      'templates/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.es2022 },
    },
    rules: {
      'no-undef': 'off',
      '@typescript-eslint/consistent-type-imports': ['error', { disallowTypeAnnotations: false }],
    },
  },
  {
    files: ['scripts/**/*.mjs'],
    languageOptions: { globals: { ...globals.node } },
  },
);
