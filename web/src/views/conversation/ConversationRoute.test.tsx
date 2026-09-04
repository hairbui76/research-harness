/**
 * The conversation workspace, against a fake daemon and a scripted run.
 *
 * Each `describe` below is one of the acceptance scenarios of the conversation spec §10,
 * driven the way a researcher drives it: through the real route table, the real shell, and
 * the real client — the only fakes are `fetch` and the run's event stream.
 *
 * Two things these tests are deliberately strict about. The transcript on disk is always
 * the answer: every terminal state, every interruption and every stop is followed by a
 * `session.get`, and what is on screen afterwards is what that read returned. And the
 * draft is never collateral damage: a refusal, a failure and a remount all leave the
 * researcher's words exactly where they were.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@research-harness/design';
import { HarnessClient } from '../../api/client';
import { SessionProvider } from '../../app/session';
import { AppRoutes } from '../../app/routes';
import { FIXTURES, expectNoAxeViolations, fakeDaemon } from '../../test/harness';
import type { FakeDaemon } from '../../test/harness';
import contextPack from '../../test/fixtures/conversation/context-pack.json';
import promotion from '../../test/fixtures/conversation/promotion.json';
import providers from '../../test/fixtures/conversation/providers.json';
import sendStarted from '../../test/fixtures/conversation/send-started.json';
import sessions from '../../test/fixtures/conversation/sessions.json';
import cliScan from '../../test/fixtures/providers/cli-scan.json';
import transcript from '../../test/fixtures/conversation/transcript.json';
import incompleteTranscript from '../../test/fixtures/conversation/transcript-incomplete.json';
import attachmentTranscript from '../../test/fixtures/conversation/transcript-attachment.json';
import { draftKey } from './useDraft';

/* -- the fake daemon, plus a run to listen to ------------------------------ */

const SESSION = 'CS0001';
const ROUTE = `/?session=${SESSION}`;

/** One SSE frame, exactly as `server/routes_sessions.py::sse_frame` writes it. */
function frame(event: string, payload: Record<string, unknown>): string {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
}

const delta = (text: string, messageId = 'M0043') =>
  frame('delta', { message_id: messageId, attempt: 1, text });

const status = (state: string, extra: Record<string, unknown> = {}) =>
  frame('status', {
    run_id: 'run_5f3c1a',
    state,
    message_id: 'M0043',
    attempt: 1,
    context_pack_id: 'CP0008',
    ...extra,
  });

/**
 * A body that yields these chunks.
 *
 * `open: true` leaves the stream running afterwards, which is what a run still working
 * looks like: the client is waiting, Stop is offered, and only an abort or a terminal
 * status ends it. Closing without a terminal status is the other real case — the
 * connection dropped — and the client reconciles rather than inventing an ending.
 */
function streamOf(chunks: string[], open = false): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      if (!open) controller.close();
    },
  });
}

/**
 * The fake daemon plus `GET /runs/{id}/events`.
 *
 * The run route is not a capability, so it is layered over `fakeDaemon` here rather than
 * added to the shared harness: a scripted stream belongs to the test that scripts it.
 */
function withRun(daemon: FakeDaemon, chunks: string[], open = false): FakeDaemon {
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(String(input), 'http://daemon.test');
    if (url.pathname.startsWith('/runs/') && url.pathname.endsWith('/events')) {
      daemon.calls.push({ method: 'GET', path: url.pathname, body: null });
      return new Response(streamOf(chunks, open), {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      });
    }
    return daemon.fetch(input, init);
  };
  return { ...daemon, fetch: fetchImpl as unknown as typeof fetch };
}

interface Answers {
  [capability: string]: unknown;
}

/** Everything the conversation reads, with sensible defaults each test can override. */
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
    ...extra,
  };
}

