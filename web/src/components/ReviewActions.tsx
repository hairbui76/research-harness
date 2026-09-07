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
 * Accepting is the one decision that asks twice. It writes accepted scientific state —
 * `review.accept` allocates a real `EvidenceId` and the candidate leaves the queue — and
 * no `review.*` capability reopens or undoes that; a later change of mind is a Decision
 * (PRODUCT §38), not a deletion. So the first press restates what is about to be written,
 * in the field, Work and quote it will be written about, and the second press writes it.
 * The confirmation is inline rather than a dialog because the source pane beside it is
 * exactly what the researcher should still be reading while they decide.
 *
 * One exception, and it is the daemon's rule rather than this component's. When the item
 * carries an open *conflict record*, accept, reject, and defer go through
 * `review.resolve_conflict`: it reaches the same three `EvidenceReviewService` methods and
 * additionally closes the record with the researcher's reason, which nothing else does
 * (`evidence/service.py::resolve_conflict`). Accepting a conflicted proposal through
 * `review.accept` would write the Evidence and leave the disagreement open on the Conflicts
 * screen forever. Which call to make is transport routing; the choice being recorded is the
 * researcher's, and a conflict is never resolved by a heuristic (PRODUCT §25). That path
 * already demands a sentence before it will run, so it is not asked to confirm twice.
 *
 * None of them decides anything else. Whether a candidate *may* be accepted is settled by
 * the review gate behind these capabilities (ADR-003, ADR-007), and a refusal is rendered as
 * it came back. Without the local token every control is disabled with the reason attached,
 * because an agent host reads and proposes and the researcher accepts (PRODUCT §29).
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Dialog,
  DialogBody,
  DialogHeader,
  ErrorNotice,
  REVIEW_DECISIONS,
  REVIEW_DECISION_META,
  ReviewDecisionBar,
  Textarea,
  useToast,
} from '@research-harness/design';
import type { ReviewDecision } from '@research-harness/design';
import type { CandidateView, Json, JsonObject } from '../api/dto';
import { useProjectPaths } from '../app/projectPaths';
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

/** The longest a quote is restated at before the sentence stops being one. */
const QUOTE_LIMIT = 140;

