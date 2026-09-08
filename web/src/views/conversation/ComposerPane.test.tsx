/**
 * The composer's standing answer to "where is this message going?".
 *
 * The egress disclosure is a dialog answered once per session. These tests are about the
 * thirty-ninth message rather than the first: whatever the record is bound to, the composer
 * keeps one quiet line inside its own frame that names the destination and says whether the
 * content leaves the machine, and that line follows the binding rather than a memory of it.
 *
 * Driven through the real route, the real shell and the real client, like every other
 * conversation test; only `fetch` is faked. The words asserted here are the ones on screen,
 * because the whole point of the line is that a researcher can read it without opening
 * anything.
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
import providers from '../../test/fixtures/conversation/providers.json';
import sessions from '../../test/fixtures/conversation/sessions.json';
import cliScan from '../../test/fixtures/providers/cli-scan.json';
import transcript from '../../test/fixtures/conversation/transcript.json';
import { destinationWords } from './ComposerPane';

/** `CS0001` is private and bound to a local entry; `CS0002` is bound to a CLI runtime. */
const LOCAL = 'CS0001';
const RUNTIME = 'CS0002';

interface Answers {
  [capability: string]: unknown;
}

function answers(extra: Answers = {}): Answers {
  return {
    'session.list': sessions,
    'session.get': transcript,
    'session.search': { count: 0, matches: [] },
    'provider.list': providers,
    'provider.cli.scan': cliScan,
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
  session: string;
  /** `null` is a window that may read and not write, the way the route is told apart. */
  token?: string | null;
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
          initialEntries={[`/?session=${options.session}`]}
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

async function transcriptReady(): Promise<void> {
  await screen.findByText(/records the accepted claim/, undefined, { timeout: 3000 });
}

/** The record `session.configure` answers with, bound as the daemon would store it. */
function boundTo(id: string, model: { provider: string; model: string } | null) {
  const record = sessions.sessions.find((session) => session.id === id);
  return {
    session: { ...record, defaults: { mode: null, token_budget: null, model, reasoning: null } },
  };
}

async function openMenu(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /^Model:/ }));
  return screen.findByRole('menu', { name: 'Model' });
}

/**
 * A browser that has already read this session's egress disclosure.
 *
 * The key is `ComposerPane`'s own (`rh.binding-disclosed.<session>`), written here rather
 * than exported, because the whole subject of these tests is what a researcher sees *after*
 * that dialog has been answered and will not appear again.
 */
function disclosed(sessionId: string): void {
  window.localStorage.setItem(`rh.binding-disclosed.${sessionId}`, 'read');
}

beforeEach(() => {
  window.localStorage.clear();
});

/* -- the words ------------------------------------------------------------ */

describe('the destination line', () => {
  const CODEX = { runtime: 'codex', model: 'gpt-5.5' };
  const SCANNED = { codex: { name: 'Codex CLI', egressHost: 'chatgpt.com' } };

  it('names the runtime, the model and the host a runtime binding reaches', () => {
    expect(
      destinationWords({
        runtime: CODEX,
        destinations: SCANNED,
        option: null,
        binding: 'session:codex/gpt-5.5',
      }),
    ).toBe('Sends to Codex CLI · gpt-5.5 — leaves this machine for chatgpt.com');
  });

  it('still says a runtime leaves the machine when the scan could not be read', () => {
    // Every CLI runtime is external egress whether or not a scan answered, so the sentence
    // survives a failed scan; only the host, which is the scan's own fact, drops out.
    expect(
      destinationWords({
        runtime: CODEX,
        destinations: {},
        option: null,
        binding: 'session:codex/gpt-5.5',
      }),
    ).toBe('Sends to codex · gpt-5.5 — leaves this machine');
  });

  it('reads a catalogue entry’s own egress class, in either direction', () => {
    const local = {
      id: 'local-small',
      label: 'Local small',
      provider: 'local',
      egressClass: 'local' as const,
      vision: false,
      contextTokens: 32_000,
      available: true,
    };
    expect(
      destinationWords({ runtime: null, destinations: {}, option: local, binding: null }),
    ).toBe('Sends to Local small — stays on this machine');
    expect(
      destinationWords({
        runtime: null,
        destinations: {},
        option: { ...local, label: 'Vendor vision', egressClass: 'external' },
        binding: null,
      }),
    ).toBe('Sends to Vendor vision — leaves this machine');
  });

  it('names a binding the picker has no row for, and claims nothing about its egress', () => {
    expect(
      destinationWords({
        runtime: null,
        destinations: {},
        option: null,
        binding: 'entry retired-entry',
      }),
    ).toBe('Sends to entry retired-entry');
  });

  it('says nothing at all when there is no destination to state', () => {
    expect(
      destinationWords({ runtime: null, destinations: {}, option: null, binding: null }),
    ).toBeNull();
  });
});