function renderConversation(options: {
  daemon: FakeDaemon;
  token?: string | null;
  route?: string;
}) {
  const client = new HarnessClient({
    baseUrl: 'http://daemon.test',
    token: options.token === undefined ? 'local-token' : options.token,
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

/**
 * The transcript is on screen once the session's first answer is.
 *
 * Matched on a run of plain prose rather than on the whole sentence: the answer is
 * Markdown, so `**C0001**` is its own element and the sentence spans several text nodes.
 */
async function transcriptReady(): Promise<void> {
  await screen.findByText(/records the accepted claim/, undefined, { timeout: 3000 });
}

beforeEach(() => {
  window.localStorage.clear();
});

/* -- §10.1 reopen and continue -------------------------------------------- */

describe('reopening a session', () => {
  it('restores the transcript the URL names, and says it is private', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    renderConversation({ daemon });

    await transcriptReady();
    expect(screen.getByRole('heading', { name: 'Latency study' })).toBeInTheDocument();
    // Both turns are there, oldest first, with their stable ids.
    expect(screen.getByText('M0041')).toBeInTheDocument();
    expect(screen.getByText('M0042')).toBeInTheDocument();
    // Conversation data is private by default and the workspace keeps saying so.
    expect(screen.getAllByText('Private').length).toBeGreaterThan(0);

    const read = daemon.capabilityCalls().find((call) => call.name === 'session.get');
    expect(read?.request).toMatchObject({ session: SESSION });
  });

  it('takes a session picked from a research page back to the conversation', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    const user = userEvent.setup();
    renderConversation({ daemon, route: '/claims' });

    // The rail carries the history on every screen.
    await screen.findByRole('button', { name: /^Screening pass/ });
    await user.click(screen.getByRole('button', { name: /^Screening pass/ }));

    // Choosing a conversation goes to the conversation, not to a claims page with a query.
    await screen.findByRole('heading', { name: 'Screening pass' });
  });

  it('creates a session and opens it, letting the daemon name it', async () => {
    const created = {
      ...sessions.sessions[0],
      id: 'CS0003',
      title: 'New session',
      message_count: 0,
      last_message: null,
      last_message_at: null,
    };
    const daemon = fakeDaemon({
      capabilities: answers({ 'session.create': { session: created } }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    await user.click(screen.getByRole('button', { name: 'New session' }));

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().find((call) => call.name === 'session.create')?.request,
      ).toMatchObject({ title: 'New session' }),
    );
    // No id was posted; the one the daemon named is the one the URL now carries.
    await waitFor(() =>
      expect(
        daemon.capabilityCalls().some((call) => call.request?.session === 'CS0003'),
      ).toBe(true),
    );
  });

  it('renames a session without touching its transcript', async () => {
    const renamed = { ...sessions.sessions[0], title: 'Tail latency' };
    const daemon = fakeDaemon({
      capabilities: answers({ 'session.rename': { session: renamed } }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    await user.click(screen.getByRole('button', { name: 'Rename Latency study' }));
    const field = await screen.findByRole('textbox', { name: 'Rename Latency study' });
    await user.clear(field);
    await user.type(field, 'Tail latency{Enter}');

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().find((call) => call.name === 'session.rename')?.request,
      ).toMatchObject({ session: SESSION, title: 'Tail latency' }),
    );
    // The transcript is where it was: renaming is a title and nothing else.
    expect(screen.getByText(/records the accepted claim/)).toBeInTheDocument();
  });

  it('reopens the session this project was last in when the URL names none', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    window.localStorage.setItem(
      `research-harness.conversation.last-session.${FIXTURES.overview.workspace}`,
      'CS0002',
    );
    renderConversation({ daemon, route: '/' });

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().some((call) => call.request?.session === 'CS0002'),
      ).toBe(true),
    );
  });
});

/* -- §10.2 / §10.3 / §10.6 the receipt ------------------------------------ */

