/**
 * The inspector's Conflicts tab, when the read behind it failed — and what its empty states
 * print above their own sentence.
 *
 * Five of the six tabs fetch for themselves and already render a refusal. Conflicts does
 * not: it renders what `GET /overview` returned, so when that read failed it used to say
 * "No open conflicts" — reporting agreement the daemon never claimed, on the one tab whose
 * whole purpose is disagreement. It has to say what happened instead, and offer the retry.
 */
import { describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@research-harness/design';
import { InspectorPane } from './InspectorPane';
import { ConversationProvider } from './state';
import { HarnessClient } from '../../api/client';
import { SessionProvider } from '../../app/session';
import { FIXTURES, fakeDaemon } from '../../test/harness';
import type { FakeDaemon } from '../../test/harness';

const REFUSAL = 'the workspace lock is held by another process';

/**
 * A daemon that answers everything except the one read the Conflicts tab depends on, and
 * counts how many times that read was attempted — which is what a retry has to change.
 */
function daemonWithRefusedOverview(): FakeDaemon & { overviewReads: () => number } {
  const inner = fakeDaemon();
  let reads = 0;
  const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://daemon.test');
    if (url.pathname === '/overview') {
      reads += 1;
      return new Response(REFUSAL, { status: 503 });
    }
    return inner.fetch(input, init);
  }) as unknown as typeof fetch;
  return { ...inner, fetch: fetchImpl, overviewReads: () => reads };
}

function renderInspector(daemon: FakeDaemon) {
  const client = new HarnessClient({
    baseUrl: 'http://daemon.test',
    token: 'local-token',
    fetchImpl: daemon.fetch,
  });
  return render(
    <ThemeProvider defaultTheme="dark" storageKey={null}>
      <ToastProvider>
        <MemoryRouter
          initialEntries={['/']}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <SessionProvider client={client}>
            <ConversationProvider>
              <InspectorPane />
            </ConversationProvider>
          </SessionProvider>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

async function openConflicts(): Promise<void> {
  const user = userEvent.setup();
  await user.click(screen.getByRole('tab', { name: /Conflicts/ }));
}

describe('the inspector’s conflicts tab', () => {
  it('reports the refusal rather than reporting agreement', async () => {
    const daemon = daemonWithRefusedOverview();
    renderInspector(daemon);
    await waitFor(() => expect(screen.getByRole('tab', { name: /Conflicts/ })).toBeInTheDocument());
    await openConflicts();

    expect(screen.getByText(REFUSAL)).toBeInTheDocument();
    expect(screen.queryByText('No open conflicts')).not.toBeInTheDocument();
  });

  it('offers the same retry the rest of the cockpit does, and asks again', async () => {
    const user = userEvent.setup();
    const daemon = daemonWithRefusedOverview();
    renderInspector(daemon);
    await waitFor(() => expect(screen.getByRole('tab', { name: /Conflicts/ })).toBeInTheDocument());
    await openConflicts();

    const before = daemon.overviewReads();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    await waitFor(() => expect(daemon.overviewReads()).toBeGreaterThan(before));
  });

  it('still says nothing is in dispute when the read succeeded and found none', async () => {
    const daemon = fakeDaemon({ gets: { '/overview': { ...FIXTURES.overview, conflicts: [] } } });
    renderInspector(daemon);
    await waitFor(() => expect(screen.getByRole('tab', { name: /Conflicts/ })).toBeInTheDocument());
    await openConflicts();

    expect(screen.getByText('No open conflicts')).toBeInTheDocument();
  });

  it('says it once: no generic label above a title that already names the state', async () => {
    const daemon = fakeDaemon({ gets: { '/overview': { ...FIXTURES.overview, conflicts: [] } } });
    renderInspector(daemon);
    await waitFor(() => expect(screen.getByRole('tab', { name: /Conflicts/ })).toBeInTheDocument());
    await openConflicts();

    expect(screen.getByText('No open conflicts')).toBeInTheDocument();
    expect(screen.queryByText('Nothing here yet')).not.toBeInTheDocument();
  });
});

describe('the inspector with nothing followed', () => {
  it('says “nothing selected” once, in the tab that can do something about it', async () => {
    renderInspector(fakeDaemon());
    await waitFor(() => expect(screen.getAllByRole('tab')).toHaveLength(6));

    // The pane used to say it twice: a line above the strip, and the Context tab's own
    // empty card under it. The card is the one that teaches, so the line is gone.
    expect(screen.getAllByText('Nothing selected')).toHaveLength(1);
    expect(
      screen.queryByText('Nothing selected. Choose a message, reference or attachment.'),
    ).toBeNull();
    expect(
      screen.getByText('Open a reference or inspect a message to see what the graph joins it to.'),
    ).toBeInTheDocument();
  });
});

/*
 * Six tabs measuring about 734px live in a pane that is about 352px wide, so two of them —
 * Conflicts and Stale, the two that say something is wrong — used to be off the end of the
 * strip with nothing on screen admitting they existed. The strip is a scroller now, and the
 * contract this file can check without a browser is the one that matters most: every tab is
 * in the document, in the daemon's order, and the arrow keys walk all six of them.
 * `browser-tests/layout.spec.ts` checks that each one is actually scrolled into view.
 */
describe('the inspector’s tab strip', () => {
  const LABELS = ['Context', 'Evidence', 'Claims', 'Review inbox', 'Conflicts', 'Stale'];

  it('carries all six tabs, and the arrow keys reach every one of them', async () => {
    const user = userEvent.setup();
    renderInspector(fakeDaemon());
    await waitFor(() => expect(screen.getAllByRole('tab')).toHaveLength(6));

    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent?.replace(/\d+.*$/, '').trim())).toEqual(LABELS);

    (tabs[0] as HTMLElement).focus();
    for (let index = 1; index < tabs.length; index += 1) {
      await user.keyboard('{ArrowRight}');
      expect(tabs[index]).toHaveFocus();
    }

    // The strip is one row that scrolls, not a row that clips.
    const list = screen.getByRole('tablist');
    expect(list.parentElement).toHaveClass('rh-tabs__strip');
    expect(list).toHaveAttribute('data-overflow', 'scroll');
  });
});
