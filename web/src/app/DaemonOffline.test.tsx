/**
 * The daemon stops answering, and the cockpit stays a cockpit.
 *
 * The old shape of this was three notices for one cause: the rail said `Daemon — offline`,
 * the token bar offered a token form for a process that was not there to take one, and
 * whichever page happened to be open put its own error box in the body. None of them said
 * what would come back on its own, and none of them said whether anything had been lost.
 *
 * What is asserted here is the replacement: one polite `role="status"` notice in the shell,
 * never `alert` and never a dialog, that names what is safe, what resumes by itself and the
 * one thing a researcher can do; the page frame still mounted underneath it; a composer
 * draft untouched; and the notice clearing on recovery without a reload.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Layout } from './Layout';
import { daemonReachability } from '../api/client';
import { draftKey } from '../views/conversation/useDraft';
import { expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

afterEach(() => daemonReachability.reset());

/** A daemon that is not listening: `fetch` rejects, the way it does on `ECONNREFUSED`. */
function silentDaemon(): FakeDaemon {
  return {
    fetch: (async () => {
      throw new TypeError('Failed to fetch');
    }) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

/** One daemon that can be taken away and given back while the shell stays mounted. */
function flakyDaemon() {
  let live = true;
  const inner = fakeDaemon();
  const daemon: FakeDaemon = {
    fetch: (async (input: RequestInfo | URL, init?: RequestInit) => {
      if (!live) throw new TypeError('Failed to fetch');
      return inner.fetch(input, init);
    }) as unknown as typeof fetch,
    calls: inner.calls,
    capabilityCalls: inner.capabilityCalls,
  };
  return {
    daemon,
    stop: () => {
      live = false;
    },
    start: () => {
      live = true;
    },
  };
}

function renderShell(daemon: FakeDaemon) {
  return renderView(<Layout />, { daemon, token: 'local-token', route: '/review', path: '*' });
}

/** The one notice, wherever in the shell it happens to sit. */
function notice(): HTMLElement {
  const found = screen
    .getAllByRole('status')
    .find((node) => node.textContent?.includes('Research Harness is not answering'));
  if (!found) throw new Error('the offline notice is not on screen');
  return found;
}

describe('the daemon stops answering', () => {
  it('says so once, politely, and says what is safe', async () => {
    renderShell(silentDaemon());

    await waitFor(() => expect(notice()).toBeInTheDocument());
    // Polite, not assertive: an outage is a condition to live with for a moment, not an
    // interruption to acknowledge.
    expect(notice()).toHaveAttribute('role', 'status');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    // What is safe, what resumes by itself, and the one thing to do about it.
    expect(notice()).toHaveTextContent('Your draft is safe.');
    expect(notice()).toHaveTextContent(/re-read themselves/);
    expect(notice()).toHaveTextContent(/research serve/);
    expect(within(notice()).getByRole('button', { name: 'Ask the daemon again' })).toBeInTheDocument();
  });

  it('says it once, not twice: the token form does not ask a daemon that is not there', async () => {
    renderShell(silentDaemon());

    await waitFor(() => expect(notice()).toBeInTheDocument());
    expect(screen.queryByText('The daemon did not answer')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Local token')).not.toBeInTheDocument();
    expect(
      screen.getAllByRole('status').filter((node) => node.textContent?.includes('not answering')),
    ).toHaveLength(1);
  });

  it('keeps the shell mounted underneath it', async () => {
    renderShell(silentDaemon());

    await waitFor(() => expect(notice()).toBeInTheDocument());
    // The skip link, the rail with all eleven destinations, and `main`: an outage does not
    // take the cockpit away, and every screen is still one click from here.
    expect(screen.getByRole('link', { name: /Skip to/i })).toBeInTheDocument();
    const rail = screen.getByRole('navigation', { name: 'Project navigation' });
    expect(within(rail).getAllByRole('link').length).toBeGreaterThan(5);
    expect(screen.getByRole('main')).toBeInTheDocument();
    // The rail's own footer still names the state in words, not in colour alone.
    expect(screen.getByText('Daemon')).toBeInTheDocument();
  });

  it('leaves an unsent draft exactly where it was', async () => {
    const stored = JSON.stringify({ text: 'the paragraph I had not sent', tokens: [] });
    window.localStorage.setItem(draftKey('CS0001'), stored);
    renderShell(silentDaemon());

    await waitFor(() => expect(notice()).toBeInTheDocument());
    expect(window.localStorage.getItem(draftKey('CS0001'))).toBe(stored);
    window.localStorage.removeItem(draftKey('CS0001'));
  });

  it('clears itself when the daemon answers again, with no reload', async () => {
    const user = userEvent.setup();
    const flaky = flakyDaemon();
    renderShell(flaky.daemon);

    const rail = await screen.findByRole('navigation', { name: 'Project navigation' });
    flaky.stop();
    daemonReachability.unanswered('/overview', 'TypeError: Failed to fetch');
    await waitFor(() => expect(notice()).toBeInTheDocument());

    flaky.start();
    await user.click(within(notice()).getByRole('button', { name: 'Ask the daemon again' }));
    await waitFor(() =>
      expect(
        screen.queryAllByRole('status').some((n) => n.textContent?.includes('not answering')),
      ).toBe(false),
    );
    // Still the same tree: nothing was remounted to recover, so nothing a researcher had
    // on screen — or had typed — went through an unmount to get the daemon back.
    expect(screen.getByRole('navigation', { name: 'Project navigation' })).toBe(rail);
  });

  it('offers exactly one way to ask again, in the one notice that states the outage', async () => {
    /*
     * `daemon-offline.png` caught the same condition stated twice: this notice, and the open
     * page's own "Try again: Waiting for the daemon" under it, each with its own retry
     * button. One condition, one notice, one way to ask again.
     */
    renderShell(silentDaemon());

    await waitFor(() => expect(notice()).toBeInTheDocument());
    expect(
      screen.getAllByRole('button', { name: /again/i }).map((button) => button.textContent),
    ).toEqual(['Ask the daemon again']);
  });

  it('says when the window last had an answer, so what is on screen has an age', async () => {
    const flaky = flakyDaemon();
    renderShell(flaky.daemon);

    await screen.findByRole('navigation', { name: 'Project navigation' });
    flaky.stop();
    daemonReachability.unanswered('/overview', 'TypeError: Failed to fetch');

    await waitFor(() => expect(notice()).toHaveTextContent(/read at \d/));
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = renderShell(silentDaemon());

    await waitFor(() => expect(notice()).toBeInTheDocument());
    await expectNoAxeViolations(container);
  });
});
