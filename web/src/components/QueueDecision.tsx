/**
 * The decisions a queue row carries, at every tier, and the one it does not.
 *
 * The review screen is where a proposal is *read* — the page it came off, the number's
 * provenance, the verifier's rationale, the competing readings. What a researcher does with
 * that reading splits in two, and the split is Product 26's: **acceptance** writes authority
 * into the project, and the source belongs beside that decision; **refusing** a proposal and
 * **putting one aside** write no evidence, and the page it was read off would not change
 * either one. So the row offers those two at every tier, and the screen keeps the acceptance
 * of anything the daemon has not already filed as routine.
 *
 * What a row therefore shows:
 *
 * - **Accept**, only where `acceptableInQueue` holds — the daemon's own routine filing:
 *   verified, supported, tier 0 or 1, anchor valid. It still asks twice. The first press
 *   restates what is about to be written, in the field, the Work and the quoted span it will
 *   be written about — the same sentence the review screen uses, from the same function —
 *   and the second press writes it. The confirmation is inline on the card, because the row
 *   it is about is what should still be readable while the decision is made.
 * - **Reject** and **Defer**, on every row, taking the researcher's sentence exactly as the
 *   review screen does, because that is what the daemon records with them. The field is a
 *   compact one on the row itself: a dialog would cover the queue the decision is about.
 *   They are read in the order `REVIEW_DECISIONS` declares, which is the order the review
 *   bar reads: one vocabulary, one sequence, on both screens.
 * - **Open to decide**, on every row: the screen where the source sits, where Accept lives
 *   for a deeper review, and where Qualify, Edit and Request more evidence live for all of
 *   them. A row that withholds Accept says so in a sentence rather than leaving its absence
 *   to be read as a defect.
 *
 * Three rules hold all of it to the same standard as the full bar:
 *
 * - **Nothing fakes an undo.** No `review.*` capability reopens an acceptance, so the row
 *   says so before the write and offers nothing afterwards but the evidence it created.
 * - **The queue's order is the daemon's.** Deciding removes a candidate from the queue by
 *   re-reading it; nothing here re-ranks, re-sorts or promotes a row.
 * - **A conflict is closed, never stepped past.** When the daemon reported an open conflict
 *   record about this candidate, Defer and Reject go through `review.resolve_conflict` —
 *   the same routing `ReviewActions` uses, for the same reason: a rejection that left the
 *   record open would leave the disagreement on the Conflicts screen forever.
 */
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  REVIEW_DECISIONS,
  REVIEW_DECISION_META,
  Textarea,
  useToast,
} from '@research-harness/design';
import type { ReviewDecision } from '@research-harness/design';
import type { ReviewItem } from '../api/dto';
import { useProjectPaths } from '../app/projectPaths';
import { useSession } from '../app/session';
import {
  CLOSES_THE_CONFLICT,
  PROMPT_LABELS,
  PROMPT_SUBMIT,
  WROTE,
  restatementFor,
  shortQuote,
} from './ReviewActions';
import { ErrorBox, candidateName, fieldLabel } from './Feedback';

/**
 * The decisions a row can carry, in the one order both review surfaces read them in.
 *
 * The order is not written here. `REVIEW_DECISIONS` declares it once — Accept, Qualify,
 * Edit, Reject, Defer, Request more evidence — and the review bar renders that list
 * whole; the row renders the part of it a row offers, filtered rather than retyped. A
 * researcher who decides one candidate on the queue and the next beside its source reads
 * the same verbs in the same order, and a decision added to the vocabulary cannot arrive
 * in two different places on the two screens.
 */
export const ROW_DECISIONS: readonly ReviewDecision[] = REVIEW_DECISIONS.filter(
  (decision) => decision === 'accept' || decision === 'reject' || decision === 'defer',
);

/** The two a row offers at every tier: neither writes evidence, so neither needs the source. */
const SENTENCE_DECISIONS = ROW_DECISIONS.filter(
  (decision): decision is 'defer' | 'reject' => decision !== 'accept',
);
type RowDecision = 'accept' | 'defer' | 'reject';

/**
 * Whether this row may be *accepted* where it sits.
 *
 * The daemon's own filing, and nothing computed here: the routine category *is* "verified
 * supported, Tier 0 or 1, and the anchor is valid". A conflict, a high-risk claim, a stale
 * anchor or an ambiguous extraction is a deep review, and an acceptance it writes is taken
 * beside the source (Product 26) rather than off a queue row.
 */
export function acceptableInQueue(item: ReviewItem): boolean {
  return item.category === 'routine' && item.tier <= 1;
}

export interface QueueDecisionProps {
  item: ReviewItem;
  /**
   * Re-read the queue. A decided candidate leaves it; nothing is removed here. The id is
   * passed back so the page can put the focus where the queue's own order says next.
   */
  onDecided: (candidateId: string) => void;
}

