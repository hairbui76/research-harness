import type { ReactNode } from 'react';
import { cx } from '../utils/cx';
import { Icon } from './Icon';

/**
 * Shared scaffolding for every labelled control: the label, the required marker, the
 * description, and the error line. It exists so the `aria-describedby` wiring is written
 * once — every form primitive in the package renders through it.
 *
 * Internal to the package; it is not part of the public export surface.
 */
export interface FieldShellProps {
  /** id of the control the label points at */
  controlId: string;
  label?: ReactNode;
  /** Hide the label visually but keep it for assistive technology. */
  hideLabel?: boolean;
  description?: ReactNode;
  descriptionId: string;
  /** Error text. Its presence is what puts the field in the invalid state. */
  error?: ReactNode;
  errorId: string;
  required?: boolean;
  disabled?: boolean;
  /** `inline` puts the control before the label, for checkbox/radio/switch. */
  layout?: 'stacked' | 'inline';
  className?: string;
  children: ReactNode;
}

export function FieldShell({
  controlId,
  label,
  hideLabel = false,
  description,
  descriptionId,
  error,
  errorId,
  required = false,
  disabled = false,
  layout = 'stacked',
  className,
  children,
}: FieldShellProps) {
  const labelNode =
    label === undefined ? null : (
      <label
        className={cx('rh-field__label', hideLabel && 'rh-visually-hidden')}
        htmlFor={controlId}
      >
        {label}
        {required ? (
          <span className="rh-field__required" aria-hidden="true">
            *
          </span>
        ) : null}
      </label>
    );

  return (
    <div
      className={cx('rh-field', `rh-field--${layout}`, disabled && 'is-disabled', className)}
      data-invalid={error ? true : undefined}
    >
      {layout === 'inline' ? (
        <div className="rh-field__row">
          {children}
          {labelNode}
        </div>
      ) : (
        <>
          {labelNode}
          {children}
        </>
      )}
      {description === undefined ? null : (
        <p className="rh-field__description" id={descriptionId}>
          {description}
        </p>
      )}
      {error === undefined ? null : (
        <p className="rh-field__error" id={errorId}>
          <Icon name="alert-circle" size={14} />
          <span>{error}</span>
        </p>
      )}
    </div>
  );
}
