import { forwardRef } from 'react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { Icon } from '../Icon';
import type { IconName } from '../Icon';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'accent';
export type ButtonSize = 'sm' | 'md';

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
  /**
   * `primary` is the page's main action, `secondary` the ordinary one, `ghost` the quiet
   * one in a toolbar, `danger` a destructive one, and `accent` the AI/action accent —
   * reserved for send/run and model activity, never for emphasis.
   */
  variant?: ButtonVariant;
  size?: ButtonSize;
  /**
   * Show a spinner, keep the button's width, mark it `aria-busy` and stop it responding.
   * The label stays in the DOM so the button does not resize mid-request.
   */
  loading?: boolean;
  /** Announced while `loading`, since the label itself is hidden. */
  loadingLabel?: string;
  iconStart?: IconName;
  iconEnd?: IconName;
  fullWidth?: boolean;
  /** Defaults to `button`; set it explicitly for a form submit. */
  type?: 'button' | 'submit' | 'reset';
  children?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    loading = false,
    loadingLabel = 'Loading',
    iconStart,
    iconEnd,
    fullWidth = false,
    type = 'button',
    disabled = false,
    className,
    children,
    ...rest
  },
  ref,
) {
  const iconSize = size === 'sm' ? 14 : 16;
  return (
    <button
      ref={ref}
      type={type}
      className={cx(
        'rh-button',
        `rh-button--${variant}`,
        `rh-button--${size}`,
        fullWidth && 'rh-button--full',
        loading && 'is-loading',
        className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      data-variant={variant}
      {...rest}
    >
      <span className="rh-button__content">
        {iconStart ? <Icon name={iconStart} size={iconSize} /> : null}
        {children === undefined ? null : <span className="rh-button__label">{children}</span>}
        {iconEnd ? <Icon name={iconEnd} size={iconSize} /> : null}
      </span>
      {loading ? (
        <>
          <span className="rh-button__spinner">
            <Icon name="loader" size={iconSize} />
          </span>
          <span className="rh-visually-hidden">{loadingLabel}</span>
        </>
      ) : null}
    </button>
  );
});
