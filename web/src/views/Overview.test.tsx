/**
 * The Overview leads with the research state that matters today.
 *
 * Wave 3 replaced the stat-tile row the critique named. What the page asserts now is the
 * order of the reading: what is waiting for a decision, then what has gone stale, then
 * what changed since the researcher last worked, and only then — in the page's footer —
 * what the project holds. Every judgement in all four comes from the daemon, so these
 * assertions are that the page renders what it received, never that it worked anything out.
 */
import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { OverviewPage } from './Overview';
import { ProjectPathProvider } from '../app/projectPaths';
import { FIXTURES, expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';
import type { FakeDaemon } from '../test/harness';

const REFUSAL = 'the workspace lock is held by another process';

/** A daemon that has not answered yet, so the page stays in its loading state. */
function pendingDaemon(): FakeDaemon {
  return {
    fetch: (() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

/** A daemon that refuses the one read this page is built on. */
function refusingDaemon(): FakeDaemon {
  return {
    fetch: (async () => new Response(REFUSAL, { status: 503 })) as unknown as typeof fetch,
    calls: [],
    capabilityCalls: () => [],
  };
}

/** The exported overview with one report replaced, so a group can be given something to show. */
function overviewWith(patch: Record<string, unknown>) {
  return { ...FIXTURES.overview, ...patch };
}

describe('the overview', () => {
  it('leads with the daemon’s own sentence about what needs a researcher', async () => {
    renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText(FIXTURES.overview.project)).toBeInTheDocument());
    expect(screen.getByText(FIXTURES.overview.attention_summary)).toBeInTheDocument();
  });

  it('states what the project holds last, after every group that is work', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() =>
      expect(screen.getByText('Waiting for a decision')).toBeInTheDocument(),
    );
    const stack = container.querySelector('.rh-web-stack');
    const holdings = container.querySelector('.rh-web-overview__holdings');
    expect(holdings).toHaveTextContent(/This project holds/);
    expect(stack?.lastElementChild, 'the colophon is the last thing on the page').toBe(holdings);
    // The size of the project is a count in a sentence that leads somewhere, never a tile.
    expect(
      within(holdings as HTMLElement).getByRole('link', { name: '1 work' }),
    ).toBeInTheDocument();
    expect(container.querySelector('.rh-web-tally')).toBeNull();
  });

  it('renders the waiting groups in the order the daemon reported them', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() =>
      expect(screen.getByText('Waiting for a decision')).toBeInTheDocument(),
    );
    const rendered = Array.from(
      container.querySelectorAll('.rh-web-attention > li > p > a'),
    ).map((node) => node.textContent);
    expect(rendered).toEqual(
      FIXTURES.overview.attention
        .filter((group) => group.surface === 'decide')
        .map((group) => group.label),
    );
  });

  it('says one badge vocabulary in the attention card, and the rest in words', async () => {
    /*
     * The card carried three: the described status badges, a warning "waiting" chip and a
     * neutral "clear" one. The daemon's own label already states the count — "2 review
     * items", "0 conflicts" — and the card is titled "Waiting for a decision", so both
     * chips repeated something already on screen. What a zero needs is a sentence.
     */
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText('Waiting for a decision')).toBeInTheDocument());
    const attention = container.querySelector('.rh-web-attention') as HTMLElement;
    expect(within(attention).queryByText('waiting')).toBeNull();
    expect(within(attention).queryByText('clear')).toBeNull();
    expect(attention.querySelectorAll('.rh-badge')).toHaveLength(0);
    expect(within(attention).getAllByText('— nothing waiting here').length).toBeGreaterThan(0);
  });

  it('leads with the group that has work in it', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() =>
      expect(screen.getByText('Waiting for a decision')).toBeInTheDocument(),
    );
    // "Has work" is an attribute rather than a class since the migration to the Design
    // System: the group's own state, styled from `[data-work]`, and read here the same way.
    expect(container.querySelector('.rh-web-attention > li')?.hasAttribute('data-work')).toBe(true);
  });

  it('sends a waiting item to the item itself when the daemon named a route for it', async () => {
    renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() =>
      expect(screen.getByText('Waiting for a decision')).toBeInTheDocument(),
    );
    const item = FIXTURES.overview.attention[0]?.items[0];
    expect(item?.route).toBeTruthy();
    expect(
      screen.getByRole('link', { name: new RegExp(item!.label.replace('_', ' ')) }),
    ).toHaveAttribute('href', item!.route);
  });

  it('gives what has gone stale its own group, with the daemon’s reason', async () => {
    renderView(<OverviewPage />, {
      daemon: fakeDaemon({
        gets: {
          '/overview': overviewWith({
            attention: FIXTURES.overview.attention.map((group) =>
              group.kind === 'stale'
                ? {
                    ...group,
                    count: 1,
                    label: '1 stale object',
                    items: [
                      {
                        id: 'C0001',
                        label: 'C0001',
                        title: 'TrafficLM reaches an F1 of 94.32 on CICIDS2017',
                        detail: 'anchor no longer replays against the stored parse',
                        priority: 4,
                        route: '/claims/C0001',
                      },
                    ],
                  }
                : group,
            ),
          }),
        },
      }),
    });

    await waitFor(() => expect(screen.getByText('Gone stale')).toBeInTheDocument());
    // The daemon's title names the object; the node id rides along in mono, exactly as it
    // does on the Stale page, because both surfaces render one item.
    expect(
      screen.getByRole('link', { name: 'TrafficLM reaches an F1 of 94.32 on CICIDS2017 C0001' }),
    ).toHaveAttribute('href', '/claims/C0001');
    expect(
      screen.getByText(/anchor no longer replays against the stored parse/),
    ).toBeInTheDocument();
  });

  it('lists what changed since the last session, newest first, with the window it used', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() =>
      expect(screen.getByText('Since your last session')).toBeInTheDocument(),
    );
    const changes = FIXTURES.overview.since_last_session!;
    expect(screen.getByText(changes.summary)).toBeInTheDocument();
    const rendered = Array.from(container.querySelectorAll('.rh-change-list__what')).map(
      (node) => node.textContent,
    );
    // Each row now leads with the subject the daemon attributed the change to (wave 5J).
    // The daemon's own sentence still follows it word for word, in the order it was given.
    const subject: Record<string, string> = { researcher: 'You ', daemon: 'The daemon ', '': '' };
    expect(rendered).toEqual(
      changes.entries.map((entry) => `${subject[entry.by] ?? ''}${entry.label}`),
    );
  });

  it('says who recorded each change, in the words the daemon attributed it to', async () => {
    /*
     * The returning researcher's question is which of these she decided and which the
     * daemon did while she was away. The answer is the daemon's `by`, rendered as the
     * subject of its own sentence; the page adds no attribution of its own and drops none.
     */
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() =>
      expect(screen.getByText('Since your last session')).toBeInTheDocument(),
    );
    const entries = FIXTURES.overview.since_last_session!.entries;
    expect(entries.every((entry) => entry.by === 'researcher')).toBe(true);
    const rows = Array.from(container.querySelectorAll('.rh-change-list__entry'));
    expect(rows.map((row) => row.getAttribute('data-by'))).toEqual(entries.map(() => 'researcher'));
    expect(container.querySelector('.rh-change-list__what')).toHaveTextContent(
      `You ${entries[0]!.label}`,
    );
  });

  it('leaves a change the daemon attributed to nobody unattributed', async () => {
    const unattributed = {
      ...FIXTURES.overview.since_last_session!,
      entries: [
        {
          ...FIXTURES.overview.since_last_session!.entries[0]!,
          by: '',
          label: 'opened a conflict: two readings of Table 1 disagree',
        },
      ],
    };
    const { container } = renderView(<OverviewPage />, {
      daemon: fakeDaemon({
        gets: { '/overview': overviewWith({ since_last_session: unattributed }) },
      }),
    });

    await waitFor(() =>
      expect(screen.getByText('Since your last session')).toBeInTheDocument(),
    );
    expect(container.querySelector('.rh-change-list__entry')).not.toHaveAttribute('data-by');
    expect(container.querySelector('.rh-change-list__what')).toHaveTextContent(
      'opened a conflict: two readings of Table 1 disagree',
    );
  });

  it('says which window it looked at, and offers a next action, when nothing changed', async () => {
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <OverviewPage />
      </ProjectPathProvider>,
      {
        daemon: fakeDaemon({
          gets: {
            '/overview': overviewWith({
              since_last_session: {
                basis: 'recent_window',
                since: '2026-08-31T00:00:00+00:00',
                summary: 'Nothing has changed in the last seven days.',
                more: '',
                entries: [],
                total: 0,
              },
            }),
          },
        }),
        route: '/projects/prj_abc/overview',
        path: '/projects/prj_abc/overview',
      },
    );

    await waitFor(() =>
      expect(screen.getByText('Nothing has changed in the last seven days.')).toBeInTheDocument(),
    );
    expect(
      screen.getByRole('link', { name: 'Open the conversation to start the next piece of work' }),
    ).toHaveAttribute('href', '/projects/prj_abc/');
  });

  it('states claim health as sentences that lead to the claims, not as a row of numbers', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText('Claim health')).toBeInTheDocument());
    // The word for the status comes from the shared vocabulary, never from the daemon's key.
    expect(screen.getByRole('link', { name: '1 claim is' })).toBeInTheDocument();
    expect(screen.getByText('Supported')).toBeInTheDocument();
    expect(container.textContent?.toLowerCase()).not.toContain('confidence');
    expect(container.textContent).not.toMatch(/\d+(\.\d+)?%/);
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() =>
      expect(screen.getByText('Waiting for a decision')).toBeInTheDocument(),
    );
    await expectNoAxeViolations(container);
  });
});

