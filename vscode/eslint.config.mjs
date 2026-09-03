import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/**", "out/**", "node_modules/**", "src/test/fixtures/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      "@typescript-eslint/consistent-type-imports": "off",
      eqeqeq: ["error", "smart"],
      "no-console": "error",
    },
  },
  {
    files: ["src/test/**/*.ts", "esbuild.mjs", "vitest.config.ts"],
    languageOptions: { globals: { process: "readonly" } },
    rules: { "no-console": "off" },
  },
);
