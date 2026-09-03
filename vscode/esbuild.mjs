// Bundle the extension into one CommonJS file for the VS Code extension host.
//
// `vscode` is provided by the host and is never bundled. Everything else the extension
// needs is either Node builtin (`node:crypto`, `node:fs/promises`, `node:path`) or written
// in this repository, which is why the extension has no runtime dependencies at all.

import { build, context } from "esbuild";

const watch = process.argv.includes("--watch");

/** @type {import("esbuild").BuildOptions} */
const options = {
  entryPoints: ["src/extension.ts"],
  bundle: true,
  outfile: "dist/extension.js",
  external: ["vscode"],
  format: "cjs",
  platform: "node",
  target: "node20",
  sourcemap: true,
  minify: false,
  logLevel: "info",
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
} else {
  await build(options);
}