/**
 * The same page under `research app`, where every workspace screen is inside a project.
 *
 * `attention[].route` is the daemon's own workspace path and stays that way in the DTO;
 * what changes is only where the link on screen points, which is what keeps a click on
 * "3 review items" inside the project the researcher is reading.
 */
describe('the overview inside a project', () => {
  const renderInProject = () =>
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <OverviewPage />
      </ProjectPathProvider>,
      {
        daemon: fakeDaemon(),
        route: '/projects/prj_abc/overview',
        path: '/projects/prj_abc/overview',
      },
    );

  it('points every waiting group at the active project', async () => {
    const { container } = renderInProject();

    await waitFor(() =>
      expect(screen.getByText('Waiting for a decision')).toBeInTheDocument(),
    );
    const hrefs = Array.from(container.querySelectorAll('.rh-web-attention > li > p > a')).map(
      (node) => node.getAttribute('href'),
    );
    expect(hrefs).toEqual(
      FIXTURES.overview.attention
        .filter((group) => group.surface === 'decide')
        .map((group) => `/projects/prj_abc${group.route}`),
    );
  });

  it('points a change at the object it changed, inside the project', async () => {
    const { container } = renderInProject();

    await waitFor(() =>
      expect(screen.getByText('Since your last session')).toBeInTheDocument(),
    );
    const linked = FIXTURES.overview.since_last_session!.entries.find((entry) => entry.route);
    expect(linked).toBeDefined();
    const hrefs = Array.from(container.querySelectorAll('.rh-change-list__link')).map((node) =>
      node.getAttribute('href'),
    );
    expect(hrefs).toContain(`/projects/prj_abc${linked!.route}`);
  });

  it('points an open question at the project’s own questions screen', async () => {
    // The exported fixture has no open question; the link is what is under test, so one is
    // added to the daemon's own report rather than invented in the view.
    const overview = overviewWith({
      open_questions: [{ id: 'RQ0001', label: 'Does it hold out of distribution?', detail: 'open' }],
    });
    renderView(
      <ProjectPathProvider projectId="prj_abc">
        <OverviewPage />
      </ProjectPathProvider>,
      {
        daemon: fakeDaemon({ gets: { '/overview': overview } }),
        route: '/projects/prj_abc/overview',
        path: '/projects/prj_abc/overview',
      },
    );

    await waitFor(() => expect(screen.getByText('Open questions')).toBeInTheDocument());
    expect(
      screen.getByRole('link', { name: 'Does it hold out of distribution?' }),
    ).toHaveAttribute('href', '/projects/prj_abc/questions');
  });

  it('leaves the legacy host’s links exactly where they were', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() =>
      expect(screen.getByText('Waiting for a decision')).toBeInTheDocument(),
    );
    const hrefs = Array.from(container.querySelectorAll('.rh-web-attention > li > p > a')).map(
      (node) => node.getAttribute('href'),
    );
    expect(hrefs).toEqual(
      FIXTURES.overview.attention
        .filter((group) => group.surface === 'decide')
        .map((group) => group.route),
    );
  });
});

