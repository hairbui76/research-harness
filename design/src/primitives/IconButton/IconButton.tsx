import { forwardRef } from 'react';
import type { ButtonHTMLAttributes } from 'react';
import { cx } from '../../utils/cx';
import { Icon } from '../Icon';
import type { IconName } from '../Icon';
import type { ButtonVariant } from '../Button';

export type IconButtonSize = 'sm' | 'md';

export interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
  /** Registry name of the glyph. */
  icon: IconName;
  /**
   * The accessible name — required, because the glyph is the only thing on screen. It is
   * also the natural tooltip text; the tooltip is DS1b's `Tooltip`, not this component.
   */
  label: string;
  variant?: ButtonVariant;
  size?: IconButtonSize;
  loading?: boolean;
  type?: 'button' | 'submit' | 'reset';
}

/** A square button whose only content is one icon. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  {
    icon,
    label,
    variant = 'ghost',
    size = 'md',
    loading = false,
    type = 'button',
    disabled = false,
    className,
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cx(
        'rh-icon-button',
        `rh-icon-button--${size}`,
        `rh-button--${variant}`,
        loading && 'is-loading',
        className,
      )}
      aria-label={label}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      data-variant={variant}
      {...rest}
    >
      <Icon name={loading ? 'loader' : icon} size={size === 'sm' ? 14 : 16} />
    </button>
  );
});
