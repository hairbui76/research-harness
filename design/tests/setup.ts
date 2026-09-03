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

expect.extend(matchers);
