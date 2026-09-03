import { createContext, forwardRef, useContext } from 'react';
import type { ChangeEvent, InputHTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { joinIds, useAutoId, useFieldIds } from '../../utils/ids';
import { useControllable } from '../../utils/useControllable';
import { FieldShell } from '../field';

interface RadioGroupContextValue {
  name: string;
  value: string | null;
  disabled: boolean;
  select: (value: string) => void;
}

const RadioGroupContext = createContext<RadioGroupContextValue | null>(null);

export interface RadioGroupProps {
  /** Visible group label; rendered as the group's accessible name. */
  label: ReactNode;
  description?: ReactNode;
  error?: ReactNode;
  /** Shared `name` for the inputs. Generated when omitted. */
  name?: string;
  /** Controlled selection; pass `null` for "controlled, nothing chosen yet". */
  value?: string | null;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  disabled?: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * Groups radios so they share a name, a selected value and one accessible label. Native
 * radios inside a labelled group already give arrow-key navigation and roving focus, so
 * there is no keyboard code here.
 */
export function RadioGroup({
  label,
  description,
  error,
  name,
  value,
  defaultValue,
  onValueChange,
  disabled = false,
  className,
  children,
}: RadioGroupProps) {
  const groupId = useAutoId(undefined, 'rh-radiogroup');
  const groupName = name ?? groupId;
  const [selected, setSelected] = useControllable<string | null>({
    value,
    defaultValue: defaultValue ?? null,
    onChange: (next) => {
      if (next !== null) onValueChange?.(next);
    },
  });
  const labelId = `${groupId}-label`;
  const descriptionId = `${groupId}-description`;
  const errorId = `${groupId}-error`;

  return (
    <div
      role="radiogroup"
      aria-labelledby={labelId}
      aria-describedby={joinIds(
        description !== undefined && descriptionId,
        error !== undefined && errorId,
      )}
      aria-invalid={error !== undefined || undefined}
      className={cx('rh-field', 'rh-radio-group', className)}
    >
      <span className="rh-field__label" id={labelId}>
        {label}
      </span>
      <div className="rh-radio-group__items">
        <RadioGroupContext.Provider
          value={{
            name: groupName,
            value: selected,
            disabled,
            select: (next) => setSelected(next),
          }}
        >
          {children}
        </RadioGroupContext.Provider>
      </div>
      {description === undefined ? null : (
        <p className="rh-field__description" id={descriptionId}>
          {description}
        </p>
      )}
      {error === undefined ? null : (
        <p className="rh-field__error" id={errorId}>
          <span>{error}</span>
        </p>
      )}
    </div>
  );
}

export interface RadioProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'checked' | 'size'> {
  label?: ReactNode;
  description?: ReactNode;
  /** Required. A radio without a value cannot report what was chosen. */
  value: string;
  /** Only used outside a `RadioGroup`. */
  checked?: boolean;
  fieldClassName?: string;
}

export const Radio = forwardRef<HTMLInputElement, RadioProps>(function Radio(
  {
    label,
    description,
    value,
    checked,
    onChange,
    name,
    id,
    disabled = false,
    className,
    fieldClassName,
    'aria-describedby': ariaDescribedBy,
    ...rest
  },
  ref,
) {
  const group = useContext(RadioGroupContext);
  const { controlId, descriptionId, errorId } = useFieldIds(id, 'rh-radio');
  const isChecked = group ? group.value === value : checked;
  const isDisabled = disabled || (group?.disabled ?? false);

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (event.target.checked) group?.select(value);
    onChange?.(event);
  };

  return (
    <FieldShell
      controlId={controlId}
      label={label}
      description={description}
      descriptionId={descriptionId}
      errorId={errorId}
      disabled={isDisabled}
      layout="inline"
      className={fieldClassName}
    >
      <span className={cx('rh-radio', isDisabled && 'is-disabled')}>
        <input
          ref={ref}
          id={controlId}
          type="radio"
          className={cx('rh-radio__input', className)}
          name={group?.name ?? name}
          value={value}
          checked={isChecked}
          onChange={handleChange}
          disabled={isDisabled}
          aria-describedby={joinIds(ariaDescribedBy, description !== undefined && descriptionId)}
          {...rest}
        />
        <span className="rh-radio__box" aria-hidden="true">
          <span className="rh-radio__dot" />
        </span>
      </span>
    </FieldShell>
  );
});