export function QueueDecision({ item, onDecided }: QueueDecisionProps) {
  const { client, canMutate, refresh } = useSession();
  const { href } = useProjectPaths();
  const { toast } = useToast();
  const [open, setOpen] = useState<RowDecision | null>(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState<RowDecision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const confirmButton = useRef<HTMLButtonElement | null>(null);
  const root = useRef<HTMLDivElement | null>(null);

  // The confirmation is a second question, so it takes the caret: Enter answers it and
  // Escape abandons it without hunting for either control.
  useEffect(() => {
    if (open === 'accept') confirmButton.current?.focus();
  }, [open]);

  if (!canMutate) return null;

  const name = candidateName(item.field, item.work);
  const quote = shortQuote(item.exact_text);
  const acceptable = acceptableInQueue(item);
  const decisions: RowDecision[] = (
    acceptable ? ROW_DECISIONS : SENTENCE_DECISIONS
  ) as RowDecision[];
  // The daemon's judgement, read off the queue item and never recomputed here.
  const hasOpenConflict = item.conflicts.length > 0;
  /** What the decision leaves behind, in the researcher's terms — the conflict included. */
  const wrote = (decision: 'defer' | 'reject'): string =>
    hasOpenConflict ? CLOSES_THE_CONFLICT[decision] : WROTE[decision];

  function abandon(): void {
    const opened = open;
    setOpen(null);
    setText('');
    setError(null);
    root.current
      ?.querySelector<HTMLButtonElement>(`[data-decision="${opened ?? decisions[0]}"]`)
      ?.focus();
  }

  async function run(
    decision: RowDecision,
    what: string,
    wrote: string,
    action: () => Promise<unknown>,
  ) {
    setBusy(decision);
    setError(null);
    try {
      await action();
      setOpen(null);
      setText('');
      // A write is announced the way the review screen announces it: politely, once, the
      // tone belonging to the decisions that accept something, and nothing offers an undo.
      toast({
        tone: decision === 'accept' ? 'success' : 'info',
        title: `${name} ${what}.`,
        description: wrote,
      });
      refresh();
      onDecided(item.candidate_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="rh-web-queue-decision rh-web-stack rh-web-stack--tight" ref={root}>
      <div className="rh-web-row" role="group" aria-label={`Decide ${name}`}>
        {decisions.map((decision) => {
          const meta = REVIEW_DECISION_META[decision];
          return (
            <Button
              key={decision}
              size="sm"
              variant={decision === 'accept' ? 'secondary' : 'ghost'}
              iconStart={meta.icon}
              data-decision={decision}
              disabled={busy !== null && busy !== decision}
              onClick={() => {
                setError(null);
                setText('');
                setOpen((current) => (current === decision ? null : decision));
              }}
            >
              {meta.label}
            </Button>
          );
        })}
        {/* The screen where the source is: the acceptance of a deeper review is taken
            there, and so are the three decisions no row offers at any tier. */}
        <Link to={href(`/review/${item.candidate_id}`)}>Open to decide</Link>
      </div>

      {acceptable ? null : (
        <p className="rh-text-secondary">
          Accepting it happens beside the source, on its own screen.
        </p>
      )}

      {open === 'accept' ? (
        <div
          role="group"
          aria-label={`Confirm the acceptance of ${name}`}
          className="rh-web-prompt rh-web-stack rh-web-stack--tight"
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return;
            event.stopPropagation();
            abandon();
          }}
        >
          <p>{restatementFor(fieldLabel(item.field), item.work, quote)}</p>
          <p className="rh-text-secondary">
            No review action takes an acceptance back. A later change of mind is recorded as a
            Decision beside it, not a deletion.
          </p>
          <div className="rh-web-row">
            <Button
              ref={confirmButton}
              size="sm"
              variant="primary"
              loading={busy === 'accept'}
              loadingLabel="Recording the acceptance"
              onClick={() =>
                void run('accept', 'accepted', WROTE.accept, () =>
                  client.acceptCandidate(item.candidate_id),
                )
              }
            >
              Accept as evidence
            </Button>
            <Button size="sm" variant="ghost" onClick={abandon}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      {open === 'defer' || open === 'reject' ? (
        <form
          aria-label={`${REVIEW_DECISION_META[open].label} ${name}`}
          className="rh-web-prompt rh-web-stack rh-web-stack--tight"
          onSubmit={(event) => {
            event.preventDefault();
            const note = text.trim();
            if (!note || open === null) return;
            if (open === 'defer') {
              void run('defer', 'deferred', wrote('defer'), () =>
                hasOpenConflict
                  ? client.resolveCandidate(item.candidate_id, 'defer', note)
                  : client.deferCandidate(item.candidate_id, note),
              );
            } else {
              void run('reject', 'rejected', wrote('reject'), () =>
                hasOpenConflict
                  ? client.resolveCandidate(item.candidate_id, 'reject', note)
                  : client.rejectCandidate(item.candidate_id, note),
              );
            }
          }}
        >
          <Textarea
            label={PROMPT_LABELS[open]}
            rows={2}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <p className="rh-text-secondary">{wrote(open)}</p>
          <div className="rh-web-row">
            <Button
              type="submit"
              size="sm"
              variant="primary"
              loading={busy === open}
              loadingLabel={`Recording the ${REVIEW_DECISION_META[open].label.toLowerCase()}`}
              disabled={!text.trim()}
            >
              {PROMPT_SUBMIT[open]}
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={abandon}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}

      {error ? <ErrorBox error={error} /> : null}
    </div>
  );
}