describe('Context used', () => {
  it('lists the accepted evidence and the prior-session excerpt that were sent', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    await user.click(screen.getByRole('button', { name: 'Context used (CP0007)' }));

    const inspector = await screen.findByRole('region', { name: 'Research inspector' });
    await within(inspector).findByText('Context used');
    // Accepted state, and a relevant excerpt from an earlier session, both named.
    expect(within(inspector).getByText('E0482')).toBeInTheDocument();
    expect(within(inspector).getAllByText('M0009').length).toBeGreaterThan(0);
    // The class is named in words wherever it appears: the allocation and the group heading.
    expect(within(inspector).getAllByText('Prior sessions').length).toBeGreaterThan(0);
    // The receipt is read from the pack the message recorded, not recomputed.
    expect(
      daemon.capabilityCalls().find((call) => call.name === 'context.get')?.request,
    ).toMatchObject({ session: SESSION, pack: 'CP0007' });
  });

  it('shows a private omission with the daemon’s own reason', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    await user.click(screen.getByRole('button', { name: 'Context used (CP0007)' }));
    const inspector = await screen.findByRole('region', { name: 'Research inspector' });

    await within(inspector).findByText('Privacy policy');
    expect(
      within(inspector).getByText(
        'This session is private and the selected model is external, so it stayed local.',
      ),
    ).toBeInTheDocument();
    // The reason is a word, not a colour.
    expect(within(inspector).getByText('Token budget')).toBeInTheDocument();
  });

  it('shows the discrepancy where accepted state outranked the conversation', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    await user.click(screen.getByRole('button', { name: 'Context used (CP0007)' }));
    const inspector = await screen.findByRole('region', { name: 'Research inspector' });

    await within(inspector).findByText('Accepted state was used');
    expect(within(inspector).getByText('Accepted — sent to the model')).toBeInTheDocument();
    expect(
      within(inspector).getByText(/Accepted scientific state outranks remembered conversation/),
    ).toBeInTheDocument();
  });

  it('previews a draft without persisting a pack', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'what about p50?');
    await user.click(screen.getByRole('button', { name: 'Preview context' }));

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().find((call) => call.name === 'context.preview')?.request,
      ).toMatchObject({ session: SESSION, text: 'what about p50?', persist: false }),
    );
  });
});

/* -- §10.4 / §10.5 promotion ---------------------------------------------- */

describe('promotion', () => {
  async function openPromotion(daemon: FakeDaemon) {
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();
    // The second Promote button is the assistant's answer; the first is the question.
    const buttons = screen.getAllByRole('button', { name: 'Promote this message' });
    await user.click(buttons[1] as HTMLElement);
    await user.click(await screen.findByRole('menuitem', { name: 'Claim candidate' }));
    return { user, dialog: await screen.findByRole('dialog', { name: /Promote this message/ }) };
  }

  it('promotes an excerpt to a claim candidate with subject, predicate and object', async () => {
    const daemon = fakeDaemon({ capabilities: answers({ 'session.promote': promotion }) });
    const { user, dialog } = await openPromotion(daemon);

    await user.type(within(dialog).getByLabelText('Subject'), 'batching');
    await user.type(within(dialog).getByLabelText('Predicate'), 'reduces');
    await user.type(within(dialog).getByLabelText('Object'), 'tail latency');
    await user.click(within(dialog).getByRole('button', { name: 'Promote' }));

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().find((call) => call.name === 'session.promote')?.request,
      ).toMatchObject({
        session: SESSION,
        message: 'M0042',
        target: 'claim_candidate',
        subject: 'batching',
        predicate: 'reduces',
        object: 'tail latency',
      }),
    );
    // The toast names what was created and says it was not accepted.
    await screen.findByText('Claim candidate created: C0002');
    expect(
      screen.getByText(/enters the review queue; nothing was accepted/),
    ).toBeInTheDocument();
  });

  it('does not offer Evidence, and says why', async () => {
    const daemon = fakeDaemon({ capabilities: answers({ 'session.promote': promotion }) });
    const { dialog } = await openPromotion(daemon);

    const targets = within(dialog).getByLabelText('Promote to') as HTMLSelectElement;
    expect(Array.from(targets.options).map((option) => option.value)).toEqual([
      'note',
      'question',
      'claim_candidate',
      'decision_candidate',
    ]);
    expect(
      within(dialog).getByText('Evidence cannot be promoted from prose'),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/exact, resolvable source anchor/)).toBeInTheDocument();
  });

  it('shows the provenance it will record', async () => {
    const daemon = fakeDaemon({ capabilities: answers({ 'session.promote': promotion }) });
    const { dialog } = await openPromotion(daemon);

    const provenance = within(dialog).getByText('Provenance').closest('.rh-web-field');
    expect(provenance?.textContent).toContain(SESSION);
    expect(provenance?.textContent).toContain('M0042');
  });
});

/* -- §10.7 two-way navigation --------------------------------------------- */

