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
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import { daemonReachability } from '../api/client';
import type { ReviewItem } from '../api/dto';
import {
  CATEGORY_ORDER,
  ReviewInboxPage,
  ReviewRow,
  groupByCategory,
  inboxGroups,
  matchesFilters,
} from './ReviewInbox';
import { CommandsProvider } from '../app/commands';
import { ProjectPathProvider } from '../app/projectPaths';
import { fieldLabel } from '../components/Feedback';
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
    expect(screen.getByText('Metric result')).toBeInTheDocument();
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

    await waitFor(() => expect(screen.getByText('Metric result')).toBeInTheDocument());
    const first = QUEUE.items[0]!;
    const link = screen.getByText(fieldLabel(first.field)).closest('a');
    expect(link).toHaveAttribute('href', `/review/${first.candidate_id}`);
  });

  it('prints no identifier a researcher would have to decode', async () => {
    const { container } = renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('Metric result')).toBeInTheDocument());
    const text = container.textContent ?? '';
    for (const token of ['metric_result', 'method_summary', 'high_risk', 'partially_supported']) {
      expect(text).not.toContain(token);
    }
    // The daemon's own sentence survives; only its vocabulary is read out in words.
    expect(text).toContain('the verifier reported partially supported');
    expect(text).toContain('Tier 2 — deep review');
  });

  it('puts the meaning of the two states a row is about within reach', async () => {
    const user = userEvent.setup();
    const { container } = renderView(<ReviewRow item={QUEUE.items[0]!} />, {
      daemon: queueDaemon(),
      route: '/review',
      path: '/review',
    });

    const category = screen.getByText('High-risk scientific claims').closest('.rh-badge')!;
    expect(category).toHaveAttribute('tabindex', '0');
    expect(category).not.toHaveAttribute('title');
    expect(
      container.querySelector(`#${category.getAttribute('aria-describedby')}`),
    ).toHaveTextContent(/carries a number/);

    await user.tab();
    await user.tab();
    expect(category).toHaveFocus();
    expect(container.querySelector('.rh-authority-badge__hint')).toHaveTextContent(
      /carries a number/,
    );
  });

  /**
   * The tier stays plain text — it is a property of the question, not a state of this
   * answer, and a third badge on the row would say otherwise — but "Tier 2 — deep review"
   * was a phrase a first-timer met with nothing to explain it (critique 2026-09-07,
   * heuristic 10, Jordan). It carries its sentence the way the two badges beside it do.
   */
  it('says what the tier means, without turning the tier into a badge', async () => {
    const user = userEvent.setup();
    const { container } = renderView(<ReviewRow item={QUEUE.items[0]!} />, {
      daemon: queueDaemon(),
      route: '/review',
      path: '/review',
    });

    const tier = screen.getByText('Tier 2 — deep review');
    expect(tier.closest('.rh-badge')).toBeNull();
    expect(tier).toHaveAttribute('tabindex', '0');
    expect(tier).not.toHaveAttribute('title');
    expect(container.querySelector(`#${tier.getAttribute('aria-describedby')}`)).toHaveTextContent(
      /Interpretation/,
    );

    await user.click(tier);
    expect(container.querySelector('.rh-described-term__hint')).toHaveTextContent(/Interpretation/);
  });

  it('finds a candidate by the word the row shows as well as by the daemon’s field name', () => {
    const metric = QUEUE.items.find((item) => item.field === 'metric_result')!;

    expect(matchesFilters(metric, { ...NO_FILTERS, text: 'metric result' })).toBe(true);
    expect(matchesFilters(metric, { ...NO_FILTERS, text: 'metric_result' })).toBe(true);
  });

  it('shows no model-confidence number, because the daemon reports none', async () => {
    const { container } = renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('Metric result')).toBeInTheDocument());
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

    await waitFor(() => expect(screen.getByText('Metric result')).toBeInTheDocument());
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
    expect(screen.queryByText('Metric result')).not.toBeInTheDocument();
    expect(screen.getByText('Method summary')).toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByText('Metric result')).toBeInTheDocument());
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

    await waitFor(() => expect(screen.getByText('Metric result')).toBeInTheDocument());
    const rows = screen.getAllByRole('link', { name: /·/ });

    await user.keyboard('j');
    expect(rows[0]).toHaveFocus();
    await user.keyboard('j');
    expect(rows[1]).toHaveFocus();
    await user.keyboard('k');
    expect(rows[0]).toHaveFocus();
  });

  it('presses the row in focus with the keys the review screen binds', async () => {
    const user = userEvent.setup();
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('Metric result')).toBeInTheDocument());

    // `j` puts the focus on the first row, and `r` asks *that* row for the sentence a
    // rejection is recorded with — the key presses the row's own button, as `r` on the
    // review screen presses the bar's.
    await user.keyboard('j');
    await user.keyboard('r');
    expect(
      screen.getByRole('form', { name: 'Reject Metric result · W0001' }),
    ).toBeInTheDocument();

    // A deep review has no Accept on its row, and the key invents none: three rows down,
    // on the candidate the daemon filed as routine, the same key restates what it writes.
    await user.keyboard('jj');
    await user.keyboard('a');
    expect(
      screen.getByText(/Accept as evidence for Dataset of W0001/),
    ).toBeInTheDocument();
  });

  it('teaches the row keys rather than leaving them to be guessed', async () => {
    const user = userEvent.setup();
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('Metric result')).toBeInTheDocument());
    await user.keyboard('?');

    const help = screen.getByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(within(help).getByText('The row in focus')).toBeInTheDocument();
    expect(within(help).getByText('Reject')).toBeInTheDocument();
  });

  it('does not move a row while the researcher is typing in the filter', async () => {
    const user = userEvent.setup();
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('Metric result')).toBeInTheDocument());
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

  it('puts its control in the toolbar and still opens the page on the first group', async () => {
    /*
     * Wave one moved this panel below the queue so that a conflict, not a batch, was what
     * opened the page. That property is kept and asserted here — but the control itself is
     * no longer *in* the queue at all: it acts on the whole queue, so it sits in the
     * toolbar beside the filters, and nothing about the batch is on the page until a
     * preview has been asked for.
     */
    const user = userEvent.setup();
    renderInbox(queueDaemon({ 'review.accept_batch': DRY_RUN }));

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    const trigger = screen.getByRole('button', { name: /Accept the routine candidates/ });
    expect(trigger.closest('.rh-full-page__toolbar')).not.toBeNull();
    expect(screen.getAllByRole('heading', { level: 2 }).map((node) => node.textContent)).not.toContain(
      'Batch accept',
    );

    await user.click(trigger);
    await waitFor(() =>
      expect(
        screen.getByText(/1 routine candidate meets the batch conditions/),
      ).toBeInTheDocument(),
    );
    // The restatement appears where the control that opened it is: above the queue, so it
    // can be read without hunting, and only once it has been asked for.
    const panels = screen.getAllByRole('heading', { level: 2 }).map((node) => node.textContent);
    expect(panels.indexOf('Batch accept')).toBeLessThan(
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
    expect(screen.getByText(/verdict is partially supported, not supported/)).toBeInTheDocument();
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
    ).toHaveTextContent('Dataset · W0001');
    expect(screen.getByText('Nothing is waiting for review')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Accept the routine candidates/ }),
    ).not.toBeInTheDocument();
  });

  it('decides a routine candidate on its own row, and still asks twice before it writes', async () => {
    const user = userEvent.setup();
    const daemon = queueDaemon({
      'review.accept': {
        candidate_id: 'cand_4590b9b1f474d343',
        action: 'accept',
        status: 'reviewed',
        evidence: 'E0007',
        mutation: null,
      },
    });
    renderInbox(daemon);

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    const row = screen.getByRole('group', { name: 'Decide Dataset · W0001' });

    // The three decisions the daemon's routine filing leaves to the researcher, and no more.
    expect(within(row).getAllByRole('button').map((button) => button.textContent)).toEqual([
      'Accept',
      'Defer',
      'Reject',
    ]);
    // Every row is decidable now; only a routine one may be *accepted* where it sits. The
    // deep-review row keeps its own group, and Accept is the one thing missing from it.
    const deep = screen.getByRole('group', { name: 'Decide Metric result · W0001' });
    expect(within(deep).queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument();

    await user.click(within(row).getByRole('button', { name: 'Accept' }));
    // The first press writes nothing: it restates what the second one would write.
    expect(daemon.capabilityCalls().filter((call) => call.name === 'review.accept')).toEqual([]);
    expect(
      screen.getByText(/Accept as evidence for Dataset of W0001: “All experiments use CICIDS2017”/),
    ).toBeInTheDocument();
    expect(screen.getByText(/No review action takes an acceptance back/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Accept as evidence' }));
    await waitFor(() =>
      expect(daemon.capabilityCalls().filter((call) => call.name === 'review.accept')).toEqual([
        { name: 'review.accept', request: { candidate_id: 'cand_4590b9b1f474d343' } },
      ]),
    );
    // Nothing fakes an undo, here or anywhere else the cockpit accepts.
    expect(screen.queryByRole('button', { name: /Undo/i })).not.toBeInTheDocument();
  });

  it('asks a routine deferral for the sentence the daemon records with it', async () => {
    const user = userEvent.setup();
    const daemon = queueDaemon({
      'review.defer': {
        candidate_id: 'cand_4590b9b1f474d343',
        action: 'defer',
        status: 'deferred',
        evidence: null,
        mutation: null,
      },
    });
    renderInbox(daemon);

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    const row = screen.getByRole('group', { name: 'Decide Dataset · W0001' });
    await user.click(within(row).getByRole('button', { name: 'Defer' }));

    const form = screen.getByRole('form', { name: 'Defer Dataset · W0001' });
    await user.type(within(form).getByLabelText('Why this is being put aside'), 'waiting for the appendix');
    await user.click(within(form).getByRole('button', { name: 'Defer' }));

    await waitFor(() =>
      expect(daemon.capabilityCalls().filter((call) => call.name === 'review.defer')).toEqual([
        {
          name: 'review.defer',
          request: { candidate_id: 'cand_4590b9b1f474d343', note: 'waiting for the appendix' },
        },
      ]),
    );
  });

  it('offers no row decision at all to a window that may not accept', async () => {
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    renderInbox(
      fakeDaemon({ gets: { '/overview': asHost }, capabilities: { 'review.inbox': QUEUE } }),
      null,
    );

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    expect(screen.queryByRole('group', { name: /^Decide / })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open to decide' })).not.toBeInTheDocument();
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

/**
 * Deciding a row at every tier.
 *
 * The daemon's routine filing is what lets a candidate be *accepted* where it sits:
 * verified, supported, tier 0 or 1, anchor valid. A deeper one is read before it is
 * accepted, because the acceptance is what writes authority and Product 26 puts the source
 * beside that decision. Refusing a proposal and putting one aside write no evidence and
 * change no state the source would settle, so every row offers those two, in the same
 * words and against the same capabilities the review screen uses — and says where Accept is.
 */
describe('deciding a row, at every tier', () => {
  /** metric_result: high risk, tier 2 — a deep review, and first in the queue. */
  const DEEP = QUEUE.items[0]!;
  const REJECTED = {
    candidate_id: DEEP.candidate_id,
    action: 'reject',
    status: 'rejected',
    evidence: null,
    mutation: null,
  };

  it('offers a deep review what the source does not settle, and never Accept', async () => {
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    const row = screen.getByRole('group', { name: 'Decide Metric result · W0001' });

    expect(within(row).getAllByRole('button').map((button) => button.textContent)).toEqual([
      'Defer',
      'Reject',
    ]);
    // Where the acceptance is taken instead, said on the row rather than left to be found.
    expect(within(row).getByRole('link', { name: 'Open to decide' })).toHaveAttribute(
      'href',
      `/review/${DEEP.candidate_id}`,
    );
    // Both rows the daemon did not file as routine say why Accept is not on them.
    expect(screen.getAllByText(/Accepting it happens beside the source/)).toHaveLength(2);
  });

  it('takes the sentence a rejection needs on the row itself, in a field and never a dialog', async () => {
    const user = userEvent.setup();
    const daemon = queueDaemon({ 'review.reject': REJECTED });
    renderInbox(daemon);

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    const row = screen.getByRole('group', { name: 'Decide Metric result · W0001' });
    await user.click(within(row).getByRole('button', { name: 'Reject' }));

    // The first press writes nothing. It asks for what the daemon records the refusal with.
    expect(daemon.capabilityCalls().filter((call) => call.name === 'review.reject')).toEqual([]);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    const form = screen.getByRole('form', { name: 'Reject Metric result · W0001' });
    expect(within(form).getByRole('button', { name: 'Reject' })).toBeDisabled();

    await user.type(
      within(form).getByLabelText('Why this candidate is refused'),
      'the number is the baseline, not the model',
    );
    await user.click(within(form).getByRole('button', { name: 'Reject' }));

    await waitFor(() =>
      expect(daemon.capabilityCalls().filter((call) => call.name === 'review.reject')).toEqual([
        {
          name: 'review.reject',
          request: {
            candidate_id: DEEP.candidate_id,
            reason: 'the number is the baseline, not the model',
          },
        },
      ]),
    );
    // Nothing fakes an undo on a row either, whatever the tier.
    expect(screen.queryByRole('button', { name: /Undo/i })).not.toBeInTheDocument();
  });

  it('lands the focus on the next row in the daemon’s order once one leaves the queue', async () => {
    const user = userEvent.setup();
    // The queue the daemon answers with changes when the candidate leaves it, so the
    // capability table is the mutable one a real afternoon has.
    const capabilities: Record<string, unknown> = {
      'review.inbox': QUEUE,
      'review.reject': REJECTED,
    };
    renderInbox(fakeDaemon({ capabilities }));

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    capabilities['review.inbox'] = { ...QUEUE, count: 2, items: QUEUE.items.slice(1) };

    const row = screen.getByRole('group', { name: 'Decide Metric result · W0001' });
    await user.click(within(row).getByRole('button', { name: 'Reject' }));
    const form = screen.getByRole('form', { name: 'Reject Metric result · W0001' });
    await user.type(within(form).getByLabelText('Why this candidate is refused'), 'the baseline');
    await user.click(within(form).getByRole('button', { name: 'Reject' }));

    await waitFor(() => expect(screen.getByText(/2 waiting/)).toBeInTheDocument());
    // The rule decide-and-next uses: the next candidate in the queue's own order, not the
    // top of the document a removed row would otherwise drop the keyboard on.
    await waitFor(() =>
      expect(screen.getByRole('link', { name: /Method summary · W0001/ })).toHaveFocus(),
    );
  });

  it('closes an open conflict record rather than rejecting past it', async () => {
    const user = userEvent.setup();
    const conflicted: ReviewItem = {
      ...DEEP,
      category: 'conflict',
      conflicts: [
        {
          conflict_id: 'CF0001',
          created_at: '2026-09-01T00:00:00Z',
          differing_fields: ['value'],
          kind: 'value_conflict',
          positions: [],
          proposed_changes: [],
          status: 'open',
          subject: 'W0001 metric_result',
          summary: 'Two readings of the same cell',
          tier: 2,
        },
      ],
    };
    const daemon = fakeDaemon({
      capabilities: {
        'review.inbox': { ...QUEUE, count: 1, items: [conflicted] },
        'review.resolve_conflict': {
          candidate_id: conflicted.candidate_id,
          choice: 'reject',
          mutation: null,
        },
      },
    });
    renderInbox(daemon);

    await waitFor(() => expect(screen.getByText(/1 waiting/)).toBeInTheDocument());
    const row = screen.getByRole('group', { name: 'Decide Metric result · W0001' });
    await user.click(within(row).getByRole('button', { name: 'Reject' }));

    const form = screen.getByRole('form', { name: 'Reject Metric result · W0001' });
    expect(within(form).getByText(/conflict record closes with your reason/)).toBeInTheDocument();
    await user.type(
      within(form).getByLabelText('Why this candidate is refused'),
      'the other cell is the model’s',
    );
    await user.click(within(form).getByRole('button', { name: 'Reject' }));

    // The same routing the review screen uses: a rejection that left the record open would
    // leave the disagreement on the Conflicts screen forever.
    await waitFor(() =>
      expect(
        daemon.capabilityCalls().filter((call) => call.name === 'review.resolve_conflict'),
      ).toEqual([
        {
          name: 'review.resolve_conflict',
          request: {
            candidate_id: conflicted.candidate_id,
            choice: 'reject',
            reason: 'the other cell is the model’s',
          },
        },
      ]),
    );
    expect(daemon.capabilityCalls().filter((call) => call.name === 'review.reject')).toEqual([]);
  });

  it('has no automatically detectable accessibility violation with every row decidable', async () => {
    const { container } = renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('Metric result')).toBeInTheDocument());
    await expectNoAxeViolations(container);
  });
});

describe('the queue while the daemon is silent', () => {
  afterEach(() => daemonReachability.reset());

  it('says one quiet line rather than a second notice under the shell’s', async () => {
    /*
     * An outage is one condition, and the shell states it once for the whole window, with
     * the cause, the command, what is safe and the one way to ask again. The page's part is
     * the part that is local to it: how old what it has is — as a line, not as a second
     * notice with a second retry button (`daemon-offline.png`).
     */
    const silent = {
      fetch: (async () => {
        throw new TypeError('Failed to fetch');
      }) as unknown as typeof fetch,
      calls: [],
      capabilityCalls: () => [],
    };
    renderInbox(silent);

    await waitFor(() =>
      expect(screen.getByText(/reads itself.*as soon as the daemon answers/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Waiting for the daemon/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
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
    const link = screen.getByRole('link', { name: new RegExp(fieldLabel(first.field)) });
    expect(link).toHaveAttribute('href', `/projects/prj_abc/review/${first.candidate_id}`);
  });

  it('keeps the legacy link when there is no project', async () => {
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    const first = QUEUE.items[0]!;
    expect(
      screen.getByRole('link', { name: new RegExp(fieldLabel(first.field)) }),
    ).toHaveAttribute(
      'href',
      `/review/${first.candidate_id}`,
    );
  });
});

describe('the palette on the inbox', () => {
  it('offers the queue’s own actions beside the shell’s destinations', async () => {
    const user = userEvent.setup();
    renderInbox(queueDaemon());

    await waitFor(() => expect(screen.getByText('Metric result')).toBeInTheDocument());
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

    await waitFor(() => expect(screen.getByText('Metric result')).toBeInTheDocument());
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});
