/**
 * Graph-backed references, driven the way a researcher drives them.
 *
 * Each `describe` is one clause of the Web half of Gate P20 (graph spec §11, plan §0.1 and
 * conversation spec §7), run through the real route table, the real shell and the real
 * client; the only fakes are `fetch` and the `graph.*` payloads, and those payloads were
 * generated from the daemon's own response models.
 *
 * Two things these tests are strict about, because they are what the projection must never
 * be allowed to do:
 *
 * - **A candidate relation never reads as an accepted one.** Accepted Evidence joined to a
 *   Claim by a model's proposal is still a proposal, and the pane says so in words.
 * - **The cockpit renders what the graph returns.** A private prior-session message pruned
 *   from a project-visible object's neighbourhood is *absent*, and nothing on this side
 *   filters, re-adds or infers a neighbour.
 */
import { beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@research-harness/design';
import { HarnessClient } from '../../../api/client';
import { SessionProvider } from '../../../app/session';
import { AppRoutes } from '../../../app/routes';
import { FIXTURES, expectNoAxeViolations, fakeDaemon } from '../../../test/harness';
import type { FakeDaemon } from '../../../test/harness';
import { draftKey } from '../useDraft';

import contextPack from '../../../test/fixtures/conversation/context-pack.json';
import providers from '../../../test/fixtures/conversation/providers.json';
import sendStarted from '../../../test/fixtures/conversation/send-started.json';
import sessions from '../../../test/fixtures/conversation/sessions.json';
import autocompleteE from '../../../test/fixtures/graph/autocomplete-e.json';
import blocksA0017 from '../../../test/fixtures/graph/blocks-a0017-3.json';
import neighboursClaim from '../../../test/fixtures/graph/neighbours-claim.json';
import neighboursEvidence from '../../../test/fixtures/graph/neighbours-evidence.json';
import neighboursProject from '../../../test/fixtures/graph/neighbours-claim-project.json';
import provenanceClaim from '../../../test/fixtures/graph/provenance-claim.json';
import provenanceNone from '../../../test/fixtures/graph/provenance-none.json';
import resolveArtifact from '../../../test/fixtures/graph/resolve-artifact-link.json';
import resolveBroken from '../../../test/fixtures/graph/resolve-artifact-broken.json';
import resolveEvidence from '../../../test/fixtures/graph/resolve-evidence.json';
import resolveManuscript from '../../../test/fixtures/graph/resolve-manuscript-link.json';
import resolvePrivate from '../../../test/fixtures/graph/resolve-private.json';
import resolveSession from '../../../test/fixtures/graph/resolve-session-link.json';
import resolveStale from '../../../test/fixtures/graph/resolve-stale.json';
import resolveUnresolved from '../../../test/fixtures/graph/resolve-unresolved.json';
import statusAbsent from '../../../test/fixtures/graph/status-absent.json';
import statusAvailable from '../../../test/fixtures/graph/status-available.json';
import statusRebuilding from '../../../test/fixtures/graph/status-rebuilding.json';
import manuscriptBuild from '../../../test/fixtures/manuscript-workspace/build-unavailable.json';
import manuscriptFiles from '../../../test/fixtures/manuscript-workspace/files.json';
import manuscriptMain from '../../../test/fixtures/manuscript-workspace/read-main.json';
import transcript from '../../../test/fixtures/graph/transcript-links.json';

const SESSION = 'CS0001';
const ROUTE = `/?session=${SESSION}`;

/* -- the fake daemon ------------------------------------------------------- */

interface Answers {
  [capability: string]: unknown;
}

/** Everything the conversation reads, plus the graph, with sensible defaults. */
function answers(extra: Answers = {}): Answers {
  return {
    'session.list': sessions,
    'session.get': transcript,
    'session.search': { count: 0, matches: [] },
    'provider.list': providers,
    'context.get': contextPack,
    'context.preview': contextPack,
    'state.index': FIXTURES.index,
    'evidence.list': { count: 0, evidence: [] },
    'claim.list': { count: 0, claims: [] },
    'review.inbox': FIXTURES.reviewInbox,
    'state.stale': { count: 0, marks: [] },
    'attachment.check_send': { session: SESSION, attachments: [] },
    'graph.status': statusAvailable,
    'graph.autocomplete': autocompleteE,
    ...extra,
  };
}

/** `graph.resolve` and `graph.neighbors` answer differently per request, so they dispatch. */
interface GraphScript {
  /** Keyed by the `reference` the composer or a link asked about. */
  resolve?: Record<string, unknown>;
  /** Keyed by the node `id` a traversal started from. */
  neighbours?: Record<string, unknown>;
  provenance?: Record<string, unknown>;
}

/**
 * `fakeDaemon` maps a capability to one answer; the graph reads take a subject.
 *
 * Layered here rather than in the shared harness, the way `withRun` layers the run stream:
 * a script belongs to the test that scripts it. Every request is still recorded on the
 * daemon, so a test can assert what was asked as well as what came back.
 */
function withGraph(daemon: FakeDaemon, script: GraphScript): FakeDaemon {
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(String(input), 'http://daemon.test');
    const name = url.pathname.startsWith('/capabilities/')
      ? url.pathname.slice('/capabilities/'.length)
      : null;
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, string>) : {};
    const table =
      name === 'graph.resolve'
        ? script.resolve
        : name === 'graph.neighbors'
          ? script.neighbours
          : name === 'graph.provenance'
            ? script.provenance
            : undefined;
    if (table === undefined) return daemon.fetch(input, init);
    daemon.calls.push({ method: 'POST', path: url.pathname, body });
    const key = name === 'graph.resolve' ? (body.reference ?? '') : (body.id ?? '');
    const answer = table[key];
    if (answer === undefined) {
      return json({
        capability: name,
        ok: false,
        error: { code: 'not_found', message: `no scripted graph answer for ${key}` },
      });
    }
    return json({ capability: name, ok: true, result: answer });
  };
  return { ...daemon, fetch: fetchImpl as unknown as typeof fetch };
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderCockpit(options: { daemon: FakeDaemon; route?: string }) {
  const client = new HarnessClient({
    baseUrl: 'http://daemon.test',
    token: 'local-token',
    fetchImpl: options.daemon.fetch,
  });
  return render(
    <ThemeProvider defaultTheme="dark" storageKey={null}>
      <ToastProvider>
        <MemoryRouter
          initialEntries={[options.route ?? ROUTE]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <SessionProvider client={client}>
            <AppRoutes />
          </SessionProvider>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

/** The transcript is on screen once the answer that carries the deep links is. */
async function transcriptReady(): Promise<void> {
  await screen.findByText(/Yes at the corpus level/, undefined, { timeout: 3000 });
}

const requests = (daemon: FakeDaemon, name: string) =>
  daemon.calls.filter((call) => call.path === `/capabilities/${name}`).map((call) => call.body);

/*
 * One manuscript deep link lands on `/manuscript`, which mounts CodeMirror, and CodeMirror
 * measures the document as it renders. jsdom cannot, so the same two `Range` shims task
 * W4's own workspace test installs are installed here — nothing else is stubbed.
 */
beforeAll(() => {
  const rect = {
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: 0,
    height: 0,
    toJSON: () => ({}),
  } as DOMRect;
  const rects = Object.assign([] as DOMRect[], { item: () => null }) as unknown as DOMRectList;
  Range.prototype.getClientRects = () => rects;
  Range.prototype.getBoundingClientRect = () => rect;
});

beforeEach(() => {
  window.localStorage.clear();
});

/* -- §11.4 autocomplete, and the exact object that gets recorded ----------- */

describe('completing an `@` reference', () => {
  it('offers the graph’s own rows and records the exact object it resolved to', async () => {
    const daemon = withGraph(fakeDaemon({ capabilities: answers() }), {
      resolve: { E0482: resolveEvidence },
    });
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();

    await user.type(screen.getByRole('textbox', { name: 'Message' }), '@');
    const search = await screen.findByRole('combobox', { name: 'Insert a research reference' });
    await user.type(search, 'E');

    // The graph answered, with the prefix as typed.
    await waitFor(() => expect(requests(daemon, 'graph.autocomplete').length).toBeGreaterThan(0));
    expect(requests(daemon, 'graph.autocomplete').at(-1)).toMatchObject({ prefix: 'E' });

    // A stale row is offered and says so, because a researcher may well want to write
    // about one; it is simply marked (conversation spec §7).
    const option = await screen.findByRole('option', { name: /a nine percent drop/ });
    expect(screen.getByRole('option', { name: /throughput rose by four percent/ })).toHaveTextContent(
      'Stale',
    );

    await user.click(option);

    // The token is structured: an object id, not text that looks like one.
    const tokens = await screen.findByRole('list', { name: 'References in this message' });
    expect(within(tokens).getByText(/E0482/)).toBeInTheDocument();

    // It is resolved against canonical state before the send, and the send carries the
    // exact id the resolver answered for.
    await waitFor(() => expect(requests(daemon, 'graph.resolve')).toContainEqual({ reference: 'E0482' }));
    await user.click(screen.getByRole('button', { name: 'Send' }));
    await waitFor(() => expect(requests(daemon, 'session.send').length).toBe(1));
    expect(requests(daemon, 'session.send')[0]).toMatchObject({
      session: SESSION,
      references: ['E0482'],
    });
  });

  it('is reachable and usable from the keyboard alone', async () => {
    const daemon = withGraph(fakeDaemon({ capabilities: answers() }), {
      resolve: { E0482: resolveEvidence },
    });
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();

    // No pointer from here on: type the trigger, arrow into the list, choose with Enter.
    await user.click(screen.getByRole('textbox', { name: 'Message' }));
    await user.keyboard('@');
    const search = await screen.findByRole('combobox', { name: 'Insert a research reference' });
    expect(search).toHaveFocus();
    await screen.findByRole('option', { name: /a nine percent drop/ });
    await user.keyboard('{ArrowDown}{Enter}');

    const tokens = await screen.findByRole('list', { name: 'References in this message' });
    expect(within(tokens).getByText(/E0482/)).toBeInTheDocument();
    // Focus returns to the words, so typing continues where it left off.
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveFocus();
  });

  it('has no accessibility violations with the picker open', async () => {
    const daemon = withGraph(fakeDaemon({ capabilities: answers() }), { resolve: {} });
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();

    await user.type(screen.getByRole('textbox', { name: 'Message' }), '@');
    await screen.findByRole('combobox', { name: 'Insert a research reference' });
    await screen.findByRole('option', { name: /a nine percent drop/ });
    await expectNoAxeViolations();
  });
});

/* -- conversation spec §7: marked before sending --------------------------- */

describe('a token the resolver objected to', () => {
  it('marks unresolved, stale and private references, and still sends them', async () => {
    const daemon = withGraph(
      fakeDaemon({ capabilities: answers({ 'session.send': sendStarted }) }),
      {
        resolve: { E9999: resolveUnresolved, E0500: resolveStale, M0009: resolvePrivate },
      },
    );
    // A draft as a researcher left it: three references, none of them clean.
    window.localStorage.setItem(
      draftKey(SESSION),
      JSON.stringify({
        text: 'Check these before I write them up.',
        tokens: [
          { id: 'E9999', kind: 'evidence', resolution: 'resolved' },
          { id: 'E0500', kind: 'evidence', resolution: 'resolved' },
          { id: 'M0009', kind: 'message', resolution: 'resolved' },
        ],
      }),
    );
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();

    const marks = await screen.findByRole('region', {
      name: 'References to check before sending',
    });
    await waitFor(() => expect(within(marks).getByText('Unresolved')).toBeInTheDocument());
    // "Stale" twice on the same chip is right: the object's authority and the resolution
    // are different statements, and both are shown as words.
    expect(within(marks).getAllByText('Stale').length).toBeGreaterThan(0);
    expect(within(marks).getAllByText('Private').length).toBeGreaterThan(0);
    // The daemon's own sentence, printed as it came.
    expect(within(marks).getByText(/anchor text_hash no longer matches/)).toBeInTheDocument();

    // Flagged is not blocked: Send is live and carries every id.
    const send = screen.getByRole('button', { name: 'Send' });
    expect(send).toBeEnabled();
    await user.click(send);
    await waitFor(() => expect(requests(daemon, 'session.send').length).toBe(1));
    expect(requests(daemon, 'session.send')[0]).toMatchObject({
      references: ['E9999', 'E0500', 'M0009'],
    });
  });
});

/* -- plan §0.1: deep links resolve before they navigate -------------------- */

describe('an `rh://` link in a message', () => {
  it('opens an artifact at the exact page and block', async () => {
    const daemon = withGraph(
      fakeDaemon({
        capabilities: answers(),
        gets: { '/blocks/A0017-3': blocksA0017 },
      }),
      { resolve: { 'rh://artifact/A0017-3?page=6&block=B0081': resolveArtifact } },
    );
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();

    await user.click(screen.getByRole('link', { name: 'page 6, block B0081' }));

    // The exact block, on its own page, from the artifact's stored parse.
    await screen.findByText(/Page 6, block B0081/);
    expect(screen.getByText('A0017-3 · p.6 · B0081')).toBeInTheDocument();
    expect(screen.getByText(/lowered p99 latency by nine percent/)).toBeInTheDocument();
  });

  it('lands a session link on the message it names', async () => {
    const daemon = withGraph(fakeDaemon({ capabilities: answers() }), {
      resolve: { 'rh://session/CS0001?message=M0042': resolveSession },
    });
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();

    await user.click(screen.getByRole('link', { name: 'an earlier turn' }));
    // The inspector follows the turn the link named.
    expect(await screen.findByText('M0042', { selector: '.rh-research-inspector__following-label' }))
      .toBeInTheDocument();
  });

  it('opens the manuscript at the file and the line', async () => {
    const daemon = withGraph(
      fakeDaemon({
        capabilities: answers({
          'manuscript.files': manuscriptFiles,
          'manuscript.build': manuscriptBuild,
          'manuscript.read_file': manuscriptMain,
        }),
      }),
      { resolve: { 'rh://manuscript/main.tex?line=120': resolveManuscript } },
    );
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();

    await user.click(screen.getByRole('link', { name: 'main.tex' }));

    // The workspace reads `?file=` and `?line=` and opens that file at that position.
    await waitFor(() =>
      expect(requests(daemon, 'manuscript.read_file')).toContainEqual({ path: 'main.tex' }),
    );
    expect(await screen.findByRole('tree', { name: 'Manuscript files' })).toBeInTheDocument();
  });

  it('explains a broken link instead of navigating somewhere plausible', async () => {
    const daemon = withGraph(fakeDaemon({ capabilities: answers() }), {
      resolve: { 'rh://artifact/A0099-9?page=6&block=B0081': resolveBroken },
    });
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();

    await user.click(screen.getByRole('link', { name: 'A0099-9' }));

    // The daemon's own sentence, and no navigation: the transcript is still on screen.
    expect(await screen.findByText(/no artifact A0099-9 in project tail-latency/)).toBeInTheDocument();
    expect(screen.getByText(/Yes at the corpus level/)).toBeInTheDocument();
    // Nothing to open: the object does not exist, so no "Open anyway" is offered.
    expect(screen.queryByRole('button', { name: 'Open anyway' })).not.toBeInTheDocument();
  });
});

/* -- §11.2 and §11.3: traversal in both directions, candidates stay candidate */

describe('the inspector’s graph pane', () => {
  const claimScript: GraphScript = {
    resolve: { C0001: resolveEvidence, E0482: resolveEvidence },
    neighbours: { C0001: neighboursClaim, E0482: neighboursEvidence },
    provenance: { C0001: provenanceClaim, E0482: provenanceNone },
  };

  /**
   * Open the Claim the first message references, on the tab that shows the graph.
   *
   * `openRef` takes a Claim chip to the Claims tab (task W1's choice, and the right one for
   * a chip in a message); the graph pane lives on Context, so this is the researcher's own
   * second click.
   */
  async function openTheClaim(user: ReturnType<typeof userEvent.setup>): Promise<void> {
    await transcriptReady();
    await user.click(await screen.findByRole('link', { name: /C0001/ }));
    await user.click(screen.getByRole('tab', { name: /Context/ }));
  }

  it('walks Claim → supporting and contradicting Evidence → the exact artifact anchor', async () => {
    const daemon = withGraph(fakeDaemon({ capabilities: answers() }), claimScript);
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await openTheClaim(user);

    // The provenance path, step by step, with the relation between each pair.
    const path = await screen.findByRole('navigation', { name: 'Provenance of C0001' });
    expect(within(path).getByText('E0482')).toBeInTheDocument();
    expect(within(path).getByText('supports')).toBeInTheDocument();
    expect(within(path).getByText('anchored at')).toBeInTheDocument();
    expect(within(path).getByText('A0017-3')).toBeInTheDocument();
    // And the exact place it ended.
    expect(screen.getByText('A0017-3 · p.6 · B0081 · chars 418–512')).toBeInTheDocument();

    // Both relations, in the researcher's words, in the direction they were followed.
    expect(screen.getByText('Supported by')).toBeInTheDocument();
    expect(screen.getByText('Contradicted by')).toBeInTheDocument();
  });

  it('labels a model-proposed relation candidate and never shows it as accepted', async () => {
    const daemon = withGraph(fakeDaemon({ capabilities: answers() }), claimScript);
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await openTheClaim(user);

    const contradicting = (await screen.findByText('Contradicted by')).parentElement!;
    expect(within(contradicting).getByText('E0555')).toBeInTheDocument();
    expect(within(contradicting).getByText('proposed by a model, not reviewed')).toBeInTheDocument();

    // The two badges on the row are about different things and both are right: the chip
    // carries the *object's* authority — E0555 is accepted Evidence — and the relation
    // carries its own, which is `candidate` and is introduced by the words "this relation
    // is". The relation is never labelled accepted.
    const relation = contradicting.querySelector('.rh-web-graph__authority [data-authority]');
    expect(relation).toHaveAttribute('data-authority', 'candidate');
    expect(relation).toHaveTextContent('Candidate');
    expect(within(contradicting).getByText('this relation is')).toBeInTheDocument();

    // And the accepted relation on the same pane is labelled accepted, so the difference is
    // visible rather than implied.
    const supporting = screen.getByText('Supported by').parentElement!;
    expect(supporting.querySelector('.rh-web-graph__authority [data-authority]')).toHaveAttribute(
      'data-authority',
      'accepted',
    );
  });

  it('walks back from the Evidence to the Claim', async () => {
    const daemon = withGraph(fakeDaemon({ capabilities: answers() }), claimScript);
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await openTheClaim(user);

    const supporting = (await screen.findByText('Supported by')).parentElement!;
    await user.click(within(supporting).getByRole('link', { name: /E0482/ }));

    // The pane now follows E0482, and the Claim is one hop out of it.
    await waitFor(() =>
      expect(requests(daemon, 'graph.neighbors')).toContainEqual(
        expect.objectContaining({ id: 'E0482' }),
      ),
    );
    expect(await screen.findByText('Supports')).toBeInTheDocument();
  });

  it('reaches the graph pane and its neighbours from the keyboard', async () => {
    const daemon = withGraph(fakeDaemon({ capabilities: answers() }), claimScript);
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();
    await user.click(await screen.findByRole('link', { name: /C0001/ }));

    // The inspector's tabs are a manual-activation tablist: arrow to Context, activate it.
    const claims = screen.getByRole('tab', { name: /Claims/ });
    claims.focus();
    await user.keyboard('{ArrowLeft}{ArrowLeft}{Enter}');
    expect(screen.getByRole('tab', { name: /Context/ })).toHaveAttribute('aria-selected', 'true');

    // Every neighbour is a real control, so tabbing reaches one and Enter follows it.
    const supporting = (await screen.findByText('Supported by')).parentElement!;
    const evidence = within(supporting).getByRole('link', { name: /E0482/ });
    evidence.focus();
    expect(evidence).toHaveFocus();
    await user.keyboard('{Enter}');
    await waitFor(() =>
      expect(requests(daemon, 'graph.neighbors')).toContainEqual(
        expect.objectContaining({ id: 'E0482' }),
      ),
    );
  });

  it('has no accessibility violations on the inspector tabs', async () => {
    const daemon = withGraph(fakeDaemon({ capabilities: answers() }), claimScript);
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await openTheClaim(user);
    await screen.findByRole('navigation', { name: 'Provenance of C0001' });
    // `heading-order` is on. The pane used to start its sections at `h3` under a page whose
    // `h1` is the session title, so every panel reported the same h1 → h3 step; the sections
    // are `h2` now (wave 2H), which is what a pane beside the transcript is.
    await expectNoAxeViolations(document.body);

    await user.click(screen.getByRole('tab', { name: /Claims/ }));
    await expectNoAxeViolations(document.body);
  });
});

/* -- §11.5 and graph spec §8: privacy is the graph's answer, not the client's */

describe('privacy during traversal', () => {
  it('asks for the session’s egress class and renders exactly what comes back', async () => {
    // A project-visible session: the walk may only enter project-visible nodes.
    const projectSessions = {
      ...sessions,
      sessions: sessions.sessions.map((session) => ({ ...session, visibility: 'project' })),
    };
    const projectTranscript = {
      ...transcript,
      session: { ...transcript.session, visibility: 'project' },
    };
    const daemon = withGraph(
      fakeDaemon({
        capabilities: answers({
          'session.list': projectSessions,
          'session.get': projectTranscript,
        }),
      }),
      {
        resolve: { C0001: resolveEvidence },
        neighbours: { C0001: neighboursProject },
        provenance: { C0001: provenanceClaim },
      },
    );
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();
    await user.click(await screen.findByRole('link', { name: /C0001/ }));
    await user.click(screen.getByRole('tab', { name: /Context/ }));

    await waitFor(() => expect(requests(daemon, 'graph.neighbors').length).toBeGreaterThan(0));
    expect(requests(daemon, 'graph.neighbors')[0]).toMatchObject({
      id: 'C0001',
      hops: 1,
      direction: 'both',
      visibility: ['project'],
    });

    // The private prior-session message is simply not in the answer, and nothing on this
    // side puts it back.
    const mentioned = (await screen.findByText('Mentioned in messages')).parentElement!;
    expect(within(mentioned).getByText('M0031')).toBeInTheDocument();
    expect(within(mentioned).queryByText('M0009')).not.toBeInTheDocument();
    expect(screen.queryByText('M0009')).not.toBeInTheDocument();
  });

  it('asks for everything on this machine inside a private session', async () => {
    const daemon = withGraph(fakeDaemon({ capabilities: answers() }), {
      resolve: { C0001: resolveEvidence },
      neighbours: { C0001: neighboursClaim },
      provenance: { C0001: provenanceClaim },
    });
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();
    await user.click(await screen.findByRole('link', { name: /C0001/ }));
    await user.click(screen.getByRole('tab', { name: /Context/ }));

    await waitFor(() => expect(requests(daemon, 'graph.neighbors').length).toBeGreaterThan(0));
    expect(requests(daemon, 'graph.neighbors')[0]).not.toHaveProperty('visibility');
    // A private session sees its own working context, because it never leaves the machine.
    const mentioned = (await screen.findByText('Mentioned in messages')).parentElement!;
    expect(within(mentioned).getByText('M0009')).toBeInTheDocument();
  });
});

/* -- graph spec §8: direct canonical reads when the graph cannot answer ----- */

/** `state.rebuild`'s own report, trimmed to the fields the cockpit never reads. */
const rebuildDone = {
  ok: true,
  objects: 41,
  objects_by_type: { claim: 6, evidence: 12 },
  stale_marks: 0,
  fts_rows: 41,
  canonical_digest: 'sha256:6f1cd0a2',
  duration_ms: 812,
  invalid_files: [],
  summary: '41 objects, 0 stale marks in 812 ms',
};

/** A refusal is the daemon's sentence, and the cockpit may not paraphrase it. */
const REFUSAL =
  'state.rebuild is an admin capability and this token is not the researcher; run ' +
  '`research rebuild` in the workspace instead.';

describe('when the graph is not answering', () => {
  it('falls back to the project listings and says so, once, in the composer', async () => {
    const daemon = withGraph(
      fakeDaemon({ capabilities: answers({ 'graph.status': statusRebuilding }) }),
      { resolve: {} },
    );
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();

    // The demoted line: one sentence beside the destination, not a framed notice above the
    // box. It still names the state the daemon reported and what is answering instead — and
    // the capability that is answering is on the element rather than in the sentence,
    // because `state.index` is not a word a researcher reads (2E).
    const line = await screen.findByText(/Rebuilding the research index/);
    expect(screen.getAllByText(/Rebuilding the research index/)).toHaveLength(1);
    expect(line).toHaveTextContent('completing from the project listings');
    expect(line.closest('.rh-web-graph-note')).toHaveAttribute('data-answering', 'state.index');
    expect(line.closest('.rh-composer')).not.toBeNull();

    // Completion still works, from the listings, and the graph is not asked.
    await user.type(screen.getByRole('textbox', { name: 'Message' }), '@');
    const search = await screen.findByRole('combobox', { name: 'Insert a research reference' });
    await user.type(search, 'C0001');
    expect(await screen.findByRole('option', { name: /TrafficLM reaches an F1/ })).toBeInTheDocument();
    expect(requests(daemon, 'graph.autocomplete')).toHaveLength(0);
  });

  it('falls back when `graph.status` itself cannot be read', async () => {
    const capabilities = answers();
    delete capabilities['graph.status'];
    const daemon = withGraph(fakeDaemon({ capabilities }), { resolve: {} });
    renderCockpit({ daemon });
    await transcriptReady();

    expect(
      await screen.findByText(/The research index is not answering/),
    ).toBeInTheDocument();
  });

  it('says a rebuild is in progress only while one actually is', async () => {
    const daemon = withGraph(
      fakeDaemon({ capabilities: answers({ 'graph.status': statusRebuilding }) }),
      { resolve: {} },
    );
    renderCockpit({ daemon });
    await transcriptReady();

    const note = (await screen.findByText(/Rebuilding the research index/)).closest(
      '.rh-web-graph-note',
    )!;
    // The bar and the frame went with the demotion; what a rebuild in flight still owes the
    // reader is that it *is* in flight, and the note says so in words and to the live region.
    expect(note).toHaveAttribute('data-degradation', 'rebuilding');
    expect(note).toHaveAttribute('aria-busy', 'true');
    expect(within(note as HTMLElement).queryByRole('progressbar')).toBeNull();
  });

  it('does not dress an index that was never built as one being built', async () => {
    const daemon = withGraph(
      fakeDaemon({ capabilities: answers({ 'graph.status': statusAbsent }) }),
      { resolve: {} },
    );
    renderCockpit({ daemon });
    await transcriptReady();

    const note = (await screen.findByText(/The research index is not built yet/)).closest(
      '.rh-web-graph-note',
    )!;
    // The Windows report: a spinner, LOADING and an "Index rebuild" bar, with nothing running.
    expect(note).toHaveAttribute('data-degradation', 'absent');
    expect(note).not.toHaveAttribute('aria-busy');
    expect(within(note as HTMLElement).queryByRole('progressbar')).toBeNull();
    expect(note).not.toHaveTextContent('Loading');
    expect(note).not.toHaveTextContent('Rebuilding');
    expect(note).toHaveTextContent('completing from the project listings');
  });

  it('runs the rebuild its own wording asks for, and the notice goes when the index is there', async () => {
    const capabilities = answers({ 'graph.status': statusAbsent, 'state.rebuild': rebuildDone });
    const daemon = withGraph(fakeDaemon({ capabilities }), { resolve: {} });
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();
    await screen.findByText(/The research index is not built yet/);

    // The rebuild the daemon is about to run is the one that makes the index answer.
    capabilities['graph.status'] = statusAvailable;
    await user.click(screen.getByRole('button', { name: 'Rebuild the index' }));

    await waitFor(() =>
      expect(screen.queryByText(/The research index is not built yet/)).toBeNull(),
    );
    const names = daemon.capabilityCalls().map((call) => call.name);
    const rebuiltAt = names.indexOf('state.rebuild');
    expect(rebuiltAt).toBeGreaterThanOrEqual(0);
    // The status is read again afterwards; the notice does not simply hide itself.
    expect(names.slice(rebuiltAt + 1)).toContain('graph.status');
  });

  it('offers no rebuild in a window that may not write', async () => {
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    const daemon = withGraph(
      fakeDaemon({
        gets: { '/overview': asHost },
        capabilities: answers({ 'graph.status': statusAbsent, 'state.rebuild': rebuildDone }),
      }),
      { resolve: {} },
    );
    renderCockpit({ daemon });
    await transcriptReady();

    const note = (await screen.findByText(/The research index is not built yet/)).closest(
      '.rh-web-graph-note',
    )!;
    expect(
      within(note as HTMLElement).getByRole('button', { name: 'Check again' }),
    ).toBeInTheDocument();
    expect(
      within(note as HTMLElement).queryByRole('button', { name: 'Rebuild the index' }),
    ).toBeNull();
  });

  it('renders the daemon’s own sentence when a rebuild is refused, and keeps the notice', async () => {
    const refusal = {
      capability: 'state.rebuild',
      ok: false,
      error: { code: 'permission_denied', message: REFUSAL },
    };
    const daemon = withGraph(
      fakeDaemon({
        capabilities: answers({ 'graph.status': statusAbsent, 'state.rebuild': refusal }),
      }),
      { resolve: {} },
    );
    const user = userEvent.setup();
    renderCockpit({ daemon });
    await transcriptReady();
    await screen.findByText(/The research index is not built yet/);

    await user.click(screen.getByRole('button', { name: 'Rebuild the index' }));

    expect(await screen.findByText(REFUSAL)).toBeInTheDocument();
    // Nothing was built, so the note is still the truth about the index.
    expect(screen.getByText(/The research index is not built yet/)).toBeInTheDocument();
  });

  it('has no accessibility violations with the rebuild offered', async () => {
    const daemon = withGraph(
      fakeDaemon({
        capabilities: answers({ 'graph.status': statusAbsent, 'state.rebuild': rebuildDone }),
      }),
      { resolve: {} },
    );
    const { container } = renderCockpit({ daemon });
    await transcriptReady();
    await screen.findByRole('button', { name: 'Rebuild the index' });

    await expectNoAxeViolations(container);
  });
});
