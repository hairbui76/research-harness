/*
 * jest-dom's matchers are registered against this package's own `expect` rather than through
 * `@testing-library/jest-dom/vitest`. That entry point imports `vitest` itself, and a workspace
 * with more than one peer-resolved vitest build registers a second set of chai plugins that
 * replaces `toMatchSnapshot` with one bound to a SnapshotClient the runner never primed. The
 * design package does the same; see design/tests/setup.ts.
 */
import * as matchers from '@testing-library/jest-dom/matchers';
import { expect } from 'vitest';

// Node 25's process-level `localStorage` can replace jsdom's complete implementation in
// Vitest 2. Recover a browser-compatible Storage object from a same-origin window.
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