/**
 * "Look again" says when it last looked (critique H1: it never did).
 *
 * The time is the read's own: the transport stamps every answered round trip, and the
 * session hands that instant on, so the page reports when its content arrived rather than
 * running a clock of its own. It is quiet text until a researcher presses the button — a
 * page that announced every automatic read would talk over the work — and from that press
 * on it is a polite live region, because the answer to "is this current?" is the one thing
 * a manual refresh is asking for.
 */
describe('when the overview last read', () => {
  it('states the time of the read beside “Look again”', async () => {
    const { container } = renderView(<OverviewPage />, { daemon: fakeDaemon() });

    await waitFor(() => expect(screen.getByText(FIXTURES.overview.project)).toBeInTheDocument());
    const read = await screen.findByText(/^Read at \d{1,2}:\d{2}/);
    expect(read.closest('.rh-full-page__toolbar'), 'it sits in the toolbar').not.toBeNull();
    expect(container.querySelector('.rh-web-overview__read')).toBe(read);
  });

  it('says nothing about a read that has not happened', () => {
    renderView(<OverviewPage />, { daemon: pendingDaemon() });

    expect(screen.queryByText(/^Read at /)).toBeNull();
    expect(screen.getByRole('button', { name: 'Look again' })).toBeInTheDocument();
  });

  it('stays quiet until the researcher asks again, and is polite when it answers', async () => {
    const user = userEvent.setup();
    renderView(<OverviewPage />, { daemon: fakeDaemon() });

    const read = await screen.findByText(/^Read at /);
    expect(read, 'an automatic read announces nothing').not.toHaveAttribute('role');

    await user.click(screen.getByRole('button', { name: 'Look again' }));

    // `status` is the polite one: it waits for a pause instead of interrupting.
    await waitFor(() =>
      expect(screen.getByText(/^Read at /)).toHaveAttribute('role', 'status'),
    );
  });
});

