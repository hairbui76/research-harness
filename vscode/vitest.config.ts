import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// The unit tests import extension modules directly, so `vscode` - which only exists inside
// the extension host - is aliased to the hand-written mock in `src/test/vscode-mock.ts`.
// Anything that needs the real editor API belongs in the optional `@vscode/test-electron`
// suite, which is skipped unless RESEARCH_HARNESS_VSCODE_E2E=1 (see docs/architecture/vscode.md).
export default defineConfig({
  resolve: {
    alias: {
      vscode: fileURLToPath(new URL("./src/test/vscode-mock.ts", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["src/test/**/*.test.ts"],
    reporters: ["default"],
  },
});
