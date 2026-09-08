/**
 * The Evidence index: the page the accepted record is browsed from.
 *
 * The rules under test are the ones the record pages share. The lead is the daemon's and
 * is read before the size of the record; the questions are the daemon's and pressing one
 * sends a request rather than running a `filter()`; the find is the browser's and only ever
 * hides; every state keeps the frame; no number stands on its own. Where a link points is
 * asserted under both hosts, because an id becomes a link on nearly every cell of this page.
 */
import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EvidenceIndexPage } from './Evidence';
import { ProjectPathProvider } from '../app/projectPaths';
import { daemonReachability } from '../api/client';
import type { EvidenceSummary } from '../api/dto';
import { expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

/** One row, as `evidence.list` composes it, with one thing changed. */
function reading(id: string, overrides: Partial<EvidenceSummary> = {}): EvidenceSummary {
  return {
    id,
    work: 'W0001',
    work_title: 'Structured traffic representations',
    artifact: 'A0001-1',
    field: 'dataset',
    status: 'accepted',
    origin: 'source_observed',
    evidence_type: 'experimental_setup',
    strength: 'direct',
    review_tier: 1,
    verdict: 'supported',
    exact_text: 'We evaluate on CICIDS2017 and report macro F1.',
    qualification: null,
    stale: 'fresh',
    claims: [],
    accepted: '8 September 2026',
    accepted_at: '2026-09-08T09:15:00+00:00',
    ...overrides,
  };
}

/**
 * What the daemon says needs a researcher in this record.
 *
 * Shaped exactly as `evidence.list` answers it: the group's whole line is the daemon's
 * sentence, each item is one reading with the cockpit path the daemon chose for it, and
 * `more` is what the daemon's own cap left out. Nothing here is derived in the view — that
 * is the property the tests below are about.
 */
const NEEDS_A_RESEARCHER = [
  {
    kind: 'stale',
    label: '2 pieces of evidence went stale when their sources changed',
    count: 2,
    items: [
      { id: 'E0002', label: 'Dataset · A tokenizer comparison', detail: '', route: '/evidence/E0002' },
      { id: 'E0003', label: 'Metric result · An unregistered draft', detail: '', route: '' },
    ],
    more: '',
  },
  {
    kind: 'uncited',
    label: '4 pieces of evidence are cited by no claim',
    count: 4,
    items: [
      { id: 'E0004', label: 'Dataset · Encrypted flow taxonomies', detail: '', route: '/evidence/E0004' },
    ],
    more: '3 more are in the list below.',
  },
];

const QUESTIONS = [
  {
    kind: 'stale',
    label: 'Went stale',
    count: 2,
    summary: '2 of 5 pieces of evidence went stale when their sources changed.',
  },
  {
    kind: 'uncited',
    label: 'Cited by no claim',
    count: 4,
    summary: '4 of 5 pieces of evidence are cited by no claim.',
  },
];

function rows(count: number): EvidenceSummary[] {
  return Array.from({ length: count }, (_unused, index) =>
    reading(`E${String(index + 1).padStart(4, '0')}`, {
      exact_text: `The span this reading was accepted from, number ${index + 1}.`,
    }),
  );
}

/** A record with a lead, questions and rows: the ordinary state of this page. */
function recordDaemon(): FakeDaemon {
  return fakeDaemon({
    capabilities: {
      'evidence.list': {
        count: 5,
        total: 5,
        question: '',
        evidence: rows(5),
        attention: NEEDS_A_RESEARCHER,
        questions: QUESTIONS,
      },
    },
  });
}

/**
 * A daemon that answers each question with a different list.
 *
 * That is the property the narrowing tests are about: the page has to ask rather than
 * filter, so a fake whose answers cannot be derived from one another catches a `filter()`.
 */
function askableDaemon(): FakeDaemon {
  const all = rows(5);
  const byQuestion: Record<string, EvidenceSummary[]> = {
    '': all,
    stale: all.slice(0, 2),
    uncited: all.slice(1, 5),
  };
  const calls: { method: string; path: string; body: unknown }[] = [];
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://daemon.test');
    const body = init?.body ? (JSON.parse(String(init.body)) as { question?: string }) : null;
    calls.push({ method: init?.method ?? 'GET', path: url.pathname, body });
    if (url.pathname !== '/capabilities/evidence.list') {
      return new Response('not found', { status: 404 });
    }
    const question = body?.question ?? '';
    const evidence = byQuestion[question] ?? [];
    return new Response(
      JSON.stringify({
        capability: 'evidence.list',
        ok: true,
        result: {
          count: evidence.length,
          total: all.length,
          question,
          evidence,
          attention: NEEDS_A_RESEARCHER,
          questions: QUESTIONS,
        },
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  };
  return {
    fetch: fetchImpl as unknown as typeof fetch,
    calls: calls as never,
    capabilityCalls: () =>
      calls
        .filter((call) => call.method === 'POST' && call.path.startsWith('/capabilities/'))
        .map((call) => ({ name: call.path.slice('/capabilities/'.length), request: call.body })),
  } as FakeDaemon;
}

/**
 * Every number on the page that nothing labels.
 *
 * A `<dd>` answers the `<dt>` beside it and a cell answers its column header, so neither is
 * a number standing on its own. What the rule forbids is the other thing: a count rendered
 * as a figure with nothing around it, which is the stat tile the Overview left behind.
 */
function bareNumbers(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('*'))
    .filter(
      (node) =>
        node.children.length === 0 &&
        !['DD', 'TD', 'TH'].includes(node.tagName) &&
        /^\d+([.,]\d+)?%?$/.test((node.textContent ?? '').trim()),
    )
    .map((node) => node.outerHTML);
}

/** The live line that counts the record; the page has more than one polite region. */
function recordCount(): HTMLElement {
  return within(
    screen.getByRole('region', { name: 'Everything this project has accepted' }),
  ).getByRole('status');
}

describe('what needs a researcher in the accepted record', () => {
  it('names the work before it says how much the record holds', async () => {
    const { container } = renderView(<EvidenceIndexPage />, {
      daemon: recordDaemon(),
      route: '/evidence',
      path: '/evidence',
    });

    await waitFor(() =>
      expect(
        screen.getByText('2 pieces of evidence went stale when their sources changed'),
      ).toBeInTheDocument(),
    );
    const named = screen.getByText(
      '2 pieces of evidence went stale when their sources changed',
    );
    expect(
      named.compareDocumentPosition(recordCount()) & Node.DOCUMENT_POSITION_FOLLOWING,
      'the size of the record is read after what needs a researcher',
    ).toBeTruthy();
    // The daemon's order, kept: decay before what landed nowhere.
    expect(
      named.compareDocumentPosition(
        screen.getByText('4 pieces of evidence are cited by no claim'),
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(recordCount()).toHaveTextContent('5 pieces of evidence.');
    expect(bareNumbers(container), 'no number stands on its own').toEqual([]);
  });

  it('points a named reading at itself, and one the daemon gave no page at nothing', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <EvidenceIndexPage />
      </ProjectPathProvider>,
      {
        daemon: recordDaemon(),
        route: '/projects/prj_abc/evidence',
        path: '/projects/prj_abc/evidence',
      },
    );

    await waitFor(() =>
      expect(screen.getByText('4 pieces of evidence are cited by no claim')).toBeInTheDocument(),
    );
    expect(
      screen.getByRole('link', { name: 'Dataset · A tokenizer comparison' }),
    ).toHaveAttribute('href', '/projects/prj_abc/evidence/E0002');
    // No route, so no link: the reader is already on the index, and a link to the page
    // under their feet is not a next step.
    expect(
      screen.queryByRole('link', { name: /An unregistered draft/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText('3 more are in the list below.')).toBeInTheDocument();
  });

  it('teaches what would put a reading here when the daemon names none', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <EvidenceIndexPage />
      </ProjectPathProvider>,
      {
        daemon: fakeDaemon({
          capabilities: {
            'evidence.list': {
              count: 1,
              total: 1,
              question: '',
              evidence: [reading('E0001')],
              attention: [],
              questions: [],
            },
          },
        }),
        route: '/projects/prj_abc/evidence',
        path: '/projects/prj_abc/evidence',
      },
    );

    await waitFor(() =>
      expect(screen.getByText('Nothing in this record needs a researcher')).toBeInTheDocument(),
    );
    // The page never works a group out for itself: the daemon named none, so there is none.
    expect(screen.queryByText(/went stale/)).not.toBeInTheDocument();
    expect(screen.getByText(/once a later reading has superseded it/)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Open the claims this evidence carries' }),
    ).toHaveAttribute('href', '/projects/prj_abc/claims');
    await expectNoAxeViolations(container);
  });

  it('keeps naming it while the daemon is silent, because it was true when it spoke', async () => {
    renderView(<EvidenceIndexPage />, {
      daemon: recordDaemon(),
      route: '/evidence',
      path: '/evidence',
    });

    await waitFor(() =>
      expect(
        screen.getByText('2 pieces of evidence went stale when their sources changed'),
      ).toBeInTheDocument(),
    );
    daemonReachability.unanswered('/capabilities/evidence.list', 'TypeError: Failed to fetch');
    await waitFor(() => expect(recordCount()).toHaveTextContent(/has not answered since/));
    expect(
      screen.getByText('2 pieces of evidence went stale when their sources changed'),
    ).toBeInTheDocument();
  });
});

describe('one reading in the record', () => {
  it('reads across the columns the questions ask, in the product’s own words', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <EvidenceIndexPage />
      </ProjectPathProvider>,
      {
        daemon: fakeDaemon({
          capabilities: {
            'evidence.list': {
              count: 1,
              total: 1,
              question: '',
              evidence: [
                reading('E0001', {
                  strength: 'derived',
                  origin: 'researcher_inferred',
                  claims: [{ id: 'C0001', title: 'Byte-level tokenization improves recall' }],
                }),
              ],
              attention: [],
              questions: [],
            },
          },
        }),
        route: '/projects/prj_abc/evidence',
        path: '/projects/prj_abc/evidence',
      },
    );

    await waitFor(() =>
      expect(
        screen.getByText('We evaluate on CICIDS2017 and report macro F1.'),
      ).toBeInTheDocument(),
    );
    // The name opens the reading at its source; the id beside it opens the same page.
    expect(
      screen.getByRole('link', { name: 'Dataset · Structured traffic representations' }),
    ).toHaveAttribute('href', '/projects/prj_abc/evidence/E0001');
    // The vocabularies are printed as the product says them, never as the wire spells them.
    expect(screen.getByText('Experimental setup')).toBeInTheDocument();
    expect(screen.getByText('Derived')).toBeInTheDocument();
    expect(screen.getByText('Researcher inferred')).toBeInTheDocument();
    expect(screen.queryByText('researcher_inferred')).not.toBeInTheDocument();
    // What rests on it, by the statement the claim is read as rather than by a count.
    expect(
      screen.getByRole('link', { name: 'Byte-level tokenization improves recall' }),
    ).toHaveAttribute('href', '/projects/prj_abc/claims/C0001');
    // Every row here is accepted state, so the badge stays off a plainly accepted reading.
    expect(screen.queryByText('Accepted', { selector: '.rh-badge' })).not.toBeInTheDocument();
  });

  it('badges a reading whose source moved under it, and nothing else', async () => {
    const { container } = renderView(<EvidenceIndexPage />, {
      daemon: fakeDaemon({
        capabilities: {
          'evidence.list': {
            count: 2,
            total: 2,
            question: '',
            evidence: [
              reading('E0001'),
              reading('E0002', { stale: 'stale', status: 'stale' }),
            ],
            attention: [],
            questions: [],
          },
        },
      }),
      route: '/evidence',
      path: '/evidence',
    });

    await waitFor(() => expect(recordCount()).toHaveTextContent('2 pieces of evidence.'));
    // One badge on the page: the reading that has something to say beyond "accepted".
    expect(screen.getAllByText('Stale')).toHaveLength(1);
    expect(bareNumbers(container), 'no number stands on its own').toEqual([]);
    await expectNoAxeViolations(container);
  });

  it('says nothing rests on a reading in words rather than as a zero', async () => {
    const { container } = renderView(<EvidenceIndexPage />, {
      daemon: recordDaemon(),
      route: '/evidence',
      path: '/evidence',
    });

    await waitFor(() => expect(recordCount()).toHaveTextContent('5 pieces of evidence.'));
    expect(screen.getAllByText('Nothing yet').length).toBe(5);
    expect(bareNumbers(container), 'no number stands on its own').toEqual([]);
  });
});

