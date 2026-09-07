/**
 * The three decisions a routine candidate can be given from the queue itself.
 *
 * The review screen is where a proposal is *read* — the page it came off, the number's
 * provenance, the verifier's rationale, the competing readings. A tier 0 or 1 candidate the
 * daemon has already filed as routine has none of that to argue about: it is verified,
 * supported, its anchor is valid, and the researcher's part is the decision. So the row
 * offers the decision, and the screen stays one click away for everything else.
 *
 * Three rules hold it to the same standard as the full bar:
 *
 * - **Accepting still asks twice.** The first press restates what is about to be written,
 *   in the field, the Work and the quoted span it will be written about — the same sentence
 *   the review screen uses, from the same function — and the second press writes it. The
 *   confirmation is inline on the card, because the row it is about is what should still be
 *   readable while the decision is made.
 * - **Nothing fakes an undo.** No `review.*` capability reopens an acceptance, so the row
 *   says so before the write and offers nothing afterwards but the evidence it created.
 * - **The queue's order is the daemon's.** Deciding removes a candidate from the queue by
 *   re-reading it; nothing here re-ranks, re-sorts or promotes a row.
 *
 * Rejecting and deferring take the researcher's sentence, exactly as they do on the review
 * screen, because that is what the daemon records with them.
 */
import { useEffect, useRef, useState } from 'react';
import { Button, REVIEW_DECISION_META, Textarea, useToast } from '@research-harness/design';
import type { ReviewItem } from '../api/dto';
import { useSession } from '../app/session';
import {
  PROMPT_LABELS,
  PROMPT_SUBMIT,
  WROTE,
  restatementFor,
  shortQuote,
} from './ReviewActions';
import { ErrorBox, candidateName, fieldLabel } from './Feedback';

/** The three decisions a routine row offers, in the order they are read. */
const ROW_DECISIONS = ['accept', 'defer', 'reject'] as const;
type RowDecision = (typeof ROW_DECISIONS)[number];

/**
 * Whether this row may be decided where it sits.
 *
 * The daemon's own filing, and nothing computed here: the routine category *is* "verified
 * supported, Tier 0 or 1, and the anchor is valid". A conflict, a high-risk claim, a stale
 * anchor or an ambiguous extraction is read before it is decided, and keeps the full screen.
 */
export function decidableInQueue(item: ReviewItem): boolean {
  return item.category === 'routine' && item.tier <= 1;
}

export interface QueueDecisionProps {
  item: ReviewItem;
  /** Re-read the queue. A decided candidate leaves it; nothing is removed here. */
  onDecided: () => void;
}

export function QueueDecision({ item, onDecided }: QueueDecisionProps) {
  const { client, canMutate, refresh } = useSession();
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

  function abandon(): void {
    setOpen(null);
    setText('');
    setError(null);
    root.current?.querySelector<HTMLButtonElement>('[data-decision="accept"]')?.focus();
  }

  async function run(decision: RowDecision, what: string, action: () => Promise<unknown>) {
    setBusy(decision);
    setError(null);
    try {
      await action();
      setOpen(null);
      setText('');
      // A write of accepted state is announced the way the review screen announces it: the
      // tone belongs to the decisions that accept something, and nothing offers an undo.
      toast({
        tone: decision === 'accept' ? 'success' : 'info',
        title: `${name} ${what}.`,
        description: WROTE[decision],
      });
      refresh();
      onDecided();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="rh-web-queue-decision rh-web-stack rh-web-stack--tight" ref={root}>
      <div className="rh-web-row" role="group" aria-label={`Decide ${name}`}>
        {ROW_DECISIONS.map((decision) => {
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
      </div>

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
                void run('accept', 'accepted', () => client.acceptCandidate(item.candidate_id))
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
              void run('defer', 'deferred', () => client.deferCandidate(item.candidate_id, note));
            } else {
              void run('reject', 'rejected', () => client.rejectCandidate(item.candidate_id, note));
            }
          }}
        >
          <Textarea
            label={PROMPT_LABELS[open]}
            rows={2}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <p className="rh-text-secondary">{WROTE[open]}</p>
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
