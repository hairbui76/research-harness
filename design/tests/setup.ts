/*
 * Test setup.
 *
 * jest-dom's matchers are registered against *this* package's `expect` rather than through
 * its `@testing-library/jest-dom/vitest` entry point. That entry imports `vitest` itself,
 * and in this workspace `design` and `web` resolve two distinct `vitest@2.1.9` instances
 * (they differ only by their `@types/node` peer). Both register their chai plugins on the
 * single shared `chai` instance, so the second one to load replaces `toMatchSnapshot` with
 * a matcher bound to a SnapshotClient the runner never primed — and every snapshot in the
 * package fails with "Cannot read properties of undefined (reading 'match')".
 *
 * Extending the local `expect` with the matchers module keeps the second vitest out of the
 * worker entirely. A workspace install that gives `design` and `web` one vitest instance
 * would also fix it; this form is correct either way.
 */
import * as matchers from '@testing-library/jest-dom/matchers';
import { expect } from 'vitest';

// Node 25 exposes an incomplete process-level `localStorage` unless it is given a
// persistence file. Vitest 2 copies that object over jsdom's implementation. Recover
// the browser-compatible Storage object from a fresh same-origin window so tests keep
// exercising the web API on every supported Node version.
if (typeof window.localStorage.clear !== 'function') {
  const frame = document.createElement('iframe');
  document.documentElement.appendChild(frame);
  const storage = frame.contentWindow?.localStorage;
  frame.remove();
  if (storage !== undefined) {
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: storage,
    });
  }
}

expect.extend(matchers);
