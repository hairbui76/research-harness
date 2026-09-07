/**
 * The conflicts page in every state it can be in.
 *
 * This page reads `GET /overview`, so a failure of that read is a failure of the page. It
 * has to say so: "No open conflicts" over a refused read would report agreement nobody
 * established, on the one screen whose subject is disagreement.
 */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { ConflictsPage } from './Conflicts';
import { ProjectPathProvider } from '../app/projectPaths';
import { FIXTURES, expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const REFUSAL = 'the workspace lock is held by another process';

function pendingDaemon(): FakeDaemon {
  return {
    fetch: (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

function refusingDaemon(): FakeDaemon {
  return {
    fetch: (async () => new Response(REFUSAL, { status: 503 })) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

function overviewWith(conflicts: unknown[]): FakeDaemon {
  return fakeDaemon({ gets: { '/overview': { ...FIXTURES.overview, conflicts } } });
}

describe('the conflicts page', () => {
  it('keeps its heading and claims no count while the read is in flight', () => {
    const { container } = renderView(<ConflictsPage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Conflicts' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the conflict store…');
    expect(container.textContent).not.toMatch(/\d+ open\./);
  });

  it('reports a refused read rather than reporting agreement', async () => {
    renderView(<ConflictsPage />, { daemon: refusingDaemon() });

    await waitFor(() => expect(screen.getByText(REFUSAL)).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Conflicts' })).toBeInTheDocument();
    expect(screen.queryByText('No open conflicts')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('says what a conflict is and where one is resolved when there are none', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <ConflictsPage />
      </ProjectPathProvider>,
      {
        daemon: overviewWith([]),
        route: '/projects/prj_abc/conflicts',
        path: '/projects/prj_abc/conflicts',
      },
    );

    await waitFor(() => expect(screen.getByText('No open conflicts')).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Conflicts' })).toBeInTheDocument();
    expect(screen.getByText(/resolved on the candidate's own review screen/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open the review inbox' })).toHaveAttribute(
      'href',
      '/projects/prj_abc/review',
    );
    await expectNoAxeViolations(container);
  });

  it('names the two sides in words, and reads each position out as a line', async () => {
    const { container } = renderView(<ConflictsPage />, {
      daemon: overviewWith([
        {
          conflict_id: 'conf_0f2a1c33d4e5b607',
          kind: 'provider_disagreement',
          subject: 'cand_44c1f007fc0db0b2',
          summary: 'two providers read metric_result differently',
          tier: 2,
          status: 'open',
          created_at: '2026-09-05T10:00:00Z',
          differing_fields: ['metric_result'],
          positions: [
            {
              label: 'a/model-x',
              provider: 'a',
              model: 'model-x',
              decision: { value: '94.32', unit: 'percent' },
              rationale: 'the table reports it as a percentage',
            },
          ],
          proposed_changes: [],
        },
      ]),
    });

    await waitFor(() =>
      expect(screen.getByText('Provider against provider')).toBeInTheDocument(),
    );
    expect(screen.getByText(/Disagrees on: Metric result/)).toBeInTheDocument();
    expect(screen.getByText(/Tier 2 — deep review/)).toBeInTheDocument();
    expect(screen.getByText('two providers read metric result differently')).toBeInTheDocument();
    expect(screen.getByText('Value: 94.32 · Unit: percent')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/[{}]/);
    await expectNoAxeViolations(container);
  });

  it('counts the open conflicts once the read has answered', async () => {
    renderView(<ConflictsPage />, { daemon: overviewWith(FIXTURES.overview.conflicts) });

    await waitFor(() =>
      expect(
        screen.getByText(
          `${FIXTURES.overview.conflicts.length} open. A conflict is a question for a researcher; nothing below picks a winner.`,
        ),
      ).toBeInTheDocument(),
    );
  });
});
