import { forwardRef } from 'react';
import type { ReactNode } from 'react';
import { Badge, STATUS_META } from '../../primitives/Badge';
import type { BadgeProps } from '../../primitives/Badge';
import { Tooltip } from '../../primitives/Tooltip';
import { cx } from '../../utils/cx';
import type { AuthorityLabel } from '../models';

export interface AuthorityBadgeProps extends Omit<BadgeProps, 'status' | 'tone' | 'children'> {
  /** The authority the host reports. This component never works one out. */
  authority: AuthorityLabel;
  /** Override the visible text. The default is the label from `STATUS_META`. */
  label?: ReactNode;
  /**
   * Attach the standard one-line explanation as a tooltip. The visible label already
   * carries the state, so the tooltip only ever adds detail — but it does add a tab stop,
   * because a tooltip nobody can reach from the keyboard is not worth having. Leave it off
   * inside dense lists and tables.
   */
  describe?: boolean;
  /** Extra sentence appended to the tooltip: why this object holds this authority. */
  reason?: ReactNode;
}

/**
 * The scientific authority of one object.
 *
 * A thin wrapper over the `Badge` primitive, so that every surface — a claim card, a
 * reference chip, a context receipt row, a review queue — spells the six states with the
 * same word, the same glyph and the same tokens. Authority is a property of the object the
 * host passes in; nothing here derives, upgrades or downgrades it.
 */
export const AuthorityBadge = forwardRef<HTMLSpanElement, AuthorityBadgeProps>(
  function AuthorityBadge({ authority, label, describe = false, reason, className, ...rest }, ref) {
    const meta = STATUS_META[authority];
    const badge = (
      <Badge
        ref={ref}
        status={authority}
        className={cx('rh-authority-badge', className)}
        data-authority={authority}
        tabIndex={describe ? 0 : undefined}
        {...rest}
      >
        {label ?? meta.label}
      </Badge>
    );
    if (!describe) return badge;
    return (
      <Tooltip
        content={
          <>
            {meta.description}
            {reason !== undefined ? <> {reason}</> : null}
          </>
        }
      >
        {badge}
      </Tooltip>
    );
  },
);
