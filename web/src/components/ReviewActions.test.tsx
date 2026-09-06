/**
 * The ceremony around a decision that cannot be taken back.
 *
 * Accepting writes accepted scientific state: `review.accept` allocates a real
 * `EvidenceId` and the candidate leaves the queue. No `review.*` capability reopens or
 * undoes that — a later change of mind is a Decision (PRODUCT §38), not a deletion — so
 * the acceptance is the one review action that asks twice, and the second ask restates
 * exactly what is about to be written rather than asking "Are you sure?".
 *
 * Everything else here is the rule the daemon owns rather than this component: a
 * conflicted candidate goes through `review.resolve_conflict`, and a window without the
 * local token records nothing at all (PRODUCT §29, ADR-007).
 */
import { describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@research-harness/design';
import { HarnessClient } from '../api/client';
import type { CandidateView } from '../api/dto';
import { SessionProvider } from '../app/session';
import { ProjectPathProvider } from '../app/projectPaths';
import { ReviewActions } from './ReviewActions';
import { FIXTURES, expectNoAxeViolations, fakeDaemon } from '../test/harness';

const CANDIDATE = FIXTURES.candidate as unknown as CandidateView;
const QUOTE = '94.32';

/** One `ReviewOutcome`, as every candidate-keyed review action answers. */
function outcome(action: string, evidence: string | null = null, status = 'reviewed') {
  return { candidate_id: CANDIDATE.candidate_id, action, status, evidence, mutation: null };
}

function daemonFor(overview: unknown = FIXTURES.overview) {
  return fakeDaemon({
    gets: { '/overview': overview },
    capabilities: {
      'review.accept': outcome('accept', 'E0042'),
      'review.qualify': outcome('accept_with_qualification', 'E0042'),
      'review.edit': outcome('edit', 'E0042'),
      'review.reject': outcome('reject'),
      'review.defer': outcome('defer', null, 'deferred'),
      'review.request_more': outcome('request_more', null, 'more_evidence_requested'),
      'review.resolve_conflict': {
        candidate_id: CANDIDATE.candidate_id,
        choice: 'accept',
        mutation: null,
      },
    },
  });
}

/** Where the router is now, so a toast action can be shown to actually go somewhere. */
function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

/** The toast carrying one line of text. Toasts render into a portal, outside the tree. */
async function toastSaying(text: string | RegExp): Promise<HTMLElement> {
  const line = await screen.findByText(text);
  const toast = line.closest('.rh-toast');
  if (toast === null) throw new Error('that line is not inside a toast');
  return toast as HTMLElement;
}

interface Options {
  daemon?: ReturnType<typeof fakeDaemon>;
  token?: string | null;
  hasOpenConflict?: boolean;
  onReviewed?: (what: string) => void;
  projectId?: string | null;
}

/**
 * The component under the providers `main.tsx` mounts, at a wildcard route so a toast
 * action that navigates leaves the tree standing and the destination readable.
 */
function renderActions(options: Options = {}) {
  const daemon = options.daemon ?? daemonFor();
  const client = new HarnessClient({
    baseUrl: 'http://daemon.test',
    token: options.token === undefined ? 'local-token' : options.token,
    fetchImpl: daemon.fetch,
  });
  const actions: ReactElement = (
    <>
      <ReviewActions
        candidate={CANDIDATE}
        {...(options.hasOpenConflict === undefined
          ? {}
          : { hasOpenConflict: options.hasOpenConflict })}
        onReviewed={options.onReviewed ?? (() => undefined)}
      />
      <Where />
    </>
  );
  const view = render(
    <ThemeProvider defaultTheme="dark" storageKey={null}>
      <ToastProvider>
        <MemoryRouter
          initialEntries={[`/review/${CANDIDATE.candidate_id}`]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <SessionProvider client={client}>
            <ProjectPathProvider projectId={options.projectId ?? null}>
              <Routes>
                <Route path="*" element={actions} />
              </Routes>
            </ProjectPathProvider>
          </SessionProvider>
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
  return { ...view, daemon };
}

/** The bar is enabled only once `/overview` has named the principal. */
async function ready() {
  await waitFor(() => expect(screen.getByRole('button', { name: 'Accept' })).toBeEnabled());
}

function names(daemon: ReturnType<typeof fakeDaemon>): string[] {
  return daemon.capabilityCalls().map((call) => call.name);
}

describe('accepting asks twice, and the second ask says what will be written', () => {
  it('writes nothing on the first press and restates the acceptance instead', async () => {
    const user = userEvent.setup();
    const { daemon } = renderActions();
    await ready();

    await user.click(screen.getByRole('button', { name: 'Accept' }));

    expect(names(daemon)).not.toContain('review.accept');
    const confirm = screen.getByRole('group', { name: 'Confirm the acceptance' });
    // The restatement names the field, the Work and the quote being accepted, not "Are
    // you sure?" — the reviewer is agreeing to a specific sentence about the corpus.
    expect(confirm).toHaveTextContent(CANDIDATE.field);
    expect(confirm).toHaveTextContent(CANDIDATE.work);
    expect(confirm).toHaveTextContent(QUOTE);
    expect(confirm).toHaveTextContent('accepted Evidence');
    // And it says the thing no capability offers: there is no way back.
    expect(confirm).toHaveTextContent(/No review action takes an acceptance back/);
  });

  it('still restates a candidate that quotes nothing, without empty quotation marks', async () => {
    const user = userEvent.setup();
    const daemon = daemonFor();
    const client = new HarnessClient({
      baseUrl: 'http://daemon.test',
      token: 'local-token',
      fetchImpl: daemon.fetch,
    });
    // A numeric or absence candidate can carry no exact span; the anchor, not the prose,
    // is what makes it evidence.
    const quoteless = { ...CANDIDATE, evidence: { content: {} } } as unknown as CandidateView;
    render(
      <ThemeProvider defaultTheme="dark" storageKey={null}>
        <ToastProvider>
          <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <SessionProvider client={client}>
              <ReviewActions candidate={quoteless} onReviewed={() => undefined} />
            </SessionProvider>
          </MemoryRouter>
        </ToastProvider>
      </ThemeProvider>,
    );
    await ready();

    await user.click(screen.getByRole('button', { name: 'Accept' }));
    const confirm = screen.getByRole('group', { name: 'Confirm the acceptance' });
    expect(confirm).toHaveTextContent('this proposal becomes accepted Evidence');
    expect(confirm).not.toHaveTextContent('“”');
  });

  it('is inline rather than a dialog, so the source stays on screen beside it', async () => {
    const user = userEvent.setup();
    renderActions();
    await ready();
    await user.click(screen.getByRole('button', { name: 'Accept' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('moves focus to the confirm button so Enter records the acceptance', async () => {
    const user = userEvent.setup();
    const { daemon } = renderActions();
    await ready();

    await user.click(screen.getByRole('button', { name: 'Accept' }));
    const confirm = screen.getByRole('button', { name: 'Accept as evidence' });
    await waitFor(() => expect(confirm).toHaveFocus());

    await user.keyboard('{Enter}');
    await waitFor(() => expect(names(daemon)).toContain('review.accept'));
    expect(
      daemon.capabilityCalls().find((call) => call.name === 'review.accept')?.request,
    ).toEqual({ candidate_id: CANDIDATE.candidate_id });
  });

  it('abandons the acceptance on Escape and hands focus back to Accept', async () => {
    const user = userEvent.setup();
    const { daemon } = renderActions();
    await ready();

    await user.click(screen.getByRole('button', { name: 'Accept' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Accept as evidence' })).toHaveFocus(),
    );
    await user.keyboard('{Escape}');

    expect(screen.queryByRole('group', { name: 'Confirm the acceptance' })).toBeNull();
    expect(names(daemon)).not.toContain('review.accept');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Accept' })).toHaveFocus());
  });

  it('abandons the acceptance from the Cancel button too', async () => {
    const user = userEvent.setup();
    const { daemon } = renderActions();
    await ready();

    await user.click(screen.getByRole('button', { name: 'Accept' }));
    await user.click(
      within(screen.getByRole('group', { name: 'Confirm the acceptance' })).getByRole('button', {
        name: 'Cancel',
      }),
    );

    expect(screen.queryByRole('group', { name: 'Confirm the acceptance' })).toBeNull();
    expect(names(daemon)).not.toContain('review.accept');
  });

  it('reports the decision to the host exactly once, after the write', async () => {
    const user = userEvent.setup();
    const onReviewed = vi.fn();
    renderActions({ onReviewed });
    await ready();

    await user.click(screen.getByRole('button', { name: 'Accept' }));
    expect(onReviewed).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Accept as evidence' }));

    await waitFor(() => expect(onReviewed).toHaveBeenCalledTimes(1));
    expect(onReviewed).toHaveBeenCalledWith('accepted');
  });

  it('offers no confirmation at all to a window that may not accept', async () => {
    const user = userEvent.setup();
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    const { daemon } = renderActions({ daemon: daemonFor(asHost), token: null });

    await waitFor(() => expect(screen.getByTestId('mutation-blocked')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Accept' }));

    expect(screen.queryByRole('group', { name: 'Confirm the acceptance' })).toBeNull();
    expect(names(daemon)).toEqual([]);
  });

  it('keeps asking for a reason when the candidate carries an open conflict', async () => {
    const user = userEvent.setup();
    const { daemon } = renderActions({ hasOpenConflict: true });
    await ready();

    await user.click(screen.getByRole('button', { name: 'Accept' }));
    // The conflict path already had its ceremony: it demands the sentence that closes the
    // record, so a second confirmation would only be a second click.
    expect(screen.queryByRole('group', { name: 'Confirm the acceptance' })).toBeNull();
    await user.type(
      screen.getByLabelText('Why this side of the conflict is the one to accept'),
      'row TrafficLM, column F1 of Table 1',
    );
    await user.click(screen.getByRole('button', { name: 'Accept and close the conflict' }));

    await waitFor(() => expect(names(daemon)).toContain('review.resolve_conflict'));
    expect(names(daemon)).not.toContain('review.accept');
  });
});

describe('what the toast says was written', () => {
  it('names the evidence the acceptance created and offers to open it', async () => {
    const user = userEvent.setup();
    renderActions();
    await ready();
    await user.click(screen.getByRole('button', { name: 'Accept' }));
    await user.click(screen.getByRole('button', { name: 'Accept as evidence' }));

    const toast = await toastSaying('Accepted as E0042');
    // No undo is offered, because the daemon has none to offer.
    expect(within(toast).queryByRole('button', { name: /undo/i })).toBeNull();

    await user.click(within(toast).getByRole('button', { name: 'Open E0042' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/evidence/E0042');
  });

  it('resolves the evidence link inside the project it was accepted in', async () => {
    const user = userEvent.setup();
    renderActions({ projectId: 'prj_abc' });
    await ready();
    await user.click(screen.getByRole('button', { name: 'Accept' }));
    await user.click(screen.getByRole('button', { name: 'Accept as evidence' }));

    const toast = await toastSaying('Accepted as E0042');
    await user.click(within(toast).getByRole('button', { name: 'Open E0042' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/projects/prj_abc/evidence/E0042');
  });

  it('says what a rejection wrote, and links to nothing, because it created nothing', async () => {
    const user = userEvent.setup();
    const { daemon } = renderActions();
    await ready();

    await user.click(screen.getByRole('button', { name: 'Reject' }));
    await user.type(screen.getByLabelText('Why this candidate is refused'), 'wrong column');
    await user.click(screen.getAllByRole('button', { name: 'Reject' })[1]!);

    await waitFor(() => expect(names(daemon)).toContain('review.reject'));
    const toast = await toastSaying('Candidate rejected.');
    expect(toast).toHaveTextContent('nothing is accepted');
    expect(within(toast).queryByRole('button', { name: /^Open / })).toBeNull();
  });
});

describe('the decisions that ask for a sentence', () => {
  it('restates the consequence in the form, above the button that records it', async () => {
    const user = userEvent.setup();
    renderActions();
    await ready();

    await user.click(screen.getByRole('button', { name: 'Qualify' }));
    const form = screen.getByRole('form', { name: 'Qualify' });
    expect(form).toHaveTextContent('accepted Evidence');
    expect(within(form).getByRole('button', { name: 'Accept with qualification' })).toBeDisabled();

    await user.type(
      screen.getByLabelText('Qualification recorded with the acceptance'),
      'the held-out split only',
    );
    expect(within(form).getByRole('button', { name: 'Accept with qualification' })).toBeEnabled();
  });

  it('says what deferring and asking for more evidence do, and neither accepts', async () => {
    const user = userEvent.setup();
    renderActions();
    await ready();

    await user.click(screen.getByRole('button', { name: 'Defer' }));
    expect(screen.getByRole('form', { name: 'Defer' })).toHaveTextContent('nothing is accepted');

    await user.click(screen.getByRole('button', { name: 'Request more evidence' }));
    expect(screen.getByRole('form', { name: 'Request more evidence' })).toHaveTextContent(
      'nothing is accepted',
    );
  });
});

describe('a refusal from the daemon', () => {
  it('prints the daemon’s own sentence and leaves the bar usable', async () => {
    const user = userEvent.setup();
    const daemon = fakeDaemon({
      gets: { '/overview': FIXTURES.overview },
      capabilities: {
        'review.accept': {
          capability: 'review.accept',
          ok: false,
          error: {
            code: 'validation_error',
            message: 'a proposed candidate needs a verification verdict before acceptance',
          },
        },
      },
    });
    renderActions({ daemon });
    await ready();

    await user.click(screen.getByRole('button', { name: 'Accept' }));
    await user.click(screen.getByRole('button', { name: 'Accept as evidence' }));

    expect(
      await screen.findByText(/a proposed candidate needs a verification verdict/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept' })).toBeEnabled();
  });
});

describe('the decide panel', () => {
  it('has no automatically detectable accessibility violation, confirming or not', async () => {
    const user = userEvent.setup();
    const { container } = renderActions();
    await ready();
    await expectNoAxeViolations(container);

    await user.click(screen.getByRole('button', { name: 'Accept' }));
    await expectNoAxeViolations(container);
  });
});
