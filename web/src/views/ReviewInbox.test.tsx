/**
 * Task 11.2 and the throughput work the critique asked for: the inbox groups by the reason
 * the daemon gave, in the daemon's order, and lets a researcher get through it.
 *
 * The fixture is a real `review.inbox` response. What is asserted is that the view keeps
 * Product 24.2's order, shows the reason each item is waiting, and reports no confidence
 * number anywhere — the queue is about attention, not about how sure a model was (§43) —
 * and that searching and filtering only ever *hide*, because the ranking they would
 * otherwise disturb is the daemon's scientific judgement (Product 5 P8).
 *
 * The batch is the daemon's judgement end to end: the cockpit names no candidate, previews
 * with `dry_run`, restates what the write will do, and renders the answer — including a
 * refusal under the default strict policy, in the daemon's own words.
 */
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import type { ReviewItem } from '../api/dto';
import {
  CATEGORY_ORDER,
  ReviewInboxPage,
  groupByCategory,
  inboxGroups,
  matchesFilters,
} from './ReviewInbox';
import { CommandsProvider } from '../app/commands';
import { ProjectPathProvider } from '../app/projectPaths';
import { FIXTURES, expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const QUEUE = FIXTURES.reviewInbox as unknown as { items: ReviewItem[]; count: number };
const NO_FILTERS = { text: '', category: '', verdict: '' };

/** The inbox inside the shortcut layer, which is where the shell mounts it. */
function withShell(ui: ReactElement): ReactElement {
  return <CommandsProvider>{ui}</CommandsProvider>;
}

function renderInbox(daemon: FakeDaemon, token: string | null = 'local-token') {
  return renderView(withShell(<ReviewInboxPage />), {
    daemon,
    token,
    route: '/review',
    path: '/review',
  });
}

function queueDaemon(overrides: Record<string, unknown> = {}) {
  return fakeDaemon({ capabilities: { 'review.inbox': QUEUE, ...overrides } });
}

describe('grouping', () => {
  it('keeps the queue order of Product 24.2 and drops the empty groups', () => {
    const grouped = groupByCategory(QUEUE.items);

    expect(grouped.map(([category]) => category)).toEqual(['high_risk', 'ambiguous', 'routine']);
    const order = grouped.map(([category]) => CATEGORY_ORDER.indexOf(category as never));
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });

  it('never reorders within a group: the server already ranked them', () => {
    const items = QUEUE.items.map((item) => ({ ...item, category: 'routine' as const }));
    const grouped = groupByCategory(items);
    const group = grouped[0]![1];
    expect(group.map((item) => item.candidate_id)).toEqual(items.map((item) => item.candidate_id));
  });
});

describe('search and filter', () => {
  it('searches the field, the work, the quoted span and the reasons', () => {
    const metric = QUEUE.items.find((item) => item.field === 'metric_result')!;

    expect(matchesFilters(metric, { ...NO_FILTERS, text: 'metric_res' })).toBe(true);
    expect(matchesFilters(metric, { ...NO_FILTERS, text: 'W0001' })).toBe(true);
    expect(matchesFilters(metric, { ...NO_FILTERS, text: '94.32' })).toBe(true);
    expect(matchesFilters(metric, { ...NO_FILTERS, text: 'numeric evidence' })).toBe(true);
    expect(matchesFilters(metric, { ...NO_FILTERS, text: 'transformer' })).toBe(false);
  });

  it('filters by the daemon’s own category and verdict words', () => {
    const metric = QUEUE.items.find((item) => item.field === 'metric_result')!;

    expect(matchesFilters(metric, { ...NO_FILTERS, category: 'high_risk' })).toBe(true);
    expect(matchesFilters(metric, { ...NO_FILTERS, category: 'routine' })).toBe(false);
    expect(matchesFilters(metric, { ...NO_FILTERS, verdict: 'supported' })).toBe(true);
    expect(matchesFilters(metric, { ...NO_FILTERS, verdict: 'partially_supported' })).toBe(false);
  });

  it('hides without reordering: a filter removes groups, it never moves one', () => {
    const groups = inboxGroups(QUEUE.items, { ...NO_FILTERS, verdict: 'supported' });

    expect(groups.map(([category]) => category)).toEqual(['high_risk', 'routine']);
  });

  it('leaves a filtered group in the order the daemon ranked it', () => {
    const items: ReviewItem[] = [
      { ...QUEUE.items[0]!, candidate_id: 'c1', category: 'routine', tier: 2, work: 'W0009' },
      { ...QUEUE.items[0]!, candidate_id: 'c2', category: 'conflict', tier: 1, work: 'W0001' },
      { ...QUEUE.items[0]!, candidate_id: 'c3', category: 'routine', tier: 1, work: 'W0002' },
    ];

    const groups = inboxGroups(items, NO_FILTERS);
    expect(groups.map(([category]) => category)).toEqual(['conflict', 'routine']);
    // Neither the tier nor the work moves c3 in front of c1: the daemon sent them this way.
    expect(groups[1]![1].map((item) => item.candidate_id)).toEqual(['c1', 'c3']);
  });

  it('offers no control that could re-order a group', async () => {
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    expect(screen.queryByRole('combobox', { name: /Order inside each group/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'By tier' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'By work' })).not.toBeInTheDocument();
  });
});

describe('the review inbox view', () => {
  it('renders each group with its count, the reasons, and the quoted span', async () => {
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    expect(screen.getByText('High-risk scientific claims (1)')).toBeInTheDocument();
    expect(screen.getByText('Ambiguous extractions (1)')).toBeInTheDocument();
    expect(screen.getByText('Routine verified candidates (1)')).toBeInTheDocument();
    expect(screen.getByText('metric_result')).toBeInTheDocument();
    expect(screen.getByText('94.32')).toBeInTheDocument();
  });

  it('keeps the page frame while it is still reading the queue', async () => {
    renderInbox(queueDaemon());

    expect(screen.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeInTheDocument();
    expect(screen.getByText(/Reading the review queue/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
  });

  it('keeps the page frame when the daemon refuses, and offers the read again', async () => {
    const daemon = fakeDaemon({ capabilities: {} });
    renderInbox(daemon);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Try again' })).toBeEnabled());
    expect(screen.getByRole('heading', { name: 'Review inbox', level: 1 })).toBeInTheDocument();
  });

  it('describes the queue in the product’s own words, citing no document', async () => {
    const { container } = renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    expect(container.textContent).toContain('Conflicts first');
    expect(container.textContent).not.toMatch(/PRODUCT|§/);
  });

  it('links every item to its own source-beside-decision screen', async () => {
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('metric_result')).toBeInTheDocument());
    const first = QUEUE.items[0]!;
    const link = screen.getByText(first.field).closest('a');
    expect(link).toHaveAttribute('href', `/review/${first.candidate_id}`);
  });

  it('shows no model-confidence number, because the daemon reports none', async () => {
    const { container } = renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('metric_result')).toBeInTheDocument());
    expect(container.textContent?.toLowerCase()).not.toContain('confidence');
  });

  it('says the queue is empty and offers somewhere to go next', async () => {
    const daemon = fakeDaemon({
      capabilities: { 'review.inbox': { count: 0, counts: {}, items: [] } },
    });

    renderInbox(daemon);

    await waitFor(() =>
      expect(screen.getByText('Nothing is waiting for review')).toBeInTheDocument(),
    );
    // The shared contract every other research page uses: the fact as the title, what the
    // page is for as the description, one real next step as the action.
    expect(screen.getByText(/none of them is accepted state until it is decided here/)).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Open the corpus to interrogate a work' }),
    ).toHaveAttribute('href', '/corpus');
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('metric_result')).toBeInTheDocument());
    await expectNoAxeViolations(container);
  });
});

