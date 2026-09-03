import { forwardRef } from 'react';
import type { InputHTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { joinIds, useFieldIds } from '../../utils/ids';
import { Icon } from '../Icon';
import type { IconName } from '../Icon';
import { FieldShell } from '../field';

export type InputSize = 'sm' | 'md';

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  label?: ReactNode;
  /** Keep the label for assistive technology but take it off the screen. */
  hideLabel?: boolean;
  /** Help text, linked with `aria-describedby`. */
  description?: ReactNode;
  /** Error text, linked with `aria-describedby`; its presence sets `aria-invalid`. */
  error?: ReactNode;
  /** Mark the field invalid without an error message of its own. */
  invalid?: boolean;
  size?: InputSize;
  iconStart?: IconName;
  /** Class for the outer field wrapper; `className` goes on the input itself. */
  fieldClassName?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    label,
    hideLabel,
    description,
    error,
    invalid = false,
    size = 'md',
    iconStart,
    id,
    required = false,
    disabled = false,
    className,
    fieldClassName,
    'aria-describedby': ariaDescribedBy,
    ...rest
  },
  ref,
) {
  const { controlId, descriptionId, errorId } = useFieldIds(id, 'rh-input');
  const isInvalid = invalid || error !== undefined;
  return (
    <FieldShell
      controlId={controlId}
      label={label}
      hideLabel={hideLabel}
      description={description}
      descriptionId={descriptionId}
      error={error}
      errorId={errorId}
      required={required}
      disabled={disabled}
      className={fieldClassName}
    >
      <div className="rh-input">
        {iconStart ? <Icon className="rh-input__icon" name={iconStart} size={16} /> : null}
        <input
          ref={ref}
          id={controlId}
          className={cx(
            'rh-control',
            size === 'sm' && 'rh-control--sm',
            iconStart && 'rh-control--with-icon',
            className,
          )}
          required={required}
          disabled={disabled}
          aria-invalid={isInvalid || undefined}
          aria-describedby={joinIds(
            ariaDescribedBy,
            description !== undefined && descriptionId,
            error !== undefined && errorId,
          )}
          {...rest}
        />
      </div>
    </FieldShell>
  );
});
