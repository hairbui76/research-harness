import { forwardRef, useState } from 'react';
import type { HTMLAttributes } from 'react';
import { useId } from '../../hooks/useId';
import { Button } from '../../primitives/Button';
import { Icon } from '../../primitives/Icon';
import { cx } from '../../utils/cx';
import { REVIEW_DECISION_META } from '../models';
import type { ReviewDecision } from '../models';

export interface ReviewDecisionBarProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  /** The decisions this host offers here, in the order they should appear. */
  available: readonly ReviewDecision[];
  /**
   * Why no decision can be recorded — a read-only host, a missing capability, an object
   * someone else is reviewing. Set it and every button is disabled with the reason on
   * screen, not merely greyed out.
   */
  disabledReason?: string;
  /** The decision currently being recorded. Its button spins; the rest wait. */
  busy?: ReviewDecision;
  onDecide: (decision: ReviewDecision) => void;
  /** Accessible name for the group. Defaults to "Review decision". */
  label?: string;
  size?: 'sm' | 'md';
}

/**
 * The decisions a reviewer may record about one candidate.
 *
 * It renders the options the host says are available and reports the one that was chosen.
 * It does not know which decisions are legal for this object, what accepting means, or
 * whether the researcher is allowed to do it — a read-only host passes `disabledReason`
 * and the bar prints it, because a disabled button with no explanation is a dead end.
 *
 * Each decision's meaning is reachable rather than hidden in a `title`: every button is
 * `aria-describedby` its own sentence, and the sentence for whichever decision has focus
 * or the pointer is printed under the bar. A native tooltip reaches neither the keyboard
 * nor touch, and the six meanings are exactly what a reviewer new to Qualified versus
 * Contested needs at the moment of deciding.
 */
export const ReviewDecisionBar = forwardRef<HTMLDivElement, ReviewDecisionBarProps>(
  function ReviewDecisionBar(
    {
      available,
      disabledReason,
      busy,
      onDecide,
      label = 'Review decision',
      size = 'sm',
      className,
      ...rest
    },
    ref,
  ) {
    const reasonId = useId(undefined, 'rh-review-reason');
    const describedBase = useId(undefined, 'rh-review-decision');
    const [active, setActive] = useState<ReviewDecision | null>(null);
    const blocked = disabledReason !== undefined;
    const describedBy = (decision: ReviewDecision) => `${describedBase}-${decision}`;
    const shown = active !== null && available.includes(active) ? active : null;

    return (
      <div
        ref={ref}
        role="group"
        aria-label={label}
        aria-describedby={blocked ? reasonId : undefined}
        className={cx('rh-review-decision-bar', className)}
        data-blocked={blocked || undefined}
        {...rest}
      >
        <div className="rh-review-decision-bar__buttons">
          {available.map((decision) => {
            const meta = REVIEW_DECISION_META[decision];
            return (
              <Button
                key={decision}
                size={size}
                variant={meta.variant}
                iconStart={meta.icon}
                loading={busy === decision}
                loadingLabel={`Recording ${meta.label.toLowerCase()}`}
                disabled={blocked || (busy !== undefined && busy !== decision)}
                aria-describedby={describedBy(decision)}
                data-decision={decision}
                onFocus={() => setActive(decision)}
                onBlur={() => setActive((current) => (current === decision ? null : current))}
                onMouseEnter={() => setActive(decision)}
                onMouseLeave={() => setActive((current) => (current === decision ? null : current))}
                onClick={() => onDecide(decision)}
              >
                {meta.label}
              </Button>
            );
          })}
        </div>

        {/*
          The line under the bar is the visible half of the same sentence the button is
          described by, so it is hidden from assistive technology: hearing the description
          twice — once as the button's own, once as loose text — is worse than hearing it
          once. The space is reserved whether or not anything is focused, so pointing at a
          decision does not move the buttons under the pointer.
        */}
        <p
          className="rh-review-decision-bar__hint"
          data-testid="rh-review-decision-hint"
          aria-hidden="true"
        >
          {shown === null ? null : REVIEW_DECISION_META[shown].description}
        </p>

        {/* One element per decision, named by the button that carries it. */}
        <div className="rh-visually-hidden">
          {available.map((decision) => (
            <span key={decision} id={describedBy(decision)}>
              {REVIEW_DECISION_META[decision].description}
            </span>
          ))}
        </div>

        {blocked ? (
          <p className="rh-review-decision-bar__reason" id={reasonId}>
            <Icon name="lock" size={14} />
            <span>{disabledReason}</span>
          </p>
        ) : null}
      </div>
    );
  },
);