describe('narrowing the queue on screen', () => {
  it('counts what is showing against what is waiting, and hides the rest', async () => {
    const user = userEvent.setup();
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    await user.type(screen.getByRole('textbox', { name: /Filter/ }), 'transformer');

    await waitFor(() => expect(screen.getByText(/Showing 1 of 3/)).toBeInTheDocument());
    expect(screen.queryByText('metric_result')).not.toBeInTheDocument();
    expect(screen.getByText('method_summary')).toBeInTheDocument();
    expect(screen.queryByText(/High-risk scientific claims \(/)).not.toBeInTheDocument();
  });

  it('tells a filter that matches nothing apart from an empty inbox, and clears it', async () => {
    const user = userEvent.setup();
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    await user.type(screen.getByRole('textbox', { name: /Filter/ }), 'no such span');

    expect(screen.getByText('No candidate matches these filters')).toBeInTheDocument();
    expect(screen.getByText(/Nothing has left the queue/)).toBeInTheDocument();
    expect(screen.queryByText('Nothing is waiting for review')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Clear the filters' }));
    await waitFor(() => expect(screen.getByText('metric_result')).toBeInTheDocument());
  });

  it('filters by category without moving the groups it keeps', async () => {
    const user = userEvent.setup();
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    await user.selectOptions(screen.getByRole('combobox', { name: /Category/ }), 'routine');

    await waitFor(() =>
      expect(screen.getByText('Routine verified candidates (1)')).toBeInTheDocument(),
    );
    expect(screen.queryByText(/High-risk scientific claims \(/)).not.toBeInTheDocument();
  });
});

describe('the keyboard', () => {
  it('moves down and up the rows with j and k, so Enter opens the one in focus', async () => {
    const user = userEvent.setup();
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('metric_result')).toBeInTheDocument());
    const rows = screen.getAllByRole('link', { name: /·/ });

    await user.keyboard('j');
    expect(rows[0]).toHaveFocus();
    await user.keyboard('j');
    expect(rows[1]).toHaveFocus();
    await user.keyboard('k');
    expect(rows[0]).toHaveFocus();
  });

  it('does not move a row while the researcher is typing in the filter', async () => {
    const user = userEvent.setup();
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('metric_result')).toBeInTheDocument());
    const filter = screen.getByRole('textbox', { name: /Filter/ });
    await user.click(filter);
    await user.keyboard('jk');

    expect(filter).toHaveFocus();
    expect(filter).toHaveValue('jk');
  });
});