export function ReviewActions({ candidate, hasOpenConflict, onReviewed }: ReviewActionsProps) {
  const { client, canMutate, mutationBlockedReason, refresh } = useSession();
  const { href } = useProjectPaths();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState<ReviewDecision | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement | null>(null);
  const confirmButton = useRef<HTMLButtonElement | null>(null);

  // The confirmation is a second question, so it takes the caret: Enter answers it and
  // Escape abandons it without the researcher hunting for either control.
  useEffect(() => {
    if (confirming) confirmButton.current?.focus();
  }, [confirming]);

  /** Back to the decision that opened the confirmation, so the queue is still operable. */
  function abandonAcceptance() {
    setConfirming(false);
    const accept = root.current?.querySelector<HTMLButtonElement>('[data-decision="accept"]');
    accept?.focus();
  }

  async function run(
    decision: ReviewDecision,
    what: string,
    wrote: string,
    action: () => Promise<unknown>,
  ) {
    setBusy(decision);
    setError(null);
    try {
      const result = await action();
      setPrompt(null);
      setEditing(false);
      setConfirming(false);
      setText('');
      refresh();
      onReviewed(what);
      announce(decision, what, wrote, result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(undefined);
    }
  }

  /**
   * What was written, and where it now lives.
   *
   * An acceptance answers with the `EvidenceId` it allocated, so the toast names it and
   * offers the page it is on. Nothing offers an undo, because the daemon has none: adding
   * one would be a button that either lies or writes a second decision the researcher did
   * not ask for.
   *
   * The tone follows the same rule the sentence does. Success belongs to the three
   * decisions that write accepted Evidence; a rejection, a deferral and a request for more
   * evidence accepted nothing, and their own toasts say so, so a congratulatory tone would
   * contradict the words beside it.
   */
  function announce(decision: ReviewDecision, what: string, wrote: string, result: unknown) {
    const tone = ACCEPTS[decision] ? 'success' : 'info';
    const evidenceId = evidenceIdOf(result);
    if (evidenceId === null) {
      toast({ tone, title: `Candidate ${what}.`, description: wrote });
      return;
    }
    const route = href(`/evidence/${encodeURIComponent(evidenceId)}`);
    toast({
      tone,
      title: `Accepted as ${evidenceId}`,
      description: `${candidate.field} of ${candidate.work}. ${wrote}`,
      action: { label: `Open ${evidenceId}`, onClick: () => navigate(route) },
    });
  }

  /** What a decision does when it is chosen: confirm, open the editor, or ask for a sentence. */
  function decide(decision: ReviewDecision) {
    if (decision === 'edit') {
      setConfirming(false);
      setEditing(true);
      return;
    }
    if (decision === 'accept' && !hasOpenConflict) {
      setPrompt(null);
      setConfirming(true);
      return;
    }
    setConfirming(false);
    setPrompt(decision);
    setText('');
  }

  function submitPrompt(decision: Prompt) {
    const note = text.trim();
    if (!note) return;
    if (decision === 'accept') {
      void run(decision, 'accepted', CLOSES_THE_CONFLICT.accept, () =>
        client.resolveCandidate(candidate.candidate_id, 'accept', note),
      );
    } else if (decision === 'qualify') {
      void run(decision, 'accepted with a qualification', WROTE.qualify, () =>
        client.qualifyCandidate(candidate.candidate_id, note),
      );
    } else if (decision === 'reject') {
      void run(
        decision,
        'rejected',
        hasOpenConflict ? CLOSES_THE_CONFLICT.reject : WROTE.reject,
        () =>
          hasOpenConflict
            ? client.resolveCandidate(candidate.candidate_id, 'reject', note)
            : client.rejectCandidate(candidate.candidate_id, note),
      );
    } else if (decision === 'defer') {
      void run(decision, 'deferred', hasOpenConflict ? CLOSES_THE_CONFLICT.defer : WROTE.defer, () =>
        hasOpenConflict
          ? client.resolveCandidate(candidate.candidate_id, 'defer', note)
          : client.deferCandidate(candidate.candidate_id, note),
      );
    } else {
      void run(decision, 'asked for more evidence', WROTE.request_more_evidence, () =>
        client.requestMoreEvidence(candidate.candidate_id, note),
      );
    }
  }

  const blockedReason = canMutate ? undefined : (mutationBlockedReason ?? undefined);
  const quote = quoteOf(candidate);

  return (
    <div className="rh-web-stack rh-web-stack--tight" ref={root}>
      <ReviewDecisionBar
        available={REVIEW_DECISIONS}
        onDecide={decide}
        data-testid={blockedReason ? 'mutation-blocked' : undefined}
        {...(blockedReason === undefined ? {} : { disabledReason: blockedReason })}
        {...(busy === undefined ? {} : { busy })}
      />

      {confirming && canMutate ? (
        <div
          role="group"
          aria-label="Confirm the acceptance"
          className="rh-web-prompt rh-web-stack rh-web-stack--tight"
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return;
            event.stopPropagation();
            abandonAcceptance();
          }}
        >
          <p>{restatement(candidate, quote)}</p>
          <p className="rh-text-secondary">
            No review action takes an acceptance back. A later change of mind is recorded as a
            Decision beside it, not a deletion.
          </p>
          <div className="rh-web-row">
            <Button
              ref={confirmButton}
              variant="primary"
              size="sm"
              loading={busy === 'accept'}
              loadingLabel="Recording the acceptance"
              disabled={busy !== undefined && busy !== 'accept'}
              onClick={() =>
                void run('accept', 'accepted', WROTE.accept, () =>
                  client.acceptCandidate(candidate.candidate_id),
                )
              }
            >
              Accept as evidence
            </Button>
            <Button variant="ghost" size="sm" onClick={abandonAcceptance}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      {editing ? (
        <Dialog open onOpenChange={(open) => setEditing(open)} size="lg">
          <DialogHeader>Edit the proposed evidence</DialogHeader>
          <DialogBody>
            <p className="rh-text-secondary">
              Saving accepts your wording, not the proposal: the corrected content becomes
              accepted Evidence and the source anchor is unchanged.
            </p>
            <JsonEditor
              value={candidate.evidence as Json}
              busy={busy === 'edit'}
              disabled={!canMutate || busy !== undefined}
              onCancel={() => setEditing(false)}
              onSubmit={(edited) =>
                run('edit', 'accepted the edit', WROTE.edit, () =>
                  client.editCandidate(candidate.candidate_id, edited),
                )
              }
            />
          </DialogBody>
        </Dialog>
      ) : null}

      {prompt ? (
        <form
          aria-label={REVIEW_DECISION_META[prompt].label}
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
          {/* The sentence the button is short for: what this records, and what it does not. */}
          <p className="rh-text-secondary">
            {prompt === 'accept' || (hasOpenConflict && (prompt === 'reject' || prompt === 'defer'))
              ? CLOSES_THE_CONFLICT[prompt]
              : WROTE[prompt]}
          </p>
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

/**
 * The sentence the researcher is agreeing to, in the field, Work and quote it is about.
 *
 * A candidate with no quoted span still gets a sentence rather than a pair of empty
 * quotation marks: the anchor, not the prose, is what makes it evidence.
 */
function restatement(candidate: CandidateView, quote: string): string {
  const opening = `Accept as evidence for ${candidate.field} of ${candidate.work}: `;
  const subject = quote === '' ? 'this proposal becomes' : `“${quote}” becomes`;
  return `${opening}${subject} accepted Evidence in this project, recorded with you as the reviewer.`;
}

/** The exact span being proposed, short enough to stay inside one restated sentence. */
function quoteOf(candidate: CandidateView): string {
  const evidence = (candidate.evidence ?? {}) as JsonObject;
  const content = (evidence.content ?? {}) as JsonObject;
  const text = String(content.exact_text ?? '').trim();
  if (text.length <= QUOTE_LIMIT) return text;
  return `${text.slice(0, QUOTE_LIMIT).trimEnd()}…`;
}

/** The `EvidenceId` a `ReviewOutcome` allocated, when the action created one. */
function evidenceIdOf(result: unknown): string | null {
  if (typeof result !== 'object' || result === null) return null;
  const evidence = (result as { evidence?: unknown }).evidence;
  return typeof evidence === 'string' && evidence.length > 0 ? evidence : null;
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

/**
 * What each decision leaves behind, in the researcher's terms.
 *
 * These are read off the handlers rather than guessed: a rejection is written to the
 * Work's rejections file and nothing is accepted, a deferral is a note to the researcher's
 * future self, and a request for more evidence is recorded as a low-authority note.
 */
const WROTE: Record<ReviewDecision, string> = {
  accept: 'It is accepted Evidence in this project now.',
  qualify: 'It is accepted Evidence, carrying the qualification you wrote.',
  edit: 'Your corrected wording is what was accepted, against the same source anchor.',
  reject: 'The reason is recorded with the Work; nothing is accepted.',
  defer: 'It stays in the review queue with your note; nothing is accepted.',
  request_more_evidence: 'Your question is recorded as a note; nothing is accepted.',
};

/**
 * Which decisions write accepted state.
 *
 * Read off `WROTE` above: accept, qualify and edit each leave accepted Evidence behind, and
 * the other three end with "nothing is accepted". Only the first three may wear the success
 * tone.
 */
const ACCEPTS: Record<ReviewDecision, boolean> = {
  accept: true,
  qualify: true,
  edit: true,
  reject: false,
  defer: false,
  request_more_evidence: false,
};

/** The same three decisions when a conflict record is open, which they also close. */
const CLOSES_THE_CONFLICT: Record<'accept' | 'reject' | 'defer', string> = {
  accept: 'It becomes accepted Evidence and the conflict record closes with your reason.',
  reject: 'The conflict record closes with your reason; nothing is accepted.',
  defer: 'It stays in the queue and the conflict record closes with your reason.',
};
