import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { Icon } from '../Icon';
import type { IconName } from '../Icon';
import { STATUS_META } from './status';
import type { StatusName } from './status';

export type BadgeTone = 'neutral' | 'success' | 'error' | 'warning' | 'info' | 'accent';
export type BadgeSize = 'sm' | 'md';

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  /**
   * Scientific authority. Setting it picks the status palette and, unless overridden,
   * the status glyph and label — so the state is never carried by colour alone.
   */
  status?: StatusName;
  /** Application feedback tone. Ignored when `status` is set. */
  tone?: BadgeTone;
  /** Override the glyph. Pass `null` to draw text only. */
  icon?: IconName | null;
  size?: BadgeSize;
  children?: ReactNode;
}

/**
 * A read-only state marker. Badges are never interactive: use `Tag` for something the
 * researcher can select or remove, and `Button` for something that acts.
 */
export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { status, tone = 'neutral', icon, size = 'md', className, children, ...rest },
  ref,
) {
  const meta = status ? STATUS_META[status] : undefined;
  const glyph: IconName | null = icon === undefined ? (meta?.icon ?? null) : icon;
  const content: ReactNode = children ?? meta?.label ?? null;
  return (
    <span
      ref={ref}
      className={cx(
        'rh-badge',
        `rh-badge--${size}`,
        status ? `rh-badge--status-${status}` : `rh-badge--tone-${tone}`,
        className,
      )}
      data-status={status}
      data-tone={status ? undefined : tone}
      {...rest}
    >
      {glyph ? <Icon name={glyph} size={size === 'sm' ? 14 : 16} /> : null}
      {content === null ? null : <span className="rh-badge__label">{content}</span>}
    </span>
  );
});