/* -- the line in the composer --------------------------------------------- */

describe('the composer after the disclosure', () => {
  it('keeps the bound runtime and its host on screen, as part of the text box', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    renderConversation({ daemon, session: RUNTIME });
    await transcriptReady();

    const line = await screen.findByText(
      'Sends to Codex CLI · gpt-5.5 — leaves this machine for chatgpt.com',
    );
    // Read as part of the composer, not shouted: a describedby, never a live region.
    expect(line).not.toHaveAttribute('aria-live');
    expect(line.closest('.rh-composer')).not.toBeNull();
    const textarea = screen.getByRole('textbox', { name: 'Message' });
    expect((textarea.getAttribute('aria-describedby') ?? '').split(' ')).toContain(line.id);

    // Nothing here restates the disclosure paragraph; that stays in the dialog.
    expect(screen.queryByText(cliScan.notice)).not.toBeInTheDocument();
  });

  it('follows the record when the binding changes, without disclosing again', async () => {
    const daemon = fakeDaemon({
      capabilities: answers({
        'session.configure': boundTo(RUNTIME, {
          provider: 'local_cli:codex',
          model: 'gpt-5.4-mini',
        }),
      }),
    });
    const user = userEvent.setup();
    disclosed(RUNTIME);
    renderConversation({ daemon, session: RUNTIME });
    await transcriptReady();

    await screen.findByText(
      'Sends to Codex CLI · gpt-5.5 — leaves this machine for chatgpt.com',
    );
    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('menuitem', { name: /^gpt-5\.4-mini \(live\)/ }));

    // This session has been bound to this runtime before, so the disclosure does not
    // reappear — which is exactly why the line has to.
    await screen.findByText(
      'Sends to Codex CLI · gpt-5.4-mini — leaves this machine for chatgpt.com',
    );
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Sends to Codex CLI · gpt-5.5 — leaves this machine for chatgpt.com'),
    ).not.toBeInTheDocument();
  });

  it('says a local entry stays here, in the same line and the same voice', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    renderConversation({ daemon, session: LOCAL });
    await transcriptReady();

    expect(
      await screen.findByText('Sends to Local small — stays on this machine'),
    ).toBeInTheDocument();
  });

  it('states the project default, in the words the picker already uses for it', async () => {
    const unbound = {
      ...sessions,
      sessions: sessions.sessions.map((session) =>
        session.id === LOCAL ? { ...session, defaults: {} } : session,
      ),
    };
    const daemon = fakeDaemon({ capabilities: answers({ 'session.list': unbound }) });
    renderConversation({ daemon, session: LOCAL });
    await transcriptReady();

    // The same row the picker offers to unbind with, so the two never disagree.
    expect(
      await screen.findByText('Sends to Project default (Local small) — stays on this machine'),
    ).toBeInTheDocument();
  });

  it('goes back to the project default the moment the binding is cleared', async () => {
    const daemon = fakeDaemon({
      capabilities: answers({ 'session.configure': boundTo(RUNTIME, null) }),
    });
    const user = userEvent.setup();
    renderConversation({ daemon, session: RUNTIME });
    await transcriptReady();

    await screen.findByText(
      'Sends to Codex CLI · gpt-5.5 — leaves this machine for chatgpt.com',
    );
    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('menuitem', { name: /^Project default/ }));

    await screen.findByText('Sends to Project default (Local small) — stays on this machine');
  });

  it('states nothing where the cockpit knows nothing: no catalogue, no scan, no binding', async () => {
    const unbound = {
      ...sessions,
      sessions: sessions.sessions.map((session) =>
        session.id === LOCAL ? { ...session, defaults: {} } : session,
      ),
    };
    const capabilities = answers({ 'session.list': unbound });
    delete capabilities['provider.list'];
    capabilities['provider.cli.scan'] = {
      capability: 'provider.cli.scan',
      ok: false,
      error: { code: 'unavailable', message: 'the runtime scan could not be read' },
    };
    renderConversation({ daemon: fakeDaemon({ capabilities }), session: LOCAL });
    await transcriptReady();

    // The catalogue's own sentence already says what happened; inventing a destination on
    // top of it would be the one claim this pane must never make.
    await screen.findByText(/model catalogue is unavailable/);
    expect(screen.queryByText(/^Sends to /)).not.toBeInTheDocument();
    expect(document.querySelector('.rh-composer__destination')).toBeNull();
  });

  it('reads the binding to a runtime the scan could not describe', async () => {
    const daemon = fakeDaemon({
      capabilities: answers({
        'provider.cli.scan': {
          capability: 'provider.cli.scan',
          ok: false,
          error: { code: 'unavailable', message: 'the runtime scan could not be read' },
        },
      }),
    });
    renderConversation({ daemon, session: RUNTIME });
    await transcriptReady();

    // No name and no host to borrow, and the one thing that is still true is still said.
    expect(
      await screen.findByText('Sends to codex · gpt-5.5 — leaves this machine'),
    ).toBeInTheDocument();
  });

  it('follows the per-message model a read-only window may still pick', async () => {
    // The record is bound to a runtime and this window may not change that. What it may
    // still do is choose where *this* message goes, so the line reads the selection rather
    // than the binding — otherwise it would name a destination the message is not using.
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    const daemon = fakeDaemon({ gets: { '/overview': asHost }, capabilities: answers() });
    const user = userEvent.setup();
    renderConversation({ daemon, session: RUNTIME, token: null });
    await transcriptReady();

    await screen.findByText(
      'Sends to Codex CLI · gpt-5.5 — leaves this machine for chatgpt.com',
    );
    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('menuitem', { name: /^Local small/ }));

    await screen.findByText('Sends to Local small — stays on this machine');
    // Nothing durable moved; only this message's destination did.
    expect(daemon.capabilityCalls().some((call) => call.name === 'session.configure')).toBe(
      false,
    );
    expect(screen.getByText('session:codex/gpt-5.5 (reasoning high)')).toBeInTheDocument();
  });

  it('has no automatically detectable violation with the line on screen', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    renderConversation({ daemon, session: RUNTIME });
    await transcriptReady();

    await screen.findByText(
      'Sends to Codex CLI · gpt-5.5 — leaves this machine for chatgpt.com',
    );
    await expectNoAxeViolations(document.body);
  });

  it('offers no model trigger where there is no message to send', async () => {
    // The capture that found this: a workspace with no session open, a picker reading
    // "Project default", and no line under it. A trigger that names a model while the
    // composer says nothing about egress is the one regression the removal of the
    // EXTERNAL/LOCAL tag must not cause, so the two stand or fall together.
    const empty = { count: 0, sessions: [] };
    renderConversation({ daemon: fakeDaemon({ capabilities: answers({ 'session.list': empty }) }), session: '' });
    await screen.findByText('No session open');

    expect(screen.queryByRole('button', { name: /^Model:/ })).toBeNull();
    expect(document.querySelector('.rh-composer__destination')).toBeNull();
  });

  it('keeps the index state beside the destination and one notice above the box', async () => {
    // The stack the finish review measured: the graph's framed notice, the catalogue's
    // sentence, and four more siblings above an empty message box. The index state is a
    // capability note and rides beside the destination line now; the slot above the box
    // holds one thing, and here that is the catalogue's own sentence.
    const capabilities = answers();
    delete capabilities['provider.list'];
    capabilities['provider.cli.scan'] = {
      capability: 'provider.cli.scan',
      ok: false,
      error: { code: 'unavailable', message: 'the runtime scan could not be read' },
    };
    renderConversation({ daemon: fakeDaemon({ capabilities }), session: LOCAL });
    await transcriptReady();
    await screen.findByText(/model catalogue is unavailable/);

    const pane = document.querySelector('.rh-web-composer')!;
    const box = pane.querySelector('.rh-composer')!;
    const above = [
      ...pane.querySelectorAll('.rh-error-notice, .rh-state, .rh-web-composer__note'),
    ].filter((node) => !box.contains(node));
    expect(above).toHaveLength(1);
    expect(above[0]).toHaveTextContent(/model catalogue is unavailable/);
    // No `graph.status` in this fixture, so completion is falling back — and says so from
    // inside the box, on the footer row the destination line owns.
    expect(box.querySelector('.rh-composer__footer .rh-web-graph-note')).not.toBeNull();
  });

  it('is not the only place the destination is stated', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    const user = userEvent.setup();
    renderConversation({ daemon, session: RUNTIME });
    await transcriptReady();

    await screen.findByText(
      'Sends to Codex CLI · gpt-5.5 — leaves this machine for chatgpt.com',
    );
    // The rail states the same record in the format every surface uses, and every answer
    // still opens the receipt that names what was sent. The composer's line is an addition
    // to those, never a replacement for them (binding spec §10).
    expect(screen.getByText('session:codex/gpt-5.5 (reasoning high)')).toBeInTheDocument();
    // Every turn's row has an overflow now that Inspect lives in it; the answer's is the
    // one carrying the receipt.
    await user.click(screen.getAllByRole('button', { name: 'More actions' })[1] as HTMLElement);
    await user.click(await screen.findByRole('menuitem', { name: 'Context used (CP0007)' }));
    const inspector = await screen.findByRole('region', { name: 'Research inspector' });
    await waitFor(() =>
      expect(within(inspector).getByText('Context used')).toBeInTheDocument(),
    );
  });
});

