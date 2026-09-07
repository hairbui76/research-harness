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
    await user.click(screen.getByRole('button', { name: 'Context used (CP0007)' }));
    const inspector = await screen.findByRole('region', { name: 'Research inspector' });
    await waitFor(() =>
      expect(within(inspector).getByText('Context used')).toBeInTheDocument(),
    );
  });
});
