/**
 * The stale list in every state it can be in.
 *
 * A page that returns its loading, empty or failure state instead of itself has no `h1`,
 * so the shell's skip link lands nowhere and a researcher cannot tell which page failed.
 * Each test below asserts the frame first and the state second.
 */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { StalePage } from './Stale';
import { ProjectPathProvider } from '../app/projectPaths';
import { expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const REFUSAL = 'the projection is being rebuilt';

const MARK = {
  object_id: 'C0001',
  priority: 4,
  reason: 'the evidence under it was re-anchored',
  source_change: 'A0017-3',
};

/** A daemon that has not answered yet, so the page stays in its loading state. */
function pendingDaemon(): FakeDaemon {
  return {
    fetch: (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

function refusingDaemon(): FakeDaemon {
  return fakeDaemon({
    capabilities: {
      'state.stale': {
        capability: 'state.stale',
        ok: false,
        error: { code: 'unavailable', message: REFUSAL },
      },
    },
  });
}

describe('the stale list', () => {
  it('keeps its heading and draws table rows while the read is in flight', () => {
    const { container } = renderView(<StalePage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Stale objects' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the stale set…');
    expect(
      container.querySelectorAll('.rh-skeleton-group[data-direction="row"]').length,
    ).toBeGreaterThan(1);
    // No count is claimed before one has arrived.
    expect(container.textContent).not.toMatch(/\d+ marked/);
  });

  it('keeps its heading when the read is refused, and offers the retry', async () => {
    renderView(<StalePage />, { daemon: refusingDaemon() });

    await waitFor(() => expect(screen.getByText(REFUSAL)).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Stale objects' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('says what a stale mark means and where the rest of the work is', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <StalePage />
      </ProjectPathProvider>,
      {
        daemon: fakeDaemon({ capabilities: { 'state.stale': { count: 0, marks: [] } } }),
        route: '/projects/prj_abc/stale',
        path: '/projects/prj_abc/stale',
      },
    );

    await waitFor(() => expect(screen.getByText('Nothing is stale')).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Stale objects' })).toBeInTheDocument();
    expect(screen.getByText(/rewritten silently/)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'See what else needs attention' }),
    ).toHaveAttribute('href', '/projects/prj_abc/overview');
    await expectNoAxeViolations(container);
  });

  it('reports the count the daemon gave once the marks arrive', async () => {
    renderView(<StalePage />, {
      daemon: fakeDaemon({ capabilities: { 'state.stale': { count: 1, marks: [MARK] } } }),
    });

    await waitFor(() => expect(screen.getByText(MARK.reason)).toBeInTheDocument());
    expect(screen.getByText(/1 marked, highest scientific impact first\./)).toBeInTheDocument();
  });
});
