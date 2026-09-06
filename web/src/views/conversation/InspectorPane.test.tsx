/**
 * The inspector's Conflicts tab, when the read behind it failed.
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
});
