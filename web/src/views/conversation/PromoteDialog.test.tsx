/**
 * What the promote dialog interrupts for, and what it does not.
 *
 * Two of the three notices on this screen are conditions rather than events: evidence
 * cannot be promoted from prose, ever, and an agent host may not promote at all. Both are
 * already on screen the moment the dialog opens, so `role="alert"` would interrupt a
 * screen-reader user with a rule every time they open the dialog and would bury the one
 * notice that is genuinely news — the daemon refusing the promotion they just asked for.
 */
import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ConversationMessage } from '../../api/dto';
import { PromoteDialog } from './PromoteDialog';
import { FIXTURES, expectNoAxeViolations, fakeDaemon, renderView } from '../../test/harness';

const MESSAGE = {
  schema_version: 1,
  id: 'M0042',
  created_at: '2026-09-03T19:25:02.850945Z',
  updated_at: '2026-09-03T19:25:02.850945Z',
  provenance: {},
  session: 'CS0001',
  role: 'assistant',
  blocks: [{ kind: 'text', text: 'Batching reduces tail latency on the held-out split.' }],
  authority: 'candidate',
  visibility: 'project',
  attempt: { number: 1, of: 1 },
} as unknown as ConversationMessage;

const AS_HOST = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };

function promotion(overrides: Record<string, unknown> = {}) {
  return {
    target: 'note',
    session: MESSAGE.session,
    message: MESSAGE.id,
    object_id: null,
    note_key: 'N0007',
    accepted: false,
    review: 'It enters review; nothing was accepted.',
    decision: null,
    ...overrides,
  };
}

function open(options: { overview?: unknown; capabilities?: Record<string, unknown> } = {}) {
  const daemon = fakeDaemon({
    gets: { '/overview': options.overview ?? FIXTURES.overview },
    capabilities: { 'session.promote': promotion(), ...options.capabilities },
  });
  const view = renderView(
    <PromoteDialog open onOpenChange={() => undefined} message={MESSAGE} target="note" />,
    { daemon, token: options.overview === AS_HOST ? null : 'local-token' },
  );
  return { ...view, daemon };
}

/** The notice whose title line contains this text, whatever role it carries. */
function noticeSaying(text: string | RegExp): HTMLElement {
  const line = screen.getByText(text);
  const notice = line.closest('.rh-error-notice');
  if (notice === null) throw new Error('that line is not inside an ErrorNotice');
  return notice as HTMLElement;
}

describe('the standing rules of promotion', () => {
  it('states the evidence rule politely, because it is true before the dialog opens', async () => {
    open();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Promote' })).toBeEnabled(),
    );

    const notice = noticeSaying('Evidence cannot be promoted from prose');
    // A rule that is always true is not an event. It is read where it sits.
    expect(notice).toHaveAttribute('role', 'status');
    expect(notice).toHaveTextContent('resolvable source anchor');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('states a read-only window’s refusal politely too, and disables Promote', async () => {
    open({ overview: AS_HOST });
    const notice = await waitFor(() => noticeSaying('This window may not promote'));

    expect(notice).toHaveAttribute('role', 'status');
    expect(notice).toHaveTextContent('agent host');
    expect(screen.getByRole('button', { name: 'Promote' })).toBeDisabled();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});

describe('a refusal the researcher just caused', () => {
  it('is announced assertively, because it is news about the press they made', async () => {
    const user = userEvent.setup();
    open({
      capabilities: {
        'session.promote': {
          capability: 'session.promote',
          ok: false,
          error: { code: 'validation_error', message: 'the excerpt is not part of that message' },
        },
      },
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Promote' })).toBeEnabled());

    await user.click(screen.getByRole('button', { name: 'Promote' }));

    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent('The daemon refused this promotion');
    expect(notice).toHaveTextContent('the excerpt is not part of that message');
  });
});

describe('a promotion that succeeded', () => {
  it('names what it created and says it is not accepted', async () => {
    const user = userEvent.setup();
    const { daemon } = open();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Promote' })).toBeEnabled());

    await user.click(screen.getByRole('button', { name: 'Promote' }));

    await waitFor(() =>
      expect(daemon.capabilityCalls().map((call) => call.name)).toContain('session.promote'),
    );
    const line = await screen.findByText(/Research note created: N0007/);
    const toast = line.closest('.rh-toast') as HTMLElement;
    expect(toast).toHaveTextContent('nothing was accepted');
    expect(within(toast).getByRole('button', { name: 'Open N0007' })).toBeInTheDocument();
  });
});

describe('the dialog itself', () => {
  it('has no automatically detectable accessibility violation', async () => {
    const { container } = open();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Promote' })).toBeEnabled());
    await expectNoAxeViolations(container);
  });
});
