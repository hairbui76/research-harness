import { forwardRef } from 'react';
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
    const blocked = disabledReason !== undefined;

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
                title={meta.description}
                data-decision={decision}
                onClick={() => onDecide(decision)}
              >
                {meta.label}
              </Button>
            );
          })}
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
