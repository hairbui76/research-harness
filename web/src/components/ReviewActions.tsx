/**
 * The six review actions of Product 24.3, and nothing else.
 *
 * Each button is one candidate-keyed `review.*` call carrying the staging id and whatever
 * the researcher typed — never the `Evidence` object the daemon just handed us. That is
 * what settles the queue: the handler allocates the evidence id and marks the candidate
 * reviewed in the same transaction, so a decided proposal leaves the inbox without a
 * second call.
 *
 * One exception, and it is the daemon's rule rather than this component's. When the item
 * carries an open *conflict record*, accept, reject, and defer go through
 * `review.resolve_conflict`: it reaches the same three `EvidenceReviewService` methods and
 * additionally closes the record with the researcher's reason, which nothing else does
 * (`evidence/service.py::resolve_conflict`). Accepting a conflicted proposal through
 * `review.accept` would write the Evidence and leave the disagreement open on the Conflicts
 * screen forever. Which call to make is transport routing; the choice being recorded is the
 * researcher's, and a conflict is never resolved by a heuristic (Product 25).
 *
 * None of them decides anything else. Whether a candidate *may* be accepted is settled by
 * the review gate behind these capabilities (ADR-003, ADR-007), and a refusal is rendered as
 * it came back. Without the local token every control is disabled with the reason attached,
 * because an agent host reads and proposes and the researcher accepts (Product 29).
 */
import { useState } from 'react';
import type { CandidateView, Json } from '../api/dto';
import { useSession } from '../app/session';
import { JsonEditor } from './JsonEditor';

export interface ReviewActionsProps {
  candidate: CandidateView;
  /**
   * True when `review.inbox` reported an open conflict record about this candidate. It is
   * the daemon's judgement, read off the queue item and never recomputed here.
   */
  hasOpenConflict?: boolean;
  onReviewed: (summary: string) => void;
}

type Prompt = 'accept' | 'qualify' | 'reject' | 'defer' | 'more' | 'edit' | null;

export function ReviewActions({ candidate, hasOpenConflict, onReviewed }: ReviewActionsProps) {
  const { client, canMutate, mutationBlockedReason, refresh } = useSession();
  const [prompt, setPrompt] = useState<Prompt>(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(what: string, action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setPrompt(null);
      setText('');
      refresh();
      onReviewed(what);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  const disabled = !canMutate || busy;
  const why = mutationBlockedReason ?? undefined;

  return (
    <div className="review-actions">
      <div className="actions">
        <button
          type="button"
          disabled={disabled}
          title={why}
          onClick={() =>
            hasOpenConflict
              ? setPrompt('accept')
              : run('accepted', () => client.acceptCandidate(candidate.candidate_id))
          }
        >
          Accept
        </button>
        <button type="button" disabled={disabled} title={why} onClick={() => setPrompt('qualify')}>
          Accept with qualification
        </button>
        <button type="button" disabled={disabled} title={why} onClick={() => setPrompt('edit')}>
          Edit
        </button>
        <button type="button" disabled={disabled} title={why} onClick={() => setPrompt('reject')}>
          Reject
        </button>
        <button type="button" disabled={disabled} title={why} onClick={() => setPrompt('defer')}>
          Defer
        </button>
        <button type="button" disabled={disabled} title={why} onClick={() => setPrompt('more')}>
          Request more evidence
        </button>
      </div>

      {!canMutate ? (
        <p className="muted" data-testid="mutation-blocked">
          {mutationBlockedReason}
        </p>
      ) : null}

      {prompt === 'edit' ? (
        <JsonEditor
          value={candidate.evidence as Json}
          busy={busy}
          disabled={disabled}
          onCancel={() => setPrompt(null)}
          onSubmit={(edited) =>
            run('accepted the edit', () => client.editCandidate(candidate.candidate_id, edited))
          }
        />
      ) : null}

      {prompt && prompt !== 'edit' ? (
        <form
          className="prompt"
          onSubmit={(event) => {
            event.preventDefault();
            if (!text.trim()) return;
            if (prompt === 'accept') {
              void run('accepted', () =>
                client.resolveCandidate(candidate.candidate_id, 'accept', text),
              );
            } else if (prompt === 'qualify') {
              void run('accepted with a qualification', () =>
                client.qualifyCandidate(candidate.candidate_id, text),
              );
            } else if (prompt === 'reject') {
              void run('rejected', () =>
                hasOpenConflict
                  ? client.resolveCandidate(candidate.candidate_id, 'reject', text)
                  : client.rejectCandidate(candidate.candidate_id, text),
              );
            } else if (prompt === 'defer') {
              void run('deferred', () =>
                hasOpenConflict
                  ? client.resolveCandidate(candidate.candidate_id, 'defer', text)
                  : client.deferCandidate(candidate.candidate_id, text),
              );
            } else {
              void run('asked for more evidence', () =>
                client.requestMoreEvidence(candidate.candidate_id, text),
              );
            }
          }}
        >
          <label htmlFor="review-note">{PROMPT_LABELS[prompt]}</label>
          <textarea
            id="review-note"
            rows={3}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <div className="actions">
            <button type="submit" disabled={disabled || !text.trim()}>
              {PROMPT_SUBMIT[prompt]}
            </button>
            <button type="button" className="secondary" onClick={() => setPrompt(null)}>
              Cancel
            </button>
          </div>
        </form>
      ) : null}

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

const PROMPT_LABELS: Record<Exclude<Prompt, null | 'edit'>, string> = {
  accept: 'Why this side of the conflict is the one to accept',
  qualify: 'Qualification recorded with the acceptance',
  reject: 'Why this candidate is refused',
  defer: 'Why this is being put aside',
  more: 'What further evidence is needed',
};

const PROMPT_SUBMIT: Record<Exclude<Prompt, null | 'edit'>, string> = {
  accept: 'Accept and close the conflict',
  qualify: 'Accept with qualification',
  reject: 'Reject',
  defer: 'Defer',
  more: 'Capture the request as a note',
};
