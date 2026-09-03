import { forwardRef } from 'react';
import type { ReactNode, SelectHTMLAttributes } from 'react';
import { cx } from '../../utils/cx';
import { joinIds, useFieldIds } from '../../utils/ids';
import { Icon } from '../Icon';
import { FieldShell } from '../field';

export type SelectSize = 'sm' | 'md';

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  label?: ReactNode;
  hideLabel?: boolean;
  description?: ReactNode;
  error?: ReactNode;
  invalid?: boolean;
  size?: SelectSize;
  fieldClassName?: string;
  /** `<option>` / `<optgroup>` elements. */
  children?: ReactNode;
}

/**
 * A styled native `<select>`. Native is the right answer for a short, flat list: it is
 * keyboard- and screen-reader-correct everywhere and needs no popup layer. Rich selection
 * — search, multi-select, `@` references — is DS1b's `Combobox`.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  {
    label,
    hideLabel,
    description,
    error,
    invalid = false,
    size = 'md',
    id,
    required = false,
    disabled = false,
    className,
    fieldClassName,
    children,
    'aria-describedby': ariaDescribedBy,
    ...rest
  },
  ref,
) {
  const { controlId, descriptionId, errorId } = useFieldIds(id, 'rh-select');
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
      <div className="rh-select">
        <select
          ref={ref}
          id={controlId}
          className={cx('rh-control', 'rh-select__control', size === 'sm' && 'rh-control--sm', className)}
          required={required}
          disabled={disabled}
          aria-invalid={isInvalid || undefined}
          aria-describedby={joinIds(
            ariaDescribedBy,
            description !== undefined && descriptionId,
            error !== undefined && errorId,
          )}
          {...rest}
        >
          {children}
        </select>
        <Icon className="rh-select__chevron" name="chevron-down" size={16} />
      </div>
    </FieldShell>
  );
});
