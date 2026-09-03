/// <reference types="vite/client" />
// The package's tsconfig types the test run, not a Vite app, so `import.meta.glob` is
// declared here rather than by widening `types` for everything.
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Gallery } from './Gallery';
import type { SpecimenGroup, SpecimenModule } from './Gallery';
import '../src/styles.css';
import './gallery.css';

/**
 * Every specimen file in the package, collected at build time.
 *
 * `eager: true` means the gallery is one bundle with no dynamic imports, so it runs from a
 * plain static server without any of the network conditions the product itself refuses to
 * depend on. The second glob picks up `primitives.specimen.tsx`, which lives here rather
 * than beside the primitives because DS1a and DS1b own those folders.
 */
const modules: Record<string, SpecimenModule> = {
  ...import.meta.glob<SpecimenModule>('../src/**/*.specimen.tsx', { eager: true }),
  ...import.meta.glob<SpecimenModule>('./*.specimen.tsx', { eager: true }),
};

/** `../src/manuscript/FileTree/FileTree.specimen.tsx` -> `manuscript`; `./x.specimen.tsx` -> `primitives`. */
function folderOf(path: string): string {
  if (!path.startsWith('../src/')) return 'primitives';
  return path.replace('../src/', '').split('/')[0] ?? 'other';
}

const groups: SpecimenGroup[] = Object.entries(modules)
  .map(([path, module]) => ({ folder: folderOf(path), path, module }))
  .sort((a, b) => a.folder.localeCompare(b.folder) || a.module.title.localeCompare(b.module.title));

const container = document.getElementById('root');
if (!container) throw new Error('The specimen gallery needs a #root element.');

createRoot(container).render(
  <StrictMode>
    <Gallery groups={groups} />
  </StrictMode>,
);
