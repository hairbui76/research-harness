/**
 * Task 11.3: the researcher never decides without the source, and never accepts without
 * the authority to.
 *
 * The two properties asserted here are the ones the gate rests on. First, the exact span
 * and the block it sits in are on screen beside the proposal (Product 25). Second, without
 * the local token every review control is disabled and says why: an agent host reads and
 * proposes, and the researcher accepts (Product 29, ADR-007).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactElement } from 'react';
import type { ReviewItem } from '../api/dto';
import { AUTO_ADVANCE_KEY, EvidenceReviewPage, ProposedChanges, neighbours } from './EvidenceReview';
import { CommandsProvider } from '../app/commands';
import { ProjectPathProvider } from '../app/projectPaths';
import { candidateName, fieldLabel } from '../components/Feedback';
import { splitAround } from '../components/SourcePane';
import { FIXTURES, expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';

// pdf.js is loaded lazily by the source pane; jsdom has no PDF engine, and the pane's
// documented fallback is the exact block text, which is what these tests read.
vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument: () => ({ promise: Promise.reject(new Error('no PDF engine under jsdom')) }),
}));

const QUEUE = FIXTURES.reviewInbox as unknown as { items: ReviewItem[] };
const ITEM = QUEUE.items[0]!;
const CANDIDATE = FIXTURES.candidate as unknown as { candidate_id: string; artifact: string };

/** One `ReviewOutcome`: what every candidate-keyed review action answers with. */
function outcome(action: string, evidence: string | null = null, status = 'reviewed') {
  return { candidate_id: ITEM.candidate_id, action, status, evidence, mutation: null };
}

function daemonFor(overview: unknown = FIXTURES.overview) {
  return fakeDaemon({
    gets: {
      '/overview': overview,
      [`/candidates/${ITEM.candidate_id}`]: FIXTURES.candidate,
      [`/blocks/${ITEM.artifact}`]: FIXTURES.blocks,
    },
    capabilities: {
      'review.inbox': FIXTURES.reviewInbox,
      'review.accept': outcome('accept', 'E0001'),
      'review.qualify': outcome('accept_with_qualification', 'E0001'),
      'review.edit': outcome('edit', 'E0001'),
      'review.reject': outcome('reject'),
      'review.defer': outcome('defer', null, 'deferred'),
      'review.request_more': outcome('request_more', null, 'more_evidence_requested'),
    },
  });
}

/**
 * The same candidate, recording an absence instead of a number, so the Absence panel is on
 * screen. `not_reported` is one of the four states the extractor may report; `absent` is
 * an audited conclusion and is never extracted (PRODUCT §11).
 */
function daemonForAbsence() {
  const candidate = FIXTURES.candidate as unknown as {
    evidence: { content: Record<string, unknown> };
  };
  const absence = {
    ...candidate,
    evidence: {
      ...candidate.evidence,
      content: { ...candidate.evidence.content, numeric: null, negative_state: 'not_reported' },
    },
  };
  return fakeDaemon({
    gets: {
      '/overview': FIXTURES.overview,
      [`/candidates/${ITEM.candidate_id}`]: absence,
      [`/blocks/${ITEM.artifact}`]: FIXTURES.blocks,
    },
    capabilities: { 'review.inbox': FIXTURES.reviewInbox },
  });
}

/** The review screen inside the shortcut layer, which is where the shell mounts it. */
function withShell(ui: ReactElement): ReactElement {
  return <CommandsProvider>{ui}</CommandsProvider>;
}

function renderReview(daemon = daemonFor(), token: string | null = 'local-token') {
  return renderView(withShell(<EvidenceReviewPage />), {
    daemon,
    token,
    route: `/review/${ITEM.candidate_id}`,
    path: '/review/:candidateId',
  });
}

beforeEach(() => {
  window.localStorage.clear();
});

