import { forwardRef } from 'react';
import type { ChangeEvent, InputHTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { joinIds, useFieldIds } from '../../utils/ids';
import { useControllable } from '../../utils/useControllable';
import { FieldShell } from '../field';

export interface SwitchProps
  extends Omit<
    InputHTMLAttributes<HTMLInputElement>,
    'type' | 'checked' | 'defaultChecked' | 'role' | 'size'
  > {
  label?: ReactNode;
  description?: ReactNode;
  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  fieldClassName?: string;
}

/**
 * An immediate on/off control for a setting that takes effect at once — a checkbox is
 * still the right control inside a form that is submitted later.
 *
 * It is a checkbox input with `role="switch"`, so label association, Space, and the
 * disabled state are the platform's rather than ours.
 */
export const Switch = forwardRef<HTMLInputElement, SwitchProps>(function Switch(
  {
    label,
    description,
    checked,
    defaultChecked = false,
    onCheckedChange,
    onChange,
    id,
    disabled = false,
    className,
    fieldClassName,
    'aria-describedby': ariaDescribedBy,
    ...rest
  },
  ref,
) {
  const { controlId, descriptionId, errorId } = useFieldIds(id, 'rh-switch');
  const [isChecked, setChecked] = useControllable<boolean>({
    value: checked,
    defaultValue: defaultChecked,
    onChange: onCheckedChange,
  });

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
      errorId={errorId}
      disabled={disabled}
      layout="inline"
      className={fieldClassName}
    >
      <span className={cx('rh-switch', disabled && 'is-disabled')}>
        <input
          ref={ref}
          id={controlId}
          type="checkbox"
          role="switch"
          className={cx('rh-switch__input', className)}
          checked={isChecked}
          onChange={handleChange}
          disabled={disabled}
          aria-describedby={joinIds(ariaDescribedBy, description !== undefined && descriptionId)}
          {...rest}
        />
        <span className="rh-switch__track" aria-hidden="true">
          <span className="rh-switch__thumb" />
        </span>
      </span>
    </FieldShell>
  );
});