describe('references', () => {
  it('opens an @E#### token in the inspector and gets back to the message', async () => {
    const daemon = fakeDaemon({
      capabilities: answers({
        'evidence.list': {
          count: 1,
          evidence: [
            {
              id: 'E0482',
              work: 'W0001',
              artifact: 'A0001-1',
              field: 'latency',
              status: 'accepted',
              origin: 'reported',
              evidence_type: 'numeric',
              strength: 'strong',
              review_tier: 1,
              verdict: 'supported',
              exact_text: 'a nine percent tail latency drop under batching',
              qualification: null,
              stale: 'fresh',
            },
          ],
        },
      }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    // Forwards: the token in the message opens the object.
    await user.click(screen.getByRole('link', { name: /E0482/ }));

    const inspector = await screen.findByRole('region', { name: 'Research inspector' });
    await waitFor(() =>
      expect(within(inspector).getByText(/Following reference/)).toBeInTheDocument(),
    );
    expect(
      within(inspector).getByText('E0482 — tail latency drop under batching'),
    ).toBeInTheDocument();
    // And the way out to the object's own page is offered, not taken for us.
    expect(within(inspector).getByRole('button', { name: 'Open reference' })).toBeInTheDocument();

    // Backwards: the object lists the messages that used it.
    await within(inspector).findByText('Where E0482 was used');
    await user.click(within(inspector).getByRole('button', { name: /M0041 · user/ }));

    await waitFor(() =>
      expect(within(inspector).getByText('M0041')).toBeInTheDocument(),
    );
    expect(document.querySelector('.rh-message.is-selected')?.getAttribute('data-message-id')).toBe(
      'M0041',
    );
  });

  it('completes an @ token from the project index and sends it as a reference', async () => {
    const daemon = fakeDaemon({
      capabilities: answers({ 'session.send': sendStarted }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon: withRun(daemon, [status('succeeded')]) });
    await transcriptReady();

    const box = screen.getByRole('textbox', { name: 'Message' });
    await user.type(box, 'compare with @C0001');
    const option = await screen.findByRole('option', { name: /C0001/ });
    await user.click(option);

    // The token is a structured object beside the prose, not text inside it.
    await screen.findByRole('list', { name: 'References in this message' });
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().find((call) => call.name === 'session.send')?.request,
      ).toMatchObject({ session: SESSION, references: ['C0001'] }),
    );
  });
});

/* -- §8 sending, streaming, stopping, failing ----------------------------- */

describe('sending', () => {
  it('streams the answer and then reconciles from the transcript on disk', async () => {
    const capabilities = answers({ 'session.send': sendStarted });
    const daemon = withRun(fakeDaemon({ capabilities }), [
      status('running'),
      delta('Under batching '),
      delta('the tail flattens.'),
      status('succeeded'),
    ]);
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    // The reconciliation read is what the researcher ends up looking at.
    capabilities['session.get'] = incompleteTranscript;
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'and at p50?');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText('Under batching the tail flattens across the whole corpus.');
    expect(daemon.calls.some((call) => call.path === '/runs/run_5f3c1a/events')).toBe(true);
    // Focus goes back to the box, so a keyboard user keeps typing.
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveFocus();
  });

  it('keeps a partial answer, marks it incomplete, and offers a retry', async () => {
    const capabilities = answers({ 'session.send': sendStarted });
    // The stream stops without a terminal status: the connection dropped.
    const daemon = withRun(fakeDaemon({ capabilities }), [
      status('running'),
      delta('Under batching the tail flattens, but the'),
    ]);
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    capabilities['session.get'] = {
      ...incompleteTranscript,
      messages: [incompleteTranscript.messages[0]],
    };
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'and at p50?');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    // What arrived is kept, and it is not presented as a finished answer.
    await screen.findByText('Incomplete — response was interrupted');
    expect(screen.getByText('Under batching the tail flattens, but the')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Retry this turn' }).length).toBeGreaterThan(0);
  });

  it('makes the attempts of a retried turn navigable', async () => {
    const daemon = fakeDaemon({
      capabilities: answers({ 'session.get': incompleteTranscript }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon });

    // The newest attempt is the one on screen.
    await screen.findByText('Under batching the tail flattens across the whole corpus.');
    expect(screen.getByText('attempt 2 of 2')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Previous attempt' }));
    await screen.findByText('Under batching the tail flattens, but the');
    expect(screen.getByText('attempt 1 of 2')).toBeInTheDocument();
  });

  it('renders a refusal and leaves the draft untouched', async () => {
    const daemon = fakeDaemon({
      capabilities: answers({
        'session.send': {
          capability: 'session.send',
          ok: false,
          error: {
            code: 'egress_blocked',
            message:
              'This session is private and the selected model is external; nothing was sent.',
          },
        },
      }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    const box = screen.getByRole('textbox', { name: 'Message' });
    await user.type(box, 'send this to the vendor');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText(
      'This session is private and the selected model is external; nothing was sent.',
    );
    // The draft is where it was, on screen and on disk.
    expect(box).toHaveValue('send this to the vendor');
    expect(screen.getByText(/Your message and its attachments are untouched/)).toBeInTheDocument();
    expect(window.localStorage.getItem(draftKey(SESSION))).toContain('send this to the vendor');
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();

    // The refusal was about this message; editing it makes another attempt possible.
    await user.type(box, ' locally instead');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Send' })).not.toBeDisabled(),
    );
  });

  it('restores a draft after a remount', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    const user = userEvent.setup();
    const first = renderConversation({ daemon });
    await transcriptReady();
    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'half a thought');
    first.unmount();

    renderConversation({ daemon });
    await transcriptReady();
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('half a thought');
  });

  it('shows the models the daemon offers, unavailable ones included with the reason', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    await user.click(screen.getByRole('button', { name: /^Model:/ }));
    const menu = await screen.findByRole('menu', { name: 'Model' });
    expect(within(menu).getByText('Local small')).toBeInTheDocument();
    expect(within(menu).getByText('Vendor vision')).toBeInTheDocument();
    expect(
      within(menu).getByText(
        'This session is private, so the egress policy will not send it off the machine.',
      ),
    ).toBeInTheDocument();
    // Local or external is stated in words beside every option.
    expect(within(menu).getAllByText('External').length).toBeGreaterThan(0);
  });

  it('shows the answer arriving in a live region before the transcript has it', async () => {
    const capabilities = answers({ 'session.send': sendStarted });
    // The run is still open: this is what the researcher looks at while it writes.
    const daemon = withRun(
      fakeDaemon({ capabilities }),
      [status('running'), delta('Under batching ')],
      true,
    );
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'and at p50?');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    // `session.get` has no M0043 yet; the deltas still have somewhere to arrive.
    await screen.findByText('Under batching');
    const live = document.querySelector('.rh-message-content[data-status="streaming"]');
    expect(live).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByText('Streaming…')).toBeInTheDocument();
  });

  it('says the receipt is unavailable rather than inventing one', async () => {
    const capabilities = answers();
    delete capabilities['context.get'];
    const user = userEvent.setup();
    renderConversation({ daemon: fakeDaemon({ capabilities }) });
    await transcriptReady();

    await user.click(screen.getByRole('button', { name: 'Context used (CP0007)' }));
    const inspector = await screen.findByRole('region', { name: 'Research inspector' });
    await within(inspector).findByText('Receipt unavailable');
  });

  it('stops a running answer through the capability, not by hanging up', async () => {
    const capabilities = answers({
      'session.send': sendStarted,
      'session.stop': { run_id: 'run_5f3c1a', state: 'cancelled' },
    });
    // A stream that keeps running until something stops it.
    const daemon = withRun(fakeDaemon({ capabilities }), [status('running'), delta('Under ')], true);
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'and at p50?');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    const stop = await screen.findByRole('button', { name: 'Stop' });
    await user.click(stop);

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().find((call) => call.name === 'session.stop')?.request,
      ).toMatchObject({ run_id: 'run_5f3c1a' }),
    );
  });

  it('retries an interrupted turn as a new attempt', async () => {
    const daemon = fakeDaemon({
      capabilities: answers({
        'session.get': { ...incompleteTranscript, messages: [incompleteTranscript.messages[0]] },
        'session.retry': sendStarted,
      }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon: withRun(daemon, [status('succeeded')]) });

    await screen.findByText('Incomplete — response was interrupted');
    await user.click(screen.getAllByRole('button', { name: 'Retry this turn' })[0] as HTMLElement);

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().find((call) => call.name === 'session.retry')?.request,
      ).toMatchObject({ message: 'M0043', session: SESSION }),
    );
  });

  it('picks a run back up after a reload, replaying rather than doubling it', async () => {
    const capabilities = answers();
    const daemon = withRun(
      fakeDaemon({ capabilities }),
      [status('running'), delta('Replayed from the start.', 'M0042')],
      true,
    );
    // What a tab that was closed mid-stream left behind.
    window.localStorage.setItem(
      `research-harness.conversation.run.${SESSION}`,
      JSON.stringify({ runId: 'run_5f3c1a', messageId: 'M0042', attempt: 1 }),
    );
    renderConversation({ daemon });

    await screen.findByText('Replayed from the start.');
    expect(daemon.calls.some((call) => call.path === '/runs/run_5f3c1a/events')).toBe(true);
    expect(screen.getAllByText('Replayed from the start.')).toHaveLength(1);
  });

  it('draws an attachment a message already carries', async () => {
    const daemon = fakeDaemon({
      capabilities: answers({ 'session.get': attachmentTranscript }),
    });
    renderConversation({ daemon });

    await screen.findByText('lee-2024-hydrogel-preprint.pdf');
    // The state is a word, and it says the file is working material, not corpus state.
    expect(screen.getAllByText('Session only').length).toBeGreaterThan(0);
    expect(screen.getByText('14 pages')).toBeInTheDocument();
  });

  it('says so in words when the model catalogue is unavailable', async () => {
    const capabilities = answers();
    delete capabilities['provider.list'];
    const daemon = fakeDaemon({ capabilities });
    renderConversation({ daemon });
    await transcriptReady();

    expect(await screen.findByText(/model catalogue is unavailable/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Model:/ })).not.toBeInTheDocument();
  });
});

