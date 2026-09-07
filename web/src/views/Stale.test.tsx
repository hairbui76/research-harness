/**
 * The stale list in every state it can be in.
 *
 * A page that returns its loading, empty or failure state instead of itself has no `h1`,
 * so the shell's skip link lands nowhere and a researcher cannot tell which page failed.
 * Each test below asserts the frame first and the state second.
 *
 * The rest of the file asserts the thing this page exists to prove after wave 3: the
 * groups, their order, their sentences and the reason under each object are the daemon's,
 * and this page renders them rather than deriving any of them from a priority integer.
 */
import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { StalePage } from './Stale';
import { ProjectPathProvider } from '../app/projectPaths';
import { expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const REFUSAL = 'the projection is being rebuilt';

/** `GET /stale` over a project where a Decision revision moved two things underneath. */
const REPORT = {
  summary: '2 objects went stale because something they rest on changed.',
  count: 2,
  reported: 2,
  more: '',
  groups: [
    {
      key: 'claims',
      title: 'Accepted claims',
      summary: '1 claim has gone stale',
      detail: 'A Claim was audited against evidence that has since changed.',
      count: 1,
      route: '/claims',
      items: [
        {
          id: 'C0001',
          label: 'C0001',
          detail: "the anchor is stale: origin 'author_interpreted'",
          priority: 4,
          route: '/claims/C0001',
        },
      ],
    },
    {
      key: 'index',
      title: 'Index entries',
      summary: '1 index entry has gone stale',
      detail: 'A projection entry is behind the canonical files it is derived from.',
      count: 1,
      route: '',
      items: [
        { id: 'taxonomy:shape', label: 'taxonomy:shape', detail: 'upstream D0001 changed', priority: 1, route: '' },
      ],
    },
  ],
};

const NOTHING = { summary: 'Nothing in this project has gone out of date.', count: 0, reported: 0, more: '', groups: [] };

/** A daemon that has not answered yet, so the page stays in its loading state. */
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

function staleDaemon(report: unknown): FakeDaemon {
  return fakeDaemon({ gets: { '/stale': report } });
}

describe('the stale page', () => {
  it('keeps its heading and draws the groups that are coming while the read is in flight', () => {
    const { container } = renderView(<StalePage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Stale objects' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the stale set…');
    expect(container.querySelectorAll('.rh-web-skeleton-card').length).toBeGreaterThan(1);
    // No size is claimed before the daemon has stated one.
    expect(container.querySelector('.rh-full-page__description')?.textContent).not.toMatch(/\d/);
  });

  it('keeps its heading when the read is refused, and offers the retry', async () => {
    renderView(<StalePage />, { daemon: refusingDaemon() });

    await waitFor(() => expect(screen.getByText(REFUSAL)).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Stale objects' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('teaches what staleness is in the words the Overview uses, and points at the corpus', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <StalePage />
      </ProjectPathProvider>,
      { daemon: staleDaemon(NOTHING), route: '/projects/prj_abc/stale', path: '/projects/prj_abc/stale' },
    );

    await waitFor(() => expect(screen.getByText('Nothing is stale')).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Stale objects' })).toBeInTheDocument();
    // The Overview's "Gone stale" group teaches with this sentence; so does this page.
    expect(screen.getByText(/re-anchored silently/)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Open the corpus this project rests on' }),
    ).toHaveAttribute('href', '/projects/prj_abc/corpus');
    await expectNoAxeViolations(container);
  });

  it('leads with the daemon’s sentence rather than a count at heading size', async () => {
    const { container } = renderView(<StalePage />, { daemon: staleDaemon(REPORT) });

    await waitFor(() => expect(screen.getByText('Accepted claims')).toBeInTheDocument());
    expect(container.querySelector('.rh-full-page__description')).toHaveTextContent(REPORT.summary);
    for (const node of Array.from(container.querySelectorAll('*'))) {
      if (node.children.length === 0) {
        expect((node.textContent ?? '').trim()).not.toMatch(/^\d+$/);
      }
    }
  });

  it('groups decay by the scientific impact the daemon reported, in its order', async () => {
    renderView(<StalePage />, { daemon: staleDaemon(REPORT) });

    await waitFor(() => expect(screen.getByText('Accepted claims')).toBeInTheDocument());
    const headings = screen.getAllByRole('heading', { level: 2 }).map((node) => node.textContent);
    expect(headings).toEqual(['Accepted claims', 'Index entries']);
    // The tier says what going stale there costs, so the order is readable rather than arbitrary.
    expect(screen.getByText(/audited against evidence that has since changed/)).toBeInTheDocument();
  });

  it('states a group’s size inside a link when the objects have a page of their own', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <StalePage />
      </ProjectPathProvider>,
      { daemon: staleDaemon(REPORT), route: '/projects/prj_abc/stale', path: '/projects/prj_abc/stale' },
    );

    await waitFor(() => expect(screen.getByText('Accepted claims')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: '1 claim has gone stale' })).toHaveAttribute(
      'href',
      '/projects/prj_abc/claims',
    );
    // The index tier has no page of its own, so its line is a sentence and not a link.
    expect(screen.getByText('1 index entry has gone stale').closest('a')).toBeNull();
    await expectNoAxeViolations(container);
  });

  it('links an object to itself, and reads the daemon’s vocabulary out of its reason', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <StalePage />
      </ProjectPathProvider>,
      { daemon: staleDaemon(REPORT), route: '/projects/prj_abc/stale', path: '/projects/prj_abc/stale' },
    );

    await waitFor(() =>
      expect(screen.getByText("— the anchor is stale: origin 'author interpreted'")).toBeInTheDocument(),
    );
    expect(screen.getByRole('link', { name: 'C0001' })).toHaveAttribute(
      'href',
      '/projects/prj_abc/claims/C0001',
    );
    // An object the daemon gave no route to is text, not a second link to its own group.
    const entry = screen.getByText('taxonomy:shape');
    expect(entry.closest('a')).toBeNull();
    expect(within(entry.closest('li')!).getByText(/upstream D0001 changed/)).toBeInTheDocument();
  });

  it('says in the daemon’s words what a cap left out', async () => {
    const more = '3 further stale marks have been recorded beyond the ones listed here.';
    renderView(<StalePage />, { daemon: staleDaemon({ ...REPORT, more }) });

    await waitFor(() => expect(screen.getByText(more)).toBeInTheDocument());
  });
});
