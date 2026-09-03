import { forwardRef, useCallback } from 'react';
import type { ChangeEvent, InputHTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { joinIds, useFieldIds } from '../../utils/ids';
import { useControllable } from '../../utils/useControllable';
import { Icon } from '../Icon';
import { FieldShell } from '../field';

export interface CheckboxProps
  extends Omit<
    InputHTMLAttributes<HTMLInputElement>,
    'type' | 'checked' | 'defaultChecked' | 'size'
  > {
  label?: ReactNode;
  description?: ReactNode;
  error?: ReactNode;
  invalid?: boolean;
  /** Controlled state. Leave undefined and pass `defaultChecked` for the uncontrolled case. */
  checked?: boolean;
  defaultChecked?: boolean;
  /** Neither checked nor unchecked — a partially selected group. */
  indeterminate?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  fieldClassName?: string;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  {
    label,
    description,
    error,
    invalid = false,
    checked,
    defaultChecked = false,
    indeterminate = false,
    onCheckedChange,
    onChange,
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
  const { controlId, descriptionId, errorId } = useFieldIds(id, 'rh-checkbox');
  const [isChecked, setChecked] = useControllable<boolean>({
    value: checked,
    defaultValue: defaultChecked,
    onChange: onCheckedChange,
  });
  const isInvalid = invalid || error !== undefined;

  // The indeterminate state lives only as a DOM property, so it is set through the ref.
  const setNode = useCallback(
    (node: HTMLInputElement | null) => {
      if (node) node.indeterminate = indeterminate;
      if (typeof ref === 'function') ref(node);
      else if (ref) ref.current = node;
    },
    [indeterminate, ref],
  );

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    setChecked(event.target.checked);
    onChange?.(event);
  };

  return (
    <FieldShell
      controlId={controlId}
      label={label}
      description={description}
      descriptionId={descriptionId}
      error={error}
      errorId={errorId}
      required={required}
      disabled={disabled}
      layout="inline"
      className={fieldClassName}
    >
      <span className={cx('rh-checkbox', disabled && 'is-disabled')}>
        <input
          ref={setNode}
          id={controlId}
          type="checkbox"
          className={cx('rh-checkbox__input', className)}
          checked={isChecked}
          onChange={handleChange}
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
        <span className="rh-checkbox__box" aria-hidden="true">
          <Icon name={indeterminate ? 'minus' : 'check'} size={14} />
        </span>
      </span>
    </FieldShell>
  );
});