/* -- PRODUCT §29: an agent host reads and proposes ------------------------ */

describe('an agent host', () => {
  const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };

  it('reads the transcript and cannot send, promote or rename', async () => {
    const daemon = fakeDaemon({
      gets: { '/overview': asHost },
      capabilities: answers(),
    });
    const user = userEvent.setup();
    renderConversation({ daemon, token: null });
    await transcriptReady();

    await user.type(screen.getByRole('textbox', { name: 'Message' }), 'accept this for me');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await screen.findByText(
      'This window may only read and propose, so it cannot send a message.',
    );
    // No capability was called, and the words survive.
    expect(daemon.capabilityCalls().some((call) => call.name === 'session.send')).toBe(false);
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('accept this for me');
    // Session mutations are not offered at all.
    expect(screen.queryByRole('button', { name: 'New session' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Rename / })).not.toBeInTheDocument();
  });

  it('is told why the promotion form cannot be submitted', async () => {
    const daemon = fakeDaemon({ gets: { '/overview': asHost }, capabilities: answers() });
    const user = userEvent.setup();
    renderConversation({ daemon, token: null });
    await transcriptReady();

    const buttons = screen.getAllByRole('button', { name: 'Promote this message' });
    await user.click(buttons[1] as HTMLElement);
    await user.click(await screen.findByRole('menuitem', { name: 'Research note' }));
    const dialog = await screen.findByRole('dialog', { name: /Promote this message/ });

    expect(within(dialog).getByText('This window may not promote')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Promote' })).toBeDisabled();
  });
});


