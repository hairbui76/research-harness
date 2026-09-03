/**
 * The six review actions of PRODUCT §24.3, and nothing else.
 *
 * The bar is the Design System's `ReviewDecisionBar`: it renders the decisions this host
 * offers, reports the one chosen, and prints the reason when none may be recorded. It
 * knows nothing about what a decision means — this component maps each `ReviewDecision`
 * onto one candidate-keyed `review.*` call carrying the staging id and whatever the
 * researcher typed, never the `Evidence` object the daemon just handed us. That is what
 * settles the queue: the handler allocates the evidence id and marks the candidate
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
 * researcher's, and a conflict is never resolved by a heuristic (PRODUCT §25).
 *
 * None of them decides anything else. Whether a candidate *may* be accepted is settled by
 * the review gate behind these capabilities (ADR-003, ADR-007), and a refusal is rendered as
 * it came back. Without the local token every control is disabled with the reason attached,
 * because an agent host reads and proposes and the researcher accepts (PRODUCT §29).
 */
import { useState } from 'react';
import {
  Button,
  Dialog,
  DialogBody,
  DialogHeader,
  ErrorNotice,
  REVIEW_DECISIONS,
  ReviewDecisionBar,
  Textarea,
  useToast,
} from '@research-harness/design';
import type { ReviewDecision } from '@research-harness/design';
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

/** The five decisions that ask for a sentence before they are recorded. */
type Prompt = Exclude<ReviewDecision, 'edit'>;

export function ReviewActions({ candidate, hasOpenConflict, onReviewed }: ReviewActionsProps) {
  const { client, canMutate, mutationBlockedReason, refresh } = useSession();
  const { toast } = useToast();
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState<ReviewDecision | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  async function run(decision: ReviewDecision, what: string, action: () => Promise<unknown>) {
    setBusy(decision);
    setError(null);
    try {
      await action();
      setPrompt(null);
      setEditing(false);
      setText('');
      refresh();
      onReviewed(what);
      toast({ tone: 'success', title: `Candidate ${what}.` });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(undefined);
    }
  }

  /** What a decision does when it is chosen: open the editor, ask for a sentence, or run. */
  function decide(decision: ReviewDecision) {
    if (decision === 'edit') {
      setEditing(true);
      return;
    }
    if (decision === 'accept' && !hasOpenConflict) {
      void run('accept', 'accepted', () => client.acceptCandidate(candidate.candidate_id));
      return;
    }
    setPrompt(decision);
    setText('');
  }

  function submitPrompt(decision: Prompt) {
    const note = text.trim();
    if (!note) return;
    if (decision === 'accept') {
      void run(decision, 'accepted', () =>
        client.resolveCandidate(candidate.candidate_id, 'accept', note),
      );
    } else if (decision === 'qualify') {
      void run(decision, 'accepted with a qualification', () =>
        client.qualifyCandidate(candidate.candidate_id, note),
      );
    } else if (decision === 'reject') {
      void run(decision, 'rejected', () =>
        hasOpenConflict
          ? client.resolveCandidate(candidate.candidate_id, 'reject', note)
          : client.rejectCandidate(candidate.candidate_id, note),
      );
    } else if (decision === 'defer') {
      void run(decision, 'deferred', () =>
        hasOpenConflict
          ? client.resolveCandidate(candidate.candidate_id, 'defer', note)
          : client.deferCandidate(candidate.candidate_id, note),
      );
    } else {
      void run(decision, 'asked for more evidence', () =>
        client.requestMoreEvidence(candidate.candidate_id, note),
      );
    }
  }

  const blockedReason = canMutate ? undefined : (mutationBlockedReason ?? undefined);

  return (
    <div className="rh-web-stack rh-web-stack--tight">
      <ReviewDecisionBar
        available={REVIEW_DECISIONS}
        onDecide={decide}
        data-testid={blockedReason ? 'mutation-blocked' : undefined}
        {...(blockedReason === undefined ? {} : { disabledReason: blockedReason })}
        {...(busy === undefined ? {} : { busy })}
      />

      {editing ? (
        <Dialog open onOpenChange={(open) => setEditing(open)} size="lg">
          <DialogHeader>Edit the proposed evidence</DialogHeader>
          <DialogBody>
            <JsonEditor
              value={candidate.evidence as Json}
              busy={busy === 'edit'}
              disabled={!canMutate || busy !== undefined}
              onCancel={() => setEditing(false)}
              onSubmit={(edited) =>
                run('edit', 'accepted the edit', () =>
                  client.editCandidate(candidate.candidate_id, edited),
                )
              }
            />
          </DialogBody>
        </Dialog>
      ) : null}

      {prompt ? (
        <form
          className="rh-web-prompt rh-web-stack rh-web-stack--tight"
          onSubmit={(event) => {
            event.preventDefault();
            submitPrompt(prompt);
          }}
        >
          <Textarea
            id="review-note"
            label={PROMPT_LABELS[prompt]}
            rows={3}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <div className="rh-web-row">
            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={!canMutate || busy !== undefined || !text.trim()}
            >
              {PROMPT_SUBMIT[prompt]}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setPrompt(null)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}

      {error ? (
        <ErrorNotice
          kind="retryable"
          title="The daemon refused that decision"
          description={error}
          safety={{ draft: 'safe', source: 'safe' }}
          onDismiss={() => setError(null)}
        />
      ) : null}
    </div>
  );
}

const PROMPT_LABELS: Record<Prompt, string> = {
  accept: 'Why this side of the conflict is the one to accept',
  qualify: 'Qualification recorded with the acceptance',
  reject: 'Why this candidate is refused',
  defer: 'Why this is being put aside',
  request_more_evidence: 'What further evidence is needed',
};

const PROMPT_SUBMIT: Record<Prompt, string> = {
  accept: 'Accept and close the conflict',
  qualify: 'Accept with qualification',
  reject: 'Reject',
  defer: 'Defer',
  request_more_evidence: 'Capture the request as a note',
};