describe('source beside decision', () => {
  it('shows the exact span, the block it sits in, and the field it answers', async () => {
    renderReview();

    await waitFor(() => expect(screen.getByText('Source text')).toBeInTheDocument());
    expect(screen.getAllByText(ITEM.source_context.exact_text).length).toBeGreaterThan(0);
    expect(screen.getByText('Anchor')).toBeInTheDocument();
    expect(screen.getAllByText(fieldLabel(ITEM.field)).length).toBeGreaterThan(0);
  });

  it('offers the original file when the page cannot be rendered here', async () => {
    renderReview();

    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'the original file' })).toHaveAttribute(
        'href',
        expect.stringContaining(`/artifacts/${CANDIDATE.artifact}/bytes`),
      ),
    );
  });

  it('marks the quoted span inside its block rather than showing it alone', () => {
    const parts = splitAround('All experiments use CICIDS2017 traces.', 'CICIDS2017');
    expect(parts).toEqual([
      { text: 'All experiments use ', match: false },
      { text: 'CICIDS2017', match: true },
      { text: ' traces.', match: false },
    ]);
  });

  it('shows the verifier’s verdict and rationale, and no confidence number', async () => {
    const { container } = renderReview();

    await waitFor(() => expect(screen.getByText('Verification')).toBeInTheDocument());
    expect(screen.getByText('Supported')).toBeInTheDocument();
    expect(container.textContent?.toLowerCase()).not.toContain('confidence');
  });

  it('names the screen by the question it answers, in words', async () => {
    const { container } = renderReview();

    await waitFor(() => expect(screen.getByText('Verification')).toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Metric result · W0001');
    const text = container.textContent ?? '';
    for (const token of ['metric_result', 'experimental_result', 'source_observed', 'high_risk']) {
      expect(text).not.toContain(token);
    }
  });

  it('puts the verdict’s meaning within reach rather than in a title', async () => {
    const { container } = renderReview();

    await waitFor(() => expect(screen.getByText('Verification')).toBeInTheDocument());
    const verdict = screen.getByText('Supported').closest('.rh-badge')!;
    expect(verdict).not.toHaveAttribute('title');
    expect(
      container.querySelector(`#${verdict.getAttribute('aria-describedby')}`),
    ).toHaveTextContent(/independent reader/);
  });

  /**
   * The words a first-timer meets, defined where they stand.
   *
   * "Tier 2 — deep review", "Ambiguous extractions", `STRENGTH: Direct` and
   * `ORIGIN: Source observed` were on this screen with nothing on the page to say what
   * they meant (critique 2026-09-07, heuristic 10, Jordan). Each is now reachable the way
   * the authority badge above them already was: a tab stop, a sentence named by it, and
   * the same sentence printed underneath on focus.
   */
  it('defines the metadata facts it prints, one press away', async () => {
    const user = userEvent.setup();
    const { container } = renderReview();

    await waitFor(() => expect(screen.getByText('Verification')).toBeInTheDocument());

    const meanings: Record<string, RegExp> = {
      'Experimental result': /kind of statement/,
      Direct: /How directly the source supports/,
      'Source observed': /measured or reported/,
      'Metric result': /measured result/,
    };
    for (const [word, sentence] of Object.entries(meanings)) {
      const found = [...container.querySelectorAll('.rh-described-term__word')].find(
        (element) => element.textContent === word,
      );
      expect(found, `no described fact reads "${word}"`).toBeDefined();
      expect(found).not.toHaveAttribute('title');
      expect(
        container.querySelector(`#${found!.getAttribute('aria-describedby')}`),
      ).toHaveTextContent(sentence);

      // Clicking the word focuses it, which is how a pointer reaches the same sentence
      // the keyboard does.
      await user.click(found!);
      expect(container.querySelector('.rh-described-term__hint')).toHaveTextContent(sentence);
    }
  });

  it('says what a valid anchor is, where it says the anchor is valid', async () => {
    const { container } = renderReview();

    await waitFor(() => expect(screen.getByText('Anchor')).toBeInTheDocument());
    const anchor = screen.getByText('Valid').closest('.rh-badge')!;
    expect(anchor).not.toHaveAttribute('title');
    expect(anchor).toHaveAttribute('tabindex', '0');
    expect(
      container.querySelector(`#${anchor.getAttribute('aria-describedby')}`),
    ).toHaveTextContent(/still replays/);
  });

  it('says what an absence state is, where the candidate records one', async () => {
    const { container } = renderReview(daemonForAbsence());

    await waitFor(() => expect(screen.getByText('Absence')).toBeInTheDocument());
    const state = [...container.querySelectorAll('.rh-described-term__word')].find(
      (element) => element.textContent === 'Not reported',
    );
    expect(state).toBeDefined();
    expect(
      container.querySelector(`#${state!.getAttribute('aria-describedby')}`),
    ).toHaveTextContent(/missing keyword/);
  });

  it('reads an open dictionary out as a line, never as JSON', async () => {
    const { container } = renderReview();

    await waitFor(() => expect(screen.getByText('Number')).toBeInTheDocument());
    expect(container.textContent).not.toMatch(/[{}]/);
  });

  it('shows a number with the provenance Product 12 requires of one', async () => {
    renderReview();

    await waitFor(() => expect(screen.getByText('Number')).toBeInTheDocument());
    expect(screen.getByText('F1')).toBeInTheDocument();
    expect(screen.getByText('CICIDS2017')).toBeInTheDocument();
  });
});

