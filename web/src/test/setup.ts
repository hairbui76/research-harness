/*
 * jest-dom's matchers are registered against this package's own `expect` rather than through
 * `@testing-library/jest-dom/vitest`. That entry point imports `vitest` itself, and a workspace
 * with more than one peer-resolved vitest build registers a second set of chai plugins that
 * replaces `toMatchSnapshot` with one bound to a SnapshotClient the runner never primed. The
 * design package does the same; see design/tests/setup.ts.
 */
import * as matchers from '@testing-library/jest-dom/matchers';
import { expect } from 'vitest';

expect.extend(matchers);