/* -- the entrance --------------------------------------------------------- */

/**
 * The conversation route's front door (wave six, third critique P2).
 *
 * With no session open the composer rendered as an inviting field with an accent Send,
 * disabled, and the only explanation was a sentence in the transcript that named a control
 * by a name it does not have. The daemon has no create-on-send — `session.send` takes a
 * session id and reads that record before anything else — so the field cannot be the way
 * in. One control is, with the rail's own label.
 *
 * It sits in the transcript's own empty state. Fixing the sentence left the act offered
 * twice — a control in the composer slot, under a sentence pointing down at it, under a
 * rail button of the same name — so the state that names the absence now carries the way
 * out of it, and the composer slot keeps nothing but the reason a window that may only
 * read is offered no control at all.
 */
describe('the entrance', () => {
  const NO_SESSIONS = { count: 0, sessions: [] };

  function renderEmpty(options: { agentHost?: boolean } = {}) {
    const created = {
      ...sessions.sessions[1],
      id: 'CS0009',
      title: 'New session',
      visibility: 'project',
      defaults: {},
      message_count: 0,
      last_message: null,
      last_message_at: null,
    };
    const daemon = fakeDaemon({
      ...(options.agentHost
        ? { gets: { '/overview': { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' } } }
        : {}),
      capabilities: answers({
        'session.list': NO_SESSIONS,
        'session.create': { session: created },
      }),
    });
    renderConversation({
      daemon,
      session: '',
      ...(options.agentHost ? { token: null } : {}),
    });
    return daemon;
  }

  it('replaces the disabled field with one control in the rail’s words', async () => {
    const user = userEvent.setup();
    const daemon = renderEmpty();
    const empty = (await screen.findByText('No session open')).closest('.rh-state') as HTMLElement;

    // Nothing to type into and no Send to disable, and no second copy of the act in the
    // composer slot either: the state that names the absence holds the one way out of it.
    expect(screen.queryByRole('textbox', { name: 'Message' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Send' })).toBeNull();
    expect(document.querySelector('.rh-web-entrance')).toBeNull();
    expect(within(empty).getByRole('button', { name: 'New session' })).toBeInTheDocument();

    // The same act the rail runs, asked the same way: visibility is fixed at creation.
    await user.click(within(empty).getByRole('button', { name: 'New session' }));
    const dialog = await screen.findByRole('dialog', { name: 'New session' });
    await user.click(within(dialog).getByRole('button', { name: 'Create session' }));

    await waitFor(() =>
      expect(
        daemon.capabilityCalls().find((call) => call.name === 'session.create')?.request,
      ).toEqual({ title: 'New session' }),
    );
    // And the caret lands in the box that was opened for it.
    const box = await screen.findByRole('textbox', { name: 'Message' });
    await waitFor(() => expect(box).toHaveFocus());
  });

  it('offers the act once, and points at nothing', async () => {
    renderEmpty();
    const empty = (await screen.findByText('No session open')).closest('.rh-state') as HTMLElement;

    // The empty state teaches what a session is instead of directing the eye somewhere
    // else on the screen; the sentence it used to print ("Choose New session below…")
    // named a control that stood right under it and a third time in the rail.
    expect(empty).toHaveTextContent(/A session is one conversation held against this project/);
    expect(screen.queryByText(/below/)).toBeNull();
    // One in the state, one in the rail, and none in between.
    expect(screen.getAllByRole('button', { name: 'New session' })).toHaveLength(2);
    expect(within(empty).getAllByRole('button', { name: 'New session' })).toHaveLength(1);
  });

  it('states the reason at the control when a window may only read', async () => {
    renderEmpty({ agentHost: true });
    await screen.findByText('No session open');

    // No control anywhere — the rail withdraws it too — and the reason is in the slot the
    // missing control would have filled, which for a window that may only read is the
    // message box.
    expect(screen.queryByRole('button', { name: 'New session' })).toBeNull();
    const entrance = document.querySelector('.rh-web-entrance') as HTMLElement;
    expect(entrance).toHaveTextContent(/may read and propose/);
  });

  it('has no automatically detectable violation with the front door on screen', async () => {
    renderEmpty();
    await screen.findByText('No session open');
    await expectNoAxeViolations(document.body);
  });
});

/* -- the chrome under the box --------------------------------------------- */

describe('the index note', () => {
  /** The key `useIndexNoteRead` writes; a project that has already been told once. */
  function alreadyRead(degradation: string): void {
    window.localStorage.setItem(`rh.index-note-read..${degradation}`, 'read');
  }

  function withAbsentIndex() {
    return fakeDaemon({
      capabilities: answers({
        'graph.status': { status: { state: 'absent', counts: {}, built_at: null } },
      }),
    });
  }

  it('teaches on the first showing and folds onto the hint’s line afterwards', async () => {
    renderConversation({ daemon: withAbsentIndex(), session: LOCAL });
    await transcriptReady();

    // First showing: the sentence that teaches, on a line of its own under the destination.
    const note = await screen.findByText(
      'The research index is not built yet; completing from the project listings.',
    );
    expect(document.querySelector('.rh-composer__footer > .rh-composer__note')).not.toBeNull();
    expect(note.closest('.rh-composer__hints')).toBeNull();
  });

  it('shares one footer line with the keyboard hint once it has been read', async () => {
    alreadyRead('absent');
    renderConversation({ daemon: withAbsentIndex(), session: LOCAL });
    await transcriptReady();

    // The same state and the same action, in the shortest true form, beside the shortcut.
    const short = await screen.findByText('Research index not built');
    const hints = short.closest('.rh-composer__hints');
    expect(hints).not.toBeNull();
    expect(hints?.querySelector('.rh-composer__hint')).not.toBeNull();
    expect(document.querySelector('.rh-composer__footer > .rh-composer__note')).toBeNull();
    // Folding hides nothing: the rebuild the wording asks for is still one press away.
    expect(screen.getByRole('button', { name: 'Rebuild the index' })).toBeInTheDocument();
    // And the destination keeps a line of its own.
    expect(document.querySelector('.rh-composer__footer > .rh-composer__destination')).not.toBeNull();
  });
});
