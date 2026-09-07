/**
 * The conflicts page in every state it can be in.
 *
 * This page reads `GET /overview`, so a failure of that read is a failure of the page. It
 * has to say so: "No open conflicts" over a refused read would report agreement nobody
 * established, on the one screen whose subject is disagreement.
 *
 * What it renders is the daemon's grouping (`conflict_groups`) rather than its own: which
 * kind of disagreement a record is, in what order, and where it is decided are the daemon's
 * judgements. A conflict that only appears in `conflicts` and in no group is therefore not
 * on the page at all, which is what these fixtures spell out.
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

/**
 * `GET /overview` with these conflicts, grouped the way the daemon groups them: one group
 * per kind, in first-seen order, each item carrying the route the daemon chose for that
 * subject. Hand-building the grouping here is the point — the page must render it, and a
 * fixture that omitted it would let the page go back to deciding for itself.
 */
function overviewWith(
  conflicts: {
    conflict_id: string;
    kind: string;
    subject: string;
    summary: string;
    tier: number;
    name?: string;
  }[],
): FakeDaemon {
  const kinds = [...new Set(conflicts.map((conflict) => conflict.kind))];
  const conflict_groups = kinds.map((kind) => {
    const members = conflicts.filter((conflict) => conflict.kind === kind);
    return {
      kind,
      label: members.length === 1 ? '1 conflict' : `${members.length} conflicts`,
      count: members.length,
      route: '/conflicts',
      surface: 'conflict',
      items: members.map((conflict) => ({
        // The daemon composes the subject's name; the id is in the route and nowhere else.
        id: conflict.conflict_id,
        label: conflict.name ?? conflict.subject,
        detail: conflict.summary,
        priority: conflict.tier,
        route: conflict.subject.startsWith('cand_') ? `/review/${conflict.subject}` : '',
      })),
    };
  });
  const counted =
    conflicts.length === 1 ? '1 conflict is' : `${conflicts.length} conflicts are`;
  return fakeDaemon({
    gets: {
      '/overview': {
        ...FIXTURES.overview,
        conflicts,
        conflict_groups,
        conflict_summary:
          conflicts.length === 0
            ? 'Nothing in this project is in dispute.'
            : `${counted} open. Every side is kept, and none of them is preferred until you decide.`,
      },
    },
  });
}

/** One open disagreement, as the store records it. */
const CONFLICT = {
  conflict_id: 'conf_0f2a1c33d4e5b607',
  kind: 'provider_disagreement',
  subject: 'cand_44c1f007fc0db0b2',
  // What the review queue calls that candidate, composed by the daemon (`app.py`).
  name: 'metric_result · W0001',
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
};

describe('the conflicts page', () => {
  it('keeps its heading and claims no count while the read is in flight', () => {
    const { container } = renderView(<ConflictsPage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Conflicts' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the conflict store…');
    expect(container.textContent).not.toMatch(/\d+ conflicts? (is|are) open\./);
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
    const { container } = renderView(<ConflictsPage />, { daemon: overviewWith([CONFLICT]) });

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

  /**
   * The page used to test `subject.startsWith('cand_')` itself to decide whether a conflict
   * could be opened. Where a disagreement is decided is a fact about the workspace, so the
   * daemon says it and the page follows — including when the answer is "nowhere".
   */
  it('follows the route the daemon gave, and links nothing when it gave none', async () => {
    const elsewhere = {
      ...CONFLICT,
      conflict_id: 'conf_11111111',
      kind: 'candidate_vs_accepted',
      subject: 'table-1',
      name: 'table-1',
      summary: 'the staged reading of table-1 differs from the accepted one',
    };
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <ConflictsPage />
      </ProjectPathProvider>,
      {
        daemon: overviewWith([CONFLICT, elsewhere]),
        route: '/projects/prj_abc/conflicts',
        path: '/projects/prj_abc/conflicts',
      },
    );

    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'metric result · W0001' })).toHaveAttribute(
        'href',
        '/projects/prj_abc/review/cand_44c1f007fc0db0b2',
      ),
    );
    expect(screen.getByText('table-1')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'table-1' })).not.toBeInTheDocument();
    expect(screen.getByText('Candidate against accepted state')).toBeInTheDocument();
  });

  /**
   * `contested` is a scientific authority: it says the corpus examined a claim and found
   * its evidence pointing both ways. An open conflict is a question nobody has answered, so
   * the kind of disagreement is a word and the only badge is the queue's own tier.
   */
  /**
   * A `cand_<16 hex>` id is where the record lives, not what the disagreement is about.
   * The daemon composes the subject's name and this page renders it; the id survives in
   * the route, which is where a researcher needs it.
   */
  it('calls a disputed candidate what the review queue calls it, never by its id', async () => {
    const { container } = renderView(<ConflictsPage />, { daemon: overviewWith([CONFLICT]) });

    await waitFor(() =>
      expect(screen.getByText('Provider against provider')).toBeInTheDocument(),
    );
    expect(screen.getByRole('link', { name: 'metric result · W0001' })).toBeInTheDocument();
    expect(container.textContent).not.toContain('cand_44c1f007fc0db0b2');
  });

  it('never dresses a queue state in a scientific status colour', async () => {
    const { container } = renderView(<ConflictsPage />, { daemon: overviewWith([CONFLICT]) });

    await waitFor(() => expect(screen.getByText(/Tier 2 — deep review/)).toBeInTheDocument());
    expect(container.querySelector('[data-authority]')).toBeNull();
    expect(container.querySelector('.rh-badge--contested')).toBeNull();
  });

  it('opens with the daemon’s sentence about what is in dispute', async () => {
    renderView(<ConflictsPage />, { daemon: overviewWith([CONFLICT]) });

    await waitFor(() =>
      expect(
        screen.getByText(
          '1 conflict is open. Every side is kept, and none of them is preferred until you decide.',
        ),
      ).toBeInTheDocument(),
    );
  });
});