describe('the questions the accepted record can be asked', () => {
  it('offers what the daemon says this record answers, and how many answer each', async () => {
    const { container } = renderView(<EvidenceIndexPage />, {
      daemon: askableDaemon(),
      route: '/evidence',
      path: '/evidence',
    });

    await waitFor(() => expect(recordCount()).toHaveTextContent('5 pieces of evidence.'));
    const bar = screen.getByRole('group', { name: 'Ask the record a question' });
    expect(
      within(bar).getByRole('button', { name: 'Everything accepted (5)' }),
    ).toHaveAttribute('aria-pressed', 'true');
    expect(within(bar).getByRole('button', { name: 'Went stale (2)' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    expect(within(bar).getByRole('button', { name: 'Cited by no claim (4)' })).toBeInTheDocument();
    expect(bareNumbers(container), 'no number stands on its own').toEqual([]);
    await expectNoAxeViolations(container);
  });

  it('asks the daemon the question instead of filtering the list itself', async () => {
    const user = userEvent.setup();
    const daemon = askableDaemon();
    renderView(<EvidenceIndexPage />, { daemon, route: '/evidence', path: '/evidence' });

    await waitFor(() => expect(recordCount()).toHaveTextContent('5 pieces of evidence.'));
    await user.click(screen.getByRole('button', { name: 'Went stale (2)' }));

    await waitFor(() =>
      expect(recordCount()).toHaveTextContent(
        '2 of 5 pieces of evidence went stale when their sources changed.',
      ),
    );
    expect(daemon.capabilityCalls()).toContainEqual({
      name: 'evidence.list',
      request: { question: 'stale' },
    });
    const list = screen.getByRole('list', { name: 'Accepted evidence' });
    expect(within(list).getAllByRole('listitem').length).toBe(2);

    // The lead is about the record, so it does not change when the list under it is
    // narrowed; neither do the counts on the controls, which are over the whole of it.
    expect(screen.getByText('4 pieces of evidence are cited by no claim')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cited by no claim (4)' })).toBeInTheDocument();

    // Pressing the chosen question again is the way back.
    await user.click(screen.getByRole('button', { name: 'Went stale (2)' }));
    await waitFor(() => expect(recordCount()).toHaveTextContent('5 pieces of evidence.'));
  });

  it('finds inside a question, and says what it is finding inside', async () => {
    const user = userEvent.setup();
    renderView(<EvidenceIndexPage />, {
      daemon: askableDaemon(),
      route: '/evidence',
      path: '/evidence',
    });

    await waitFor(() => expect(recordCount()).toHaveTextContent('5 pieces of evidence.'));
    await user.click(screen.getByRole('button', { name: 'Cited by no claim (4)' }));
    await waitFor(() =>
      expect(recordCount()).toHaveTextContent(
        '4 of 5 pieces of evidence are cited by no claim.',
      ),
    );

    // The find is the one question about the text on screen rather than about the science,
    // so it stays in the browser — and it says which set it is narrowing.
    await user.type(screen.getByRole('searchbox'), 'number 3');
    await waitFor(() =>
      expect(recordCount()).toHaveTextContent(
        '4 of 5 pieces of evidence are cited by no claim. Showing 1 of them.',
      ),
    );
    expect(
      screen.getByText('The span this reading was accepted from, number 3.'),
    ).toBeInTheDocument();
  });

  it('offers the way back when a find hides everything', async () => {
    const user = userEvent.setup();
    renderView(<EvidenceIndexPage />, {
      daemon: recordDaemon(),
      route: '/evidence',
      path: '/evidence',
    });

    await waitFor(() => expect(recordCount()).toHaveTextContent('5 pieces of evidence.'));
    await user.type(screen.getByRole('searchbox'), 'no reading says this');
    await waitFor(() => expect(screen.getByText('Nothing matches this find')).toBeInTheDocument());
    expect(screen.getByText(/The find only hides/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear the find' }));
    await waitFor(() => expect(recordCount()).toHaveTextContent('5 pieces of evidence.'));
  });
});

describe('a project with nothing accepted in it', () => {
  it('keeps the frame and offers the one way a reading is created', async () => {
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <EvidenceIndexPage />
      </ProjectPathProvider>,
      {
        daemon: fakeDaemon({
          capabilities: {
            'evidence.list': {
              count: 0,
              total: 0,
              question: '',
              evidence: [],
              attention: [],
              questions: [],
            },
          },
        }),
        route: '/projects/prj_abc/evidence',
        path: '/projects/prj_abc/evidence',
      },
    );

    await waitFor(() =>
      expect(screen.getByText('Nothing has been accepted in this project yet')).toBeInTheDocument(),
    );
    expect(screen.getByRole('heading', { level: 1, name: 'Evidence' })).toBeInTheDocument();
    expect(screen.getByText(/only a researcher's decision creates it/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open the review inbox' })).toHaveAttribute(
      'href',
      '/projects/prj_abc/review',
    );
    // Nothing to find in, so the find is not offered at all.
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
    await expectNoAxeViolations(container);
  });

  it('keeps the frame while the daemon is still answering', () => {
    renderView(<EvidenceIndexPage />, {
      daemon: {
        fetch: (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
        calls: [],
        capabilityCalls: () => [],
      } as FakeDaemon,
      route: '/evidence',
      path: '/evidence',
    });

    expect(screen.getByRole('heading', { level: 1, name: 'Evidence' })).toBeInTheDocument();
    expect(screen.getByText('Reading the accepted evidence…')).toBeInTheDocument();
  });

  it('keeps the frame when the daemon refuses, and offers the read again', async () => {
    renderView(<EvidenceIndexPage />, {
      daemon: fakeDaemon({
        capabilities: {
          'evidence.list': {
            capability: 'evidence.list',
            ok: false,
            error: {
              code: 'workspace_locked',
              message: 'the workspace lock is held by another process',
            },
          },
        },
      }),
      route: '/evidence',
      path: '/evidence',
    });

    await waitFor(() =>
      expect(
        screen.getByText('the workspace lock is held by another process'),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole('heading', { level: 1, name: 'Evidence' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});
