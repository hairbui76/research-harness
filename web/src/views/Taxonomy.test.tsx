/**
 * The taxonomy page in every state it can be in.
 *
 * The frame is the first assertion: loading, a refusal and a project with no approved terms
 * all keep the `h1` the shell's skip link lands on, and the empty state says what a taxonomy
 * is for rather than only that there is not one.
 *
 * The rest asserts what wave 3 changed. A taxonomy is approved rather than true (PRODUCT
 * §32), so the page opens with the terms no accepted Decision stands behind — the daemon's
 * judgement, its sentences — and the classification underneath is the tree the daemon
 * walked, not a `Parent` column a reader has to match ids across.
 */
import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { TaxonomyPage } from './Taxonomy';
import { ProjectPathProvider } from '../app/projectPaths';
import { expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const REFUSAL = 'the projection is being rebuilt';

const REPORT = {
  summary: '2 terms have no accepted Decision behind them, out of 3 terms in this project.',
  count: 3,
  needs_decision: {
    key: 'needs_decision',
    title: 'Waiting for a Decision',
    summary: '2 terms have no accepted Decision behind them',
    detail: 'A term becomes this project’s classification when a Decision approves it.',
    count: 2,
    route: '',
    items: [
      { id: 'traffic-shape:padded_fixed', label: 'padded_fixed · traffic-shape', detail: 'no Decision approves it yet', priority: 0, route: '' },
      { id: 'traffic-shape:unpadded', label: 'unpadded · traffic-shape', detail: 'D0004 approved it and has since been superseded', priority: 0, route: '' },
    ],
  },
  taxonomies: [
    {
      name: 'traffic-shape',
      summary: '3 terms, 2 of them without an accepted Decision',
      count: 3,
      approved: 1,
      terms: [
        { term: 'padded', parent: '', definition: 'a flow whose records are padded to a fixed size', decision: 'D0001', decision_status: 'accepted', approved: true, depth: 0 },
        { term: 'padded_fixed', parent: 'padded', definition: '', decision: '', decision_status: '', approved: false, depth: 1 },
        { term: 'unpadded', parent: '', definition: '', decision: 'D0004', decision_status: 'superseded', approved: false, depth: 0 },
      ],
    },
  ],
};

const NONE = {
  summary: 'This project has agreed no classification yet.',
  count: 0,
  needs_decision: {
    key: 'needs_decision',
    title: 'Waiting for a Decision',
    summary: '0 terms have no accepted Decision behind them',
    detail: 'A term becomes this project’s classification when a Decision approves it.',
    count: 0,
    route: '',
    items: [],
  },
  taxonomies: [],
};

function pendingDaemon(): FakeDaemon {
  return {
    fetch: (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

function taxonomyDaemon(report: unknown): FakeDaemon {
  return fakeDaemon({ gets: { '/taxonomy': report } });
}

describe('the taxonomy page', () => {
  it('keeps its heading and draws panels while the read is in flight', () => {
    const { container } = renderView(<TaxonomyPage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Taxonomy' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the taxonomies…');
    expect(container.querySelectorAll('.rh-web-skeleton-card').length).toBeGreaterThan(1);
  });

  it('keeps its heading when the read is refused, and offers the retry', async () => {
    renderView(<TaxonomyPage />, {
      daemon: {
        fetch: (async () => new Response(REFUSAL, { status: 503 })) as unknown as typeof fetch,
        calls: [],
        capabilityCalls: () => [],
      },
    });

    await waitFor(() => expect(screen.getByText(REFUSAL)).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Taxonomy' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('says what a taxonomy is and where one is proposed when there is none', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <TaxonomyPage />
      </ProjectPathProvider>,
      { daemon: taxonomyDaemon(NONE), route: '/projects/prj_abc/taxonomy', path: '/projects/prj_abc/taxonomy' },
    );

    await waitFor(() =>
      expect(screen.getByText('No taxonomy has been approved yet')).toBeInTheDocument(),
    );
    expect(screen.getByRole('heading', { level: 1, name: 'Taxonomy' })).toBeInTheDocument();
    expect(screen.getByText(/approved by a Decision/)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Open the conversation to propose a term' }),
    ).toHaveAttribute('href', '/projects/prj_abc/');
    await expectNoAxeViolations(container);
  });

  it('leads with the terms no accepted Decision stands behind, and why', async () => {
    const { container } = renderView(<TaxonomyPage />, { daemon: taxonomyDaemon(REPORT) });

    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 2, name: 'Waiting for a Decision' })).toBeInTheDocument(),
    );
    // The work is read before the classification it is about.
    const headings = screen.getAllByRole('heading', { level: 2 }).map((node) => node.textContent);
    expect(headings).toEqual(['Waiting for a Decision', 'traffic-shape']);
    expect(container.querySelector('.rh-full-page__description')).toHaveTextContent(REPORT.summary);
    expect(screen.getByText('padded_fixed · traffic-shape')).toBeInTheDocument();
    expect(screen.getByText('— no Decision approves it yet')).toBeInTheDocument();
    expect(
      screen.getByText('— D0004 approved it and has since been superseded'),
    ).toBeInTheDocument();
  });

  it('never puts a count on the page as a number on its own', async () => {
    const { container } = renderView(<TaxonomyPage />, { daemon: taxonomyDaemon(REPORT) });

    await waitFor(() => expect(screen.getByText('traffic-shape')).toBeInTheDocument());
    for (const node of Array.from(container.querySelectorAll('*'))) {
      if (node.children.length === 0) {
        expect((node.textContent ?? '').trim()).not.toMatch(/^\d+$/);
      }
    }
  });

  it('draws the classification as the tree the daemon walked', async () => {
    const { container } = renderView(<TaxonomyPage />, { daemon: taxonomyDaemon(REPORT) });

    await waitFor(() => expect(screen.getByText('padded')).toBeInTheDocument());
    const rows = Array.from(container.querySelectorAll('.rh-web-table tbody tr'));
    expect(rows.map((row) => row.querySelector('th')?.textContent)).toEqual([
      'padded',
      'padded_fixed',
      'unpadded',
    ]);
    // The depth replaces the `Parent` column: no id is matched against another cell.
    expect(rows[1]!.querySelector('th')).toHaveAttribute('data-depth', '1');
    expect(screen.queryByRole('columnheader', { name: 'Parent' })).toBeNull();
  });

  it('shows the Decision behind each term, and what it is when it is not accepted', async () => {
    const { container } = renderView(<TaxonomyPage />, { daemon: taxonomyDaemon(REPORT) });

    await waitFor(() => expect(screen.getByText('D0001')).toBeInTheDocument());
    const rows = Array.from(container.querySelectorAll('.rh-web-table tbody tr'));
    expect(within(rows[2] as HTMLElement).getByText('Superseded')).toBeInTheDocument();
    // An accepted Decision needs no badge: the term is approved and the row says so by id.
    expect(within(rows[0] as HTMLElement).queryByText('Accepted')).toBeNull();
    expect(within(rows[1] as HTMLElement).getByText('No Decision yet')).toBeInTheDocument();
    await expectNoAxeViolations(container);
  });

  it('teaches what a Decision does for a term when every term already has one', async () => {
    const clean = {
      ...REPORT,
      summary: 'Every one of this project’s 3 terms is approved by an accepted Decision.',
      needs_decision: { ...REPORT.needs_decision, count: 0, items: [] },
    };
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <TaxonomyPage />
      </ProjectPathProvider>,
      { daemon: taxonomyDaemon(clean), route: '/projects/prj_abc/taxonomy', path: '/projects/prj_abc/taxonomy' },
    );

    await waitFor(() =>
      expect(screen.getByText('Every term is approved by an accepted Decision')).toBeInTheDocument(),
    );
    expect(screen.getByText(REPORT.needs_decision.detail)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Open the conversation to propose a term' }),
    ).toHaveAttribute('href', '/projects/prj_abc/');
  });
});
