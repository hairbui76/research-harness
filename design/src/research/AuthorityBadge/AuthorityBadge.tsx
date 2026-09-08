import { forwardRef } from 'react';
import type { ForwardedRef, ReactNode } from 'react';
import { Badge, STATUS_META } from '../../primitives/Badge';
import type { BadgeProps } from '../../primitives/Badge';
import { cx } from '../../utils/cx';
import { useDescribedTerm } from '../DescribedTerm';
import type { DescribedTermWordProps } from '../DescribedTerm';
import type { AuthorityLabel } from '../models';

export interface AuthorityBadgeProps extends Omit<BadgeProps, 'status' | 'tone' | 'children'> {
  /** The authority the host reports. This component never works one out. */
  authority: AuthorityLabel;
  /** Override the visible text. The default is the label from `STATUS_META`. */
  label?: ReactNode;
  /**
   * Make the standard one-line explanation reachable.
   *
   * The badge takes a tab stop, is `aria-describedby` its own sentence, and prints that
   * sentence under itself while it is being asked about — the same way `ReviewDecisionBar`
   * explains the six decisions. A native `title` reaches neither the keyboard nor touch,
   * and a tooltip is a convenience layer: where a researcher has to know Qualified from
   * Contested in order to act, the meaning belongs on the page.
   *
   * Focus, a pointer that rests on the badge and a long press all open it — see
   * `useDescribedTerm`, which owns all three. A badge sits in a row beside links a
   * researcher is aiming at, so the pointer has to stay rather than pass, and a surface
   * whose row cannot grow gives the sentence a line of its own beneath the row. The dotted
   * underline and the `help` cursor are what tell a pointer there is anything to ask.
   *
   * Turn it on where the status is the subject — a review screen's header, a queue row's
   * own state, a claims table's status column — and leave it off where the status is
   * incidental, such as a reference chip inside a sentence.
   */
  describe?: boolean;
  /** Extra sentence after the description: why this object holds this authority. */
  reason?: ReactNode;
}

/**
 * The scientific authority of one object.
 *
 * A thin wrapper over the `Badge` primitive, so that every surface — a claim card, a
 * reference chip, a context receipt row, a review queue — spells the six states with the
 * same word, the same glyph and the same tokens. Authority is a property of the object the
 * host passes in; nothing here derives, upgrades or downgrades it.
 *
 * The describing badge is a separate component rather than a branch inside one, so that a
 * plain badge — by far the common case — allocates no generated id at all.
 */
export const AuthorityBadge = forwardRef<HTMLSpanElement, AuthorityBadgeProps>(
  function AuthorityBadge(props, ref) {
    const { describe = false, reason, ...rest } = props;
    if (!describe) return renderBadge(rest, ref, {});
    return (
      <DescribedAuthorityBadge
        {...rest}
        {...(reason === undefined ? {} : { reason })}
        forwardedRef={ref}
      />
    );
  },
);

/** Everything the `Badge` primitive itself takes, once the two describing props are off. */
type BadgeOnlyProps = Omit<AuthorityBadgeProps, 'describe' | 'reason'>;

/** The badge itself. A plain function, so the two callers below share one element. */
function renderBadge(
  { authority, label, className, ...rest }: BadgeOnlyProps,
  ref: ForwardedRef<HTMLSpanElement>,
  describing: DescribedTermWordProps,
): ReactNode {
  return (
    <Badge
      ref={ref}
      status={authority}
      className={cx('rh-authority-badge', className)}
      data-authority={authority}
      {...rest}
      {...describing}
    >
      {label ?? STATUS_META[authority].label}
    </Badge>
  );
}

/**
 * The badge with its meaning attached: named by it, and printing it when asked.
 *
 * The tab stop, the three gestures that open the sentence and the named half all come from
 * `useDescribedTerm`, which is the one place in the package that decides what "ask a word
 * what it means" is. Only the visible half is drawn here, under this component's own
 * class, because a surface that has to place the sentence somewhere else selects it by
 * that name.
 */
function DescribedAuthorityBadge({
  forwardedRef,
  reason,
  ...badge
}: BadgeOnlyProps & {
  reason?: ReactNode;
  forwardedRef: ForwardedRef<HTMLSpanElement>;
}): ReactNode {
  const sentence = (
    <>
      {STATUS_META[badge.authority].description}
      {reason !== undefined ? <> {reason}</> : null}
    </>
  );
  const term = useDescribedTerm(sentence);

  return (
    <span className="rh-authority-badge__described">
      {renderBadge(badge, forwardedRef, term.word)}
      {term.named}
      {/* The visible half is the same sentence, so it is hidden from assistive technology:
          hearing the meaning twice is worse than hearing it once. It sits under the badge
          and in flow, where a scrolling table cannot clip it the way it would clip an
          overlay. */}
      {term.shown ? (
        <span className="rh-authority-badge__hint" aria-hidden="true">
          {sentence}
        </span>
      ) : null}
    </span>
  );
}