describe('review authority', () => {
  it('accepts by staging id alone, so the queue settles without a second call', async () => {
    const daemon = daemonFor();
    renderReview(daemon);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Accept' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
    // Accepting writes accepted state nothing undoes, so it confirms first.
    fireEvent.click(await screen.findByRole('button', { name: 'Accept as evidence' }));

    await waitFor(() =>
      expect(daemon.capabilityCalls().some((call) => call.name === 'review.accept')).toBe(true),
    );
    const call = daemon.capabilityCalls().find((entry) => entry.name === 'review.accept');
    expect(call?.request).toEqual({ candidate_id: ITEM.candidate_id });
  });

  it('never posts the Evidence object it was just handed back to the daemon', async () => {
    const daemon = daemonFor();
    renderReview(daemon);

    // The bar's button is "Qualify" — the Design System owns the decision vocabulary
    // (`REVIEW_DECISION_META`) — and the form it opens still submits with the sentence the
    // researcher is agreeing to.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Qualify' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Qualify' }));
    fireEvent.change(screen.getByLabelText('Qualification recorded with the acceptance'), {
      target: { value: 'holds for the CICIDS2017 capture only' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Accept with qualification' }));

    await waitFor(() => {
      const call = daemon.capabilityCalls().find((entry) => entry.name === 'review.qualify');
      expect(call?.request).toEqual({
        candidate_id: ITEM.candidate_id,
        qualification: 'holds for the CICIDS2017 capture only',
      });
    });
    expect(daemon.capabilityCalls().map((call) => call.name)).not.toContain('evidence.accept');
  });

  it('defers with the note the researcher typed, and asks for more evidence the same way', async () => {
    const daemon = daemonFor();
    renderReview(daemon);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Defer' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Defer' }));
    fireEvent.change(screen.getByLabelText('Why this is being put aside'), {
      target: { value: 'waiting for the appendix' },
    });
    fireEvent.click(screen.getAllByRole('button', { name: 'Defer' })[1]!);

    await waitFor(() => {
      const call = daemon.capabilityCalls().find((entry) => entry.name === 'review.defer');
      expect(call?.request).toEqual({
        candidate_id: ITEM.candidate_id,
        note: 'waiting for the appendix',
      });
    });
  });

  it('captures a request for more evidence against the candidate itself', async () => {
    const daemon = daemonFor();
    renderReview(daemon);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Request more evidence' })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Request more evidence' }));
    fireEvent.change(screen.getByLabelText('What further evidence is needed'), {
      target: { value: 'does the appendix name the capture window?' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Capture the request as a note' }));

    await waitFor(() => {
      const call = daemon.capabilityCalls().find((entry) => entry.name === 'review.request_more');
      expect(call?.request).toEqual({
        candidate_id: ITEM.candidate_id,
        note: 'does the appendix name the capture window?',
      });
    });
    expect(daemon.capabilityCalls().map((call) => call.name)).not.toContain('note.add');
  });

  it('disables every review action for an agent host and explains why', async () => {
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    renderReview(daemonFor(asHost), null);

    await waitFor(() => expect(screen.getByTestId('mutation-blocked')).toBeInTheDocument());
    for (const label of ['Accept', 'Qualify', 'Edit', 'Reject', 'Defer', 'Request more evidence']) {
      expect(screen.getByRole('button', { name: label })).toBeDisabled();
    }
    expect(screen.getByTestId('mutation-blocked').textContent).toContain('agent host');
  });

  it('makes no capability call at all while the cockpit may not accept', async () => {
    const asHost = { ...FIXTURES.overview, principal: 'agent_host', actor: 'http' };
    const daemon = daemonFor(asHost);
    renderReview(daemon, null);

    await waitFor(() => expect(screen.getByTestId('mutation-blocked')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));

    expect(daemon.capabilityCalls().map((call) => call.name)).toEqual(['review.inbox']);
  });

  it('asks for a reason before rejecting, and sends the one it was given', async () => {
    const daemon = daemonFor();
    renderReview(daemon);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    const box = screen.getByLabelText('Why this candidate is refused');
    expect(screen.getAllByRole('button', { name: 'Reject' })[1]!).toBeDisabled();

    fireEvent.change(box, { target: { value: 'the span describes the encoder' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Reject' })[1]!);

    await waitFor(() => {
      const call = daemon.capabilityCalls().find((entry) => entry.name === 'review.reject');
      expect(call?.request).toEqual({
        candidate_id: ITEM.candidate_id,
        reason: 'the span describes the encoder',
      });
    });
  });
});

describe('a candidate carrying an open conflict', () => {
  const CONFLICT = {
    conflict_id: 'CF0001',
    kind: 'provider_disagreement',
    subject: ITEM.candidate_id,
    summary: 'two providers read the same cell differently',
    tier: 2,
    differing_fields: ['value'],
    positions: [],
    proposed_changes: [],
  };

  function conflicted() {
    const withConflict = {
      ...FIXTURES.reviewInbox,
      items: [{ ...ITEM, conflicts: [CONFLICT] }, ...QUEUE.items.slice(1)],
    };
    return fakeDaemon({
      gets: {
        '/overview': FIXTURES.overview,
        [`/candidates/${ITEM.candidate_id}`]: FIXTURES.candidate,
        [`/blocks/${ITEM.artifact}`]: FIXTURES.blocks,
      },
      capabilities: {
        'review.inbox': withConflict,
        'review.accept': outcome('accept', 'E0001'),
        'review.reject': outcome('reject'),
        'review.resolve_conflict': {
          candidate_id: ITEM.candidate_id,
          choice: 'accept',
          mutation: null,
        },
      },
    });
  }

  it('closes the record through `review.resolve_conflict`, which is the only call that does', async () => {
    const daemon = conflicted();
    renderReview(daemon);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Accept' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }));
    fireEvent.change(screen.getByLabelText('Why this side of the conflict is the one to accept'), {
      target: { value: 'row TrafficLM, column F1 of Table 1, read on page 4' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Accept and close the conflict' }));

    await waitFor(() => {
      const call = daemon.capabilityCalls().find((entry) => entry.name === 'review.resolve_conflict');
      expect(call?.request).toEqual({
        candidate_id: ITEM.candidate_id,
        choice: 'accept',
        reason: 'row TrafficLM, column F1 of Table 1, read on page 4',
      });
    });
    expect(daemon.capabilityCalls().map((call) => call.name)).not.toContain('review.accept');
  });

  it('rejects the same way, so the disagreement does not outlive the decision', async () => {
    const daemon = conflicted();
    renderReview(daemon);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Reject' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    fireEvent.change(screen.getByLabelText('Why this candidate is refused'), {
      target: { value: 'the other provider read the right cell' },
    });
    fireEvent.click(screen.getAllByRole('button', { name: 'Reject' })[1]!);

    await waitFor(() => {
      const call = daemon.capabilityCalls().find((entry) => entry.name === 'review.resolve_conflict');
      expect(call?.request).toMatchObject({ choice: 'reject' });
    });
    expect(daemon.capabilityCalls().map((call) => call.name)).not.toContain('review.reject');
  });
});

describe('the diff Product 25 asks for', () => {
  it('renders what each side would change, from and to', () => {
    renderView(
      <ProposedChanges
        changes={[
          { position: 'a/model-x', field: 'verdict', from: 'supported', to: 'contradicted' },
        ]}
      />,
      { daemon: fakeDaemon() },
    );

    expect(screen.getByText('a/model-x')).toBeInTheDocument();
    expect(screen.getByText('Verdict')).toBeInTheDocument();
    expect(screen.getByText('supported')).toBeInTheDocument();
    expect(screen.getByText('contradicted')).toBeInTheDocument();
  });
});

describe('the screen a researcher spends their day on', () => {
  it('has no automatically detectable accessibility violation', async () => {
    const { container } = renderReview();

    await waitFor(() => expect(screen.getByText('Source text')).toBeInTheDocument());
    await expectNoAxeViolations(container);
  });

  it('never prints the candidate’s own identifier, on the card or anywhere else', async () => {
    const { container } = renderReview();

    await waitFor(() => expect(screen.getByText('Source text')).toBeInTheDocument());
    // 2E: `cand_<hex>` is the daemon's handle. The evidence card carries the same name the
    // h1, the queue row and the decide-and-next links use.
    expect(container.textContent ?? '').not.toContain(ITEM.candidate_id);
    expect(container.querySelector('.rh-evidence-card__name')).toHaveTextContent(
      candidateName(ITEM.field, ITEM.work),
    );
    expect(container.querySelector('.rh-evidence-card')).toHaveAttribute(
      'data-evidence-id',
      ITEM.candidate_id,
    );
  });

  it('reaches every review decision from the keyboard, in the order it is read', async () => {
    const user = userEvent.setup();
    renderReview();

    await waitFor(() => expect(screen.getByRole('button', { name: 'Accept' })).toBeEnabled());
    screen.getByRole('button', { name: 'Accept' }).focus();

    for (const next of ['Qualify', 'Edit', 'Reject', 'Defer', 'Request more evidence']) {
      await user.tab();
      expect(screen.getByRole('button', { name: next })).toHaveFocus();
    }
  });
});

describe('the review screen inside a project', () => {
  it('links the Work it is reviewing to the project’s own corpus page', async () => {
    renderView(
      withShell(
        <ProjectPathProvider projectId="prj_abc">
          <EvidenceReviewPage />
        </ProjectPathProvider>,
      ),
      {
        daemon: daemonFor(),
        route: `/projects/prj_abc/review/${ITEM.candidate_id}`,
        path: '/projects/prj_abc/review/:candidateId',
      },
    );

    await waitFor(() => expect(screen.getByText('Proposal')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: ITEM.work })).toHaveAttribute(
      'href',
      `/projects/prj_abc/corpus/${ITEM.work}`,
    );
  });

  it('keeps the legacy corpus link when there is no project', async () => {
    renderReview();

    await waitFor(() => expect(screen.getByText('Proposal')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: ITEM.work })).toHaveAttribute(
      'href',
      `/corpus/${ITEM.work}`,
    );
  });
});

// ---------------------------------------------------------------------------------------
// Decide and move on.
//
// Reviewing is a queue, and the critique's finding was that the cockpit made it a series of
// page loads. The order a researcher moves through is the server's — the same ranking the
// inbox draws — remembered once so that a candidate leaving the queue behind them does not
// renumber what "next" means halfway through an afternoon.
// ---------------------------------------------------------------------------------------

const SECOND = QUEUE.items[1]!;

/** The Decide panel, so an outcome is read where it is recorded rather than in a toast. */
function decidePanel(): HTMLElement {
  return screen.getByRole('heading', { name: 'Decide' }).closest('section') as HTMLElement;
}

/** The daemon with both of the first two candidates readable, so `next` can be opened. */
function daemonForQueue() {
  return fakeDaemon({
    gets: {
      '/overview': FIXTURES.overview,
      [`/candidates/${ITEM.candidate_id}`]: FIXTURES.candidate,
      [`/candidates/${SECOND.candidate_id}`]: {
        ...(FIXTURES.candidate as object),
        candidate_id: SECOND.candidate_id,
        field: SECOND.field,
        work: SECOND.work,
      },
      [`/blocks/${ITEM.artifact}`]: FIXTURES.blocks,
    },
    capabilities: {
      'review.inbox': FIXTURES.reviewInbox,
      'review.defer': outcome('defer', null, 'deferred'),
      'review.accept': outcome('accept', 'E0001'),
    },
  });
}

describe('the queue’s own neighbours', () => {
  it('reads them off the order the server sent, and stops at both ends', () => {
    expect(neighbours(QUEUE.items, ITEM.candidate_id)).toEqual({
      previous: null,
      next: QUEUE.items[1],
    });
    expect(neighbours(QUEUE.items, QUEUE.items[1]!.candidate_id)).toEqual({
      previous: QUEUE.items[0],
      next: QUEUE.items[2],
    });
    expect(neighbours(QUEUE.items, QUEUE.items[2]!.candidate_id).next).toBeNull();
  });

  it('offers nothing for a candidate the remembered queue never held', () => {
    expect(neighbours(QUEUE.items, 'cand_absent')).toEqual({ previous: null, next: null });
  });
});

describe('decide and next', () => {
  it('names the next candidate by its field and its work, as a link', async () => {
    renderReview(daemonForQueue());

    await waitFor(() => expect(screen.getByText('Decide')).toBeInTheDocument());
    expect(
      screen.getByRole('link', {
        name: `Next: ${candidateName(SECOND.field, SECOND.work)}`,
      }),
    ).toHaveAttribute('href', `/review/${SECOND.candidate_id}`);
    expect(screen.queryByRole('link', { name: /^Previous:/ })).not.toBeInTheDocument();
  });

  it('keeps the outcome on screen and still offers the way forward', async () => {
    renderReview(daemonForQueue());

    await waitFor(() => expect(screen.getByRole('button', { name: 'Defer' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Defer' }));
    fireEvent.change(screen.getByLabelText('Why this is being put aside'), {
      target: { value: 'waiting for the appendix' },
    });
    fireEvent.click(screen.getAllByRole('button', { name: 'Defer' })[1]!);

    // The panel keeps the outcome; the toast that also announced it is transient.
    await waitFor(() => expect(decidePanel()).toHaveTextContent('Candidate deferred.'));
    expect(screen.getByRole('link', { name: /^Next:/ })).toBeInTheDocument();
  });

  it('stays on the candidate unless auto-advance was asked for', async () => {
    renderReview(daemonForQueue());

    await waitFor(() => expect(screen.getByRole('button', { name: 'Defer' })).toBeEnabled());
    expect(screen.getByRole('switch', { name: /next candidate/i })).not.toBeChecked();

    fireEvent.click(screen.getByRole('button', { name: 'Defer' }));
    fireEvent.change(screen.getByLabelText('Why this is being put aside'), {
      target: { value: 'waiting for the appendix' },
    });
    fireEvent.click(screen.getAllByRole('button', { name: 'Defer' })[1]!);

    await waitFor(() => expect(decidePanel()).toHaveTextContent('Candidate deferred.'));
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      candidateName(ITEM.field, ITEM.work),
    );
  });

  it('opens the next one when it was, and remembers the choice for next time', async () => {
    const user = userEvent.setup();
    renderReview(daemonForQueue());

    await waitFor(() => expect(screen.getByRole('button', { name: 'Defer' })).toBeEnabled());
    await user.click(screen.getByRole('switch', { name: /next candidate/i }));
    expect(window.localStorage.getItem(AUTO_ADVANCE_KEY)).toBe('true');

    fireEvent.click(screen.getByRole('button', { name: 'Defer' }));
    fireEvent.change(screen.getByLabelText('Why this is being put aside'), {
      target: { value: 'waiting for the appendix' },
    });
    fireEvent.click(screen.getAllByRole('button', { name: 'Defer' })[1]!);

    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        candidateName(SECOND.field, SECOND.work),
      ),
    );
  });

  it('keeps the page frame while it is still reading the candidate', () => {
    renderReview(daemonForQueue());

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(ITEM.candidate_id);
    expect(screen.getByText(/Reading candidate/)).toBeInTheDocument();
  });
});

describe('the review keyboard', () => {
  it('presses the decision the key stands for, rather than calling the daemon itself', async () => {
    const user = userEvent.setup();
    const daemon = daemonForQueue();
    renderReview(daemon);

    await waitFor(() => expect(screen.getByRole('button', { name: 'Defer' })).toBeEnabled());
    await user.keyboard('d');

    // `d` is Defer, and Defer asks for its sentence before anything is recorded.
    expect(screen.getByLabelText('Why this is being put aside')).toBeInTheDocument();
    expect(daemon.capabilityCalls().map((call) => call.name)).not.toContain('review.defer');
  });

  it('stays out of the sentence a decision is being recorded with', async () => {
    const user = userEvent.setup();
    renderReview(daemonForQueue());

    await waitFor(() => expect(screen.getByRole('button', { name: 'Defer' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Defer' }));
    const note = screen.getByLabelText('Why this is being put aside');
    await user.click(note);
    await user.keyboard('needs a decision about anchors');

    expect(note).toHaveValue('needs a decision about anchors');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      candidateName(ITEM.field, ITEM.work),
    );
  });

  it('moves to the next candidate on n and back on p', async () => {
    const user = userEvent.setup();
    renderReview(daemonForQueue());

    await waitFor(() => expect(screen.getByText('Decide')).toBeInTheDocument());
    await user.keyboard('n');

    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        candidateName(SECOND.field, SECOND.work),
      ),
    );

    await user.keyboard('p');
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        candidateName(ITEM.field, ITEM.work),
      ),
    );
  });

  it('lists its keys in the help sheet, so they can be found without being guessed', async () => {
    const user = userEvent.setup();
    renderReview(daemonForQueue());

    await waitFor(() => expect(screen.getByText('Decide')).toBeInTheDocument());
    await user.keyboard('?');

    const sheet = screen.getByRole('dialog', { name: 'Keyboard shortcuts' });
    expect(sheet).toHaveTextContent('Accept');
    expect(sheet).toHaveTextContent('Request more evidence');
    expect(sheet).toHaveTextContent('Next candidate');
  });
});
