/**
 * Task 11.3: the researcher never decides without the source, and never accepts without
 * the authority to.
 *
 * The two properties asserted here are the ones the gate rests on. First, the exact span
 * and the block it sits in are on screen beside the proposal (Product 25). Second, without
 * the local token every review control is disabled and says why: an agent host reads and
 * proposes, and the researcher accepts (Product 29, ADR-007).
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReviewItem } from '../api/dto';
import { EvidenceReviewPage, ProposedChanges } from './EvidenceReview';
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

function renderReview(daemon = daemonFor(), token: string | null = 'local-token') {
  return renderView(<EvidenceReviewPage />, {
    daemon,
    token,
    route: `/review/${ITEM.candidate_id}`,
    path: '/review/:candidateId',
  });
}

describe('source beside decision', () => {
  it('shows the exact span, the block it sits in, and the field it answers', async () => {
    renderReview();

    await waitFor(() => expect(screen.getByText('Source text')).toBeInTheDocument());
    expect(screen.getAllByText(ITEM.source_context.exact_text).length).toBeGreaterThan(0);
    expect(screen.getByText('Anchor')).toBeInTheDocument();
    expect(screen.getAllByText(ITEM.field).length).toBeGreaterThan(0);
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
    expect(screen.getByText('supported')).toBeInTheDocument();
    expect(container.textContent?.toLowerCase()).not.toContain('confidence');
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
