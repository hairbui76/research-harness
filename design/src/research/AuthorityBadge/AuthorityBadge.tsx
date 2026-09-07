import { forwardRef, useState } from 'react';
import type { ForwardedRef, ReactNode } from 'react';
import { useId } from '../../hooks/useId';
import { Badge, STATUS_META } from '../../primitives/Badge';
import type { BadgeProps } from '../../primitives/Badge';
import { cx } from '../../utils/cx';
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
   * sentence under itself while it has focus or the pointer — the same way
   * `ReviewDecisionBar` explains the six decisions. A native `title` reaches neither the
   * keyboard nor touch, and a tooltip is a convenience layer: where a researcher has to
   * know Qualified from Contested in order to act, the meaning belongs on the page.
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
  describing: Record<string, unknown>,
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

/** The badge with its meaning attached: named by it, and printing it on focus or hover. */
function DescribedAuthorityBadge({
  forwardedRef,
  reason,
  ...badge
}: BadgeOnlyProps & {
  reason?: ReactNode;
  forwardedRef: ForwardedRef<HTMLSpanElement>;
}): ReactNode {
  const descriptionId = useId(undefined, 'rh-authority-description');
  const [shown, setShown] = useState(false);
  const sentence = (
    <>
      {STATUS_META[badge.authority].description}
      {reason !== undefined ? <> {reason}</> : null}
    </>
  );

  return (
    <span className="rh-authority-badge__described">
      {renderBadge(badge, forwardedRef, {
        tabIndex: 0,
        'aria-describedby': descriptionId,
        onFocus: () => setShown(true),
        onBlur: () => setShown(false),
        onMouseEnter: () => setShown(true),
        onMouseLeave: () => setShown(false),
      })}
      {/* The named half, for assistive technology. */}
      <span id={descriptionId} className="rh-visually-hidden">
        {sentence}
      </span>
      {/* The visible half is the same sentence, so it is hidden from assistive technology:
          hearing the meaning twice is worse than hearing it once. It sits under the badge
          rather than over it, so nothing the pointer is already on can move away. */}
      {shown ? (
        <span className="rh-authority-badge__hint" aria-hidden="true">
          {sentence}
        </span>
      ) : null}
    </span>
  );
}
