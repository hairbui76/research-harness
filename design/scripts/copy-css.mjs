// Copy every .css file under src/ into dist/ at the same relative path, so `dist` is a
// complete ESM + CSS + d.ts package. tsc emits the JS and declarations; it ignores CSS.
import { cpSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, '..', 'src');
const dist = join(here, '..', 'dist');
if (!existsSync(src)) process.exit(0);
// Test snapshots live beside the components they cover; they are not part of the package.
const isTestArtifact = (p) => /\.(tsx?|md)$/.test(p) || /(^|[\\/])__snapshots__([\\/]|$)/.test(p);
cpSync(src, dist, { recursive: true, filter: (p) => p === src || !isTestArtifact(p) });