/**
 * The three states the page can be in that are not "here is the project".
 *
 * The page used to return each of them *instead of* itself, which left the h1 — the
 * project's own name — off the screen exactly when a researcher needed to know which
 * project had failed to load. The frame is the assertion here, and the toolbar with it:
 * "look again" is the one thing a researcher can do in every one of these states.
 */
describe('the overview before, without, and after its read', () => {
  it('keeps a heading, a toolbar and a skeleton while the read is in flight', () => {
    const { container } = renderView(<OverviewPage />, { daemon: pendingDaemon() });

    expect(screen.getByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Look again' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Reading the project overview…');
    expect(container.querySelector('.rh-skeleton')).toBeInTheDocument();
    // The description cannot quote what it does not have, so it says what it does know.
    expect(container.textContent).not.toMatch(/need a researcher/);
  });

  it('keeps the heading and the toolbar when the daemon refuses, and offers the retry', async () => {
    renderView(<OverviewPage />, { daemon: refusingDaemon() });

    await waitFor(() => expect(screen.getByText(REFUSAL)).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1, name: 'Overview' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Look again' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('teaches what every group is when a project is new, and where each one comes from', async () => {
    const bare = overviewWith({
      attention_summary: 'Nothing needs a researcher right now.',
      attention: FIXTURES.overview.attention.map((group) => ({
        ...group,
        count: 0,
        label: `0 ${group.kind}`,
        items: [],
      })),
      claim_health: [],
      open_questions: [],
      since_last_session: {
        basis: 'no_history',
        since: '2026-08-31T00:00:00+00:00',
        summary: 'No research activity has been recorded in this project yet.',
        more: '',
        entries: [],
        total: 0,
      },
    });
    const { container } = renderView(
      <ProjectPathProvider projectId="prj_abc">
        <OverviewPage />
      </ProjectPathProvider>,
      {
        daemon: fakeDaemon({ gets: { '/overview': bare } }),
        route: '/projects/prj_abc/overview',
        path: '/projects/prj_abc/overview',
      },
    );

    await waitFor(() =>
      expect(screen.getByText('Nothing is waiting for a decision')).toBeInTheDocument(),
    );
    for (const action of [
      'Open the review inbox',
      'Open the corpus this project rests on',
      'Open the conversation to start the next piece of work',
      'Open the conversation to promote a claim',
      'Open the conversation to promote a question',
    ]) {
      expect(screen.getByRole('link', { name: action })).toBeInTheDocument();
    }
    expect(screen.getByText('Nothing is stale')).toBeInTheDocument();
    expect(screen.getByText('No claims registered yet')).toBeInTheDocument();
    expect(screen.getByText('No open questions')).toBeInTheDocument();
    await expectNoAxeViolations(container);
  });
});