/* -- session runtime binding (binding spec §10, plan rulings 4-6) --------- */

describe('binding the session to a CLI runtime', () => {
  const BOUND = 'CS0002';
  const BOUND_ROUTE = `/?session=${BOUND}`;

  /** The record `session.configure` answers with, bound as the daemon would store it. */
  function boundTo(
    id: string,
    model: { provider: string; model: string } | null,
    reasoning: string | null = null,
  ) {
    const record = sessions.sessions.find((session) => session.id === id);
    return {
      session: { ...record, defaults: { mode: null, token_budget: null, model, reasoning } },
    };
  }

  const withScan = (extra: Answers = {}) => answers({ 'provider.cli.scan': cliScan, ...extra });

  async function openMenu(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByRole('button', { name: /^Model:/ }));
    return screen.findByRole('menu', { name: 'Model' });
  }

  it('lists the configured entries and every installed runtime the scan found', async () => {
    const daemon = fakeDaemon({ capabilities: withScan() });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    const menu = await openMenu(user);
    // The entries the router already has, and one group per installed runtime.
    expect(within(menu).getByText('Configured entries')).toBeInTheDocument();
    const codex = within(menu).getByRole('group', { name: 'Codex CLI 0.150.1' });
    expect(within(codex).getByText('gpt-5.5 (live)')).toBeInTheDocument();

    // A runtime the daemon will not route to is one disabled row carrying its reason.
    const cursor = within(menu).getByRole('group', { name: 'Cursor Agent 1.4.0' });
    expect(
      within(cursor).getByText(
        'cursor-agent 1.4.0 has no tested bounded (no-tools, read-only) mode',
      ),
    ).toBeInTheDocument();
    expect(within(cursor).getAllByRole('menuitem')).toHaveLength(1);

    // A runtime the scan did not find is not offered at all.
    expect(within(menu).queryByRole('group', { name: /^Amp/ })).not.toBeInTheDocument();
  });

  it('discloses the egress before the first binding, then configures the session', async () => {
    const daemon = fakeDaemon({
      capabilities: withScan({
        'session.configure': boundTo(SESSION, { provider: 'local_cli:codex', model: 'gpt-5.5' }),
      }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('menuitem', { name: /gpt-5\.5 \(live\)/ }));

    // The daemon's own notice, before anything is bound.
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText(cliScan.notice)).toBeInTheDocument();
    expect(daemon.capabilityCalls().some((call) => call.name === 'session.configure')).toBe(false);

    await user.click(within(dialog).getByRole('button', { name: 'Use this runtime' }));

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().find((call) => call.name === 'session.configure')?.request,
      ).toEqual({ session: SESSION, runtime: 'codex', model: 'gpt-5.5' }),
    );
    // The value is read back from the record the daemon answered with.
    await screen.findByRole('button', { name: 'Model: gpt-5.5 (live)' });
  });

  it('offers the runtime\'s own reasoning levels and sends the one picked', async () => {
    const daemon = fakeDaemon({
      capabilities: withScan({
        'session.configure': boundTo(
          BOUND,
          { provider: 'local_cli:codex', model: 'gpt-5.5' },
          'low',
        ),
      }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon, route: BOUND_ROUTE });
    await transcriptReady();

    const reasoning = await screen.findByRole('combobox', { name: 'Reasoning' });
    expect(
      Array.from(reasoning.querySelectorAll('option')).map((option) => option.value),
    ).toEqual(['', 'low', 'medium', 'high', 'xhigh']);
    expect(reasoning).toHaveValue('high');

    await user.selectOptions(reasoning, 'low');

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().find((call) => call.name === 'session.configure')?.request,
      ).toEqual({ session: BOUND, runtime: 'codex', model: 'gpt-5.5', reasoning: 'low' }),
    );
  });

  it('asks once per session: a second pick binds without another confirmation', async () => {
    const daemon = fakeDaemon({
      capabilities: withScan({
        'session.configure': boundTo(SESSION, { provider: 'local_cli:codex', model: 'gpt-5.5' }),
      }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('menuitem', { name: /gpt-5\.5 \(live\)/ }));
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Use this runtime' }));
    await screen.findByRole('button', { name: 'Model: gpt-5.5 (live)' });

    const again = await openMenu(user);
    await user.click(within(again).getByRole('menuitem', { name: /gpt-5\.4-mini \(live\)/ }));

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().filter((call) => call.name === 'session.configure'),
      ).toHaveLength(2),
    );
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('shows the stored binding on reopening, in the selector and on the session row', async () => {
    const daemon = fakeDaemon({ capabilities: withScan() });
    renderConversation({ daemon, route: BOUND_ROUTE });
    await transcriptReady();

    await screen.findByRole('button', { name: 'Model: gpt-5.5 (live)' });
    // The rail states the binding in the one format every surface uses.
    expect(screen.getByText('session:codex/gpt-5.5 (reasoning high)')).toBeInTheDocument();
  });

  it('leaves a read-only window the per-message choice and binds nothing', async () => {
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    const daemon = fakeDaemon({ gets: { '/overview': asHost }, capabilities: withScan() });
    const user = userEvent.setup();
    renderConversation({ daemon, token: null, route: BOUND_ROUTE });
    await transcriptReady();

    const menu = await openMenu(user);
    const codex = within(menu).getByRole('group', { name: 'Codex CLI 0.150.1' });
    // Every runtime row carries the session's own mutation-blocked reason.
    expect(
      within(codex).getAllByText(/connected without the local token/).length,
    ).toBeGreaterThan(0);
    expect(within(codex).getByRole('menuitem', { name: /gpt-5\.5 \(live\)/ })).toHaveAttribute(
      'aria-disabled',
      'true',
    );

    // An entry still sets the per-message model, exactly as before.
    await user.click(within(menu).getByRole('menuitem', { name: /^Local small/ }));
    await screen.findByRole('button', { name: 'Model: Local small' });
    expect(daemon.capabilityCalls().some((call) => call.name === 'session.configure')).toBe(false);
  });

  it('clears the binding back to the project default', async () => {
    const daemon = fakeDaemon({
      capabilities: withScan({ 'session.configure': boundTo(BOUND, null) }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon, route: BOUND_ROUTE });
    await transcriptReady();

    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('menuitem', { name: /^Project default/ }));

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().find((call) => call.name === 'session.configure')?.request,
      ).toEqual({ session: BOUND, clear: true }),
    );
    // The value follows the record the daemon answered with, which now binds nothing.
    await screen.findByRole('button', { name: 'Model: Project default (Local small)' });
    expect(screen.queryByText('session:codex/gpt-5.5 (reasoning high)')).not.toBeInTheDocument();
  });

  it('renders a refused binding in the daemon\'s words and keeps the previous value', async () => {
    const refusal =
      'This session is private, so it may not be bound to a runtime that leaves the machine.';
    const daemon = fakeDaemon({
      capabilities: withScan({
        'session.configure': {
          capability: 'session.configure',
          ok: false,
          error: { code: 'policy_refused', message: refusal },
        },
      }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('menuitem', { name: /gpt-5\.5 \(live\)/ }));
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Use this runtime' }));

    // The refusal belongs where the pick was made, not to the rail's session history.
    const composer = document.querySelector('.rh-web-composer') as HTMLElement;
    expect(await within(composer).findByText(refusal)).toBeInTheDocument();
    expect(
      screen.queryByText('That change to the session history was refused'),
    ).not.toBeInTheDocument();
    // CS0001's own binding is still what the selector says.
    expect(screen.getByRole('button', { name: 'Model: Local small' })).toBeInTheDocument();
  });

  it('has no automatically detectable violation with the groups and the reasoning control', async () => {
    const daemon = fakeDaemon({ capabilities: withScan() });
    const user = userEvent.setup();
    renderConversation({ daemon, route: BOUND_ROUTE });
    await transcriptReady();

    await screen.findByRole('combobox', { name: 'Reasoning' });
    await openMenu(user);
    await expectNoAxeViolations(document.body);
  });
});

/* -- accessibility -------------------------------------------------------- */

describe('accessibility', () => {
  it('has no automatically detectable violation on the route', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    renderConversation({ daemon });
    await transcriptReady();

    await expectNoAxeViolations(document.body);
  });

  it('reaches the composer, the transcript and the inspector from the keyboard', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    const user = userEvent.setup();
    renderConversation({ daemon });
    await transcriptReady();

    const box = screen.getByRole('textbox', { name: 'Message' });
    box.focus();
    expect(box).toHaveFocus();

    // The inspector is a tab list, reachable and operable without a pointer.
    const inspector = screen.getByRole('region', { name: 'Research inspector' });
    const tabs = within(inspector).getAllByRole('tab');
    (tabs[0] as HTMLElement).focus();
    await user.keyboard('{ArrowRight}{Enter}');
    await waitFor(() => expect(tabs[1]).toHaveAttribute('aria-selected', 'true'));
  });
});
