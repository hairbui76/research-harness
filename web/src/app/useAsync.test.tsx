/**
 * A refusal replaces what a page had; silence does not.
 *
 * The rule this file holds is the one the whole cockpit's outage behaviour rests on: a read
 * that never reached the daemon keeps the answer the last one returned and raises no error
 * of its own, so the shell's single notice is what states the condition and no page puts a
 * second one under it. A read whose dependencies changed is a different question, and
 * answering it with the previous one's data would be inventing a result.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { daemonReachability } from '../api/client';
import { useAsync } from './useAsync';

afterEach(() => daemonReachability.reset());

describe('useAsync', () => {
  it('keeps the last answer when nothing answered, and reports no error of its own', async () => {
    let answer: () => Promise<string> = () => Promise.resolve('three works');
    const { result, rerender } = renderHook(({ tick }) => useAsync(() => answer(), [tick]), {
      initialProps: { tick: 0 },
    });

    await waitFor(() => expect(result.current.data).toBe('three works'));

    // The daemon goes away and the same read is asked again.
    answer = () => Promise.reject(new TypeError('Failed to fetch'));
    daemonReachability.unanswered('/capabilities/work.list', 'TypeError: Failed to fetch');
    result.current.reload();

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBe('three works');
    expect(result.current.error).toBeNull();

    // A different question is not answered with the previous one's data.
    rerender({ tick: 1 });
    await waitFor(() => expect(result.current.error).toMatch(/Failed to fetch/));
    expect(result.current.data).toBeNull();
  });

  it('lets a refusal replace what the page had, because the daemon answered', async () => {
    let answer: () => Promise<string> = () => Promise.resolve('three works');
    const { result } = renderHook(() => useAsync(() => answer(), []));

    await waitFor(() => expect(result.current.data).toBe('three works'));

    answer = () => Promise.reject(new Error('the workspace lock is held by another process'));
    result.current.reload();

    await waitFor(() => expect(result.current.error).toMatch(/workspace lock/));
    expect(result.current.data).toBeNull();
  });
});