describe('the policy batch of Product 24.4', () => {
  const DRY_RUN = {
    dry_run: true,
    accepted: ['cand_4590b9b1f474d343'],
    skipped: {
      cand_44c1f007fc0db0b2: 'tier 2 needs deep review; numeric evidence is never low risk',
      cand_b09aa84fc5dee7c0: 'verdict is partially_supported, not supported',
    },
    mutations: [],
  };

  it('sits below the queue, so the highest-priority group is what opens the page', async () => {
    renderInbox(queueDaemon({ 'review.accept_batch': DRY_RUN }));

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    const panels = screen.getAllByRole('heading', { level: 2 }).map((node) => node.textContent);

    expect(panels).toContain('Batch accept');
    expect(panels.indexOf('Batch accept')).toBeGreaterThan(
      panels.indexOf('High-risk scientific claims (1)'),
    );
  });

  it('previews with a dry run, and writes nothing until the restatement is answered', async () => {
    const user = userEvent.setup();
    const daemon = queueDaemon({ 'review.accept_batch': DRY_RUN });
    renderInbox(daemon);

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Accept the routine candidates/ }));

    await waitFor(() =>
      expect(
        screen.getByText(/1 routine candidate meets the batch conditions/),
      ).toBeInTheDocument(),
    );
    expect(daemon.capabilityCalls().filter((c) => c.name === 'review.accept_batch')).toEqual([
      { name: 'review.accept_batch', request: { dry_run: true } },
    ]);
    expect(screen.getByText(/becomes accepted Evidence, verified by you/)).toBeInTheDocument();
  });

  it('names every candidate the daemon would skip, with the daemon’s own reason', async () => {
    const user = userEvent.setup();
    renderInbox(queueDaemon({ 'review.accept_batch': DRY_RUN }));

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Accept the routine candidates/ }));

    await waitFor(() =>
      expect(screen.getByText(/tier 2 needs deep review/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/verdict is partially_supported, not supported/)).toBeInTheDocument();
  });

  it('accepts only after the second press, and reports what was written', async () => {
    const user = userEvent.setup();
    const daemon = fakeDaemon({
      capabilities: { 'review.inbox': QUEUE, 'review.accept_batch': DRY_RUN },
    });
    renderInbox(daemon);

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Accept the routine candidates/ }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Accept 1 candidate' })).toBeEnabled(),
    );

    // The second press is the one that writes: only now does `dry_run` go false.
    await user.click(screen.getByRole('button', { name: 'Accept 1 candidate' }));

    await waitFor(() => {
      const batch = daemon.capabilityCalls().filter((call) => call.name === 'review.accept_batch');
      expect(batch.map((call) => call.request)).toEqual([{ dry_run: true }, { dry_run: false }]);
    });
  });

  it('keeps naming what it wrote after the queue it emptied comes back empty', async () => {
    const user = userEvent.setup();
    const base = fakeDaemon({
      capabilities: { 'review.inbox': QUEUE, 'review.accept_batch': DRY_RUN },
    });
    // The second read answers empty, the way the daemon does once a batch has taken
    // everything that qualified — which is exactly when the report must not vanish.
    let reads = 0;
    const draining = (async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/capabilities/review.inbox') && reads++ > 0) {
        return new Response(
          JSON.stringify({
            capability: 'review.inbox',
            ok: true,
            result: { count: 0, counts: {}, items: [] },
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        );
      }
      return base.fetch(input, init);
    }) as typeof fetch;

    renderInbox({ ...base, fetch: draining });

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Accept the routine candidates/ }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Accept 1 candidate' })).toBeEnabled(),
    );
    await user.click(screen.getByRole('button', { name: 'Accept 1 candidate' }));

    await waitFor(() =>
      expect(screen.getByText('1 candidate is now accepted Evidence.')).toBeInTheDocument(),
    );
    expect(
      screen.getByRole('list', { name: 'Candidates that meet the batch conditions' }),
    ).toHaveTextContent('dataset · W0001');
    expect(screen.getByText('Nothing is waiting for review')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Accept the routine candidates/ }),
    ).not.toBeInTheDocument();
  });

  it('offers the batch per work as well as for the whole queue, because that is all it takes', async () => {
    const user = userEvent.setup();
    const daemon = queueDaemon({ 'review.accept_batch': DRY_RUN });
    renderInbox(daemon);

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    await user.selectOptions(screen.getByRole('combobox', { name: /Batch scope/ }), 'W0001');
    await user.click(screen.getByRole('button', { name: /Accept the routine candidates/ }));

    await waitFor(() =>
      expect(daemon.capabilityCalls().filter((c) => c.name === 'review.accept_batch')).toEqual([
        { name: 'review.accept_batch', request: { dry_run: true, work: 'W0001' } },
      ]),
    );
  });

  it('renders a refusal under strict review in the daemon’s own sentence', async () => {
    const user = userEvent.setup();
    const refusal = {
      capability: 'review.accept_batch',
      ok: false,
      error: {
        code: 'authority_error',
        message:
          "batch acceptance under review policy 'strict' needs the Product 24.4 conditions " +
          'stated explicitly; strict review is the default and a batch is an exception a ' +
          'researcher declares',
      },
    };
    renderInbox(queueDaemon({ 'review.accept_batch': refusal }));

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Accept the routine candidates/ }));

    await waitFor(() =>
      expect(screen.getByText(/strict review is the default/)).toBeInTheDocument(),
    );
  });

  it('is not offered at all to a window that may not accept', async () => {
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    const daemon = fakeDaemon({
      gets: { '/overview': asHost },
      capabilities: { 'review.inbox': QUEUE },
    });
    renderInbox(daemon, null);

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    expect(
      screen.queryByRole('button', { name: /Accept the routine candidates/ }),
    ).not.toBeInTheDocument();
  });
});

describe('the review inbox inside a project', () => {
  it('opens each candidate on the project’s own review screen', async () => {
    renderView(
      withShell(
        <ProjectPathProvider projectId="prj_abc">
          <ReviewInboxPage />
        </ProjectPathProvider>,
      ),
      {
        daemon: queueDaemon(),
        route: '/projects/prj_abc/review',
        path: '/projects/prj_abc/review',
      },
    );

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    const first = QUEUE.items[0]!;
    const link = screen.getByRole('link', { name: new RegExp(first.field) });
    expect(link).toHaveAttribute('href', `/projects/prj_abc/review/${first.candidate_id}`);
  });

  it('keeps the legacy link when there is no project', async () => {
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    const first = QUEUE.items[0]!;
    expect(screen.getByRole('link', { name: new RegExp(first.field) })).toHaveAttribute(
      'href',
      `/review/${first.candidate_id}`,
    );
  });
});

describe('the palette on the inbox', () => {
  it('offers the queue’s own actions beside the shell’s destinations', async () => {
    const user = userEvent.setup();
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('metric_result')).toBeInTheDocument());
    await user.keyboard('{Control>}k{/Control}');

    const palette = screen.getByRole('dialog', { name: 'Go to, or do' });
    expect(within(palette).getByRole('option', { name: /Next candidate/ })).toBeInTheDocument();
  });
});

// A view mounted without the shell must still render: the registry falls back to a
// do-nothing one rather than throwing, so a page never has to ask whether it has a shell.
describe('outside the shell', () => {
  it('renders the queue with no command registry mounted', async () => {
    const spy = vi.spyOn(console, 'error');
    renderView(<ReviewInboxPage />, {
      daemon: queueDaemon(),
      route: '/review',
      path: '/review',
    });

    await waitFor(() => expect(screen.getByText('metric_result')).toBeInTheDocument());
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});
