import { forwardRef } from 'react';
import type { ReactNode, TextareaHTMLAttributes } from 'react';
import { cx } from '../../utils/cx';
import { joinIds, useFieldIds } from '../../utils/ids';
import { FieldShell } from '../field';

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: ReactNode;
  hideLabel?: boolean;
  description?: ReactNode;
  error?: ReactNode;
  invalid?: boolean;
  /** Horizontal resize is never allowed; it breaks pane layouts. */
  resize?: 'none' | 'vertical';
  fieldClassName?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  {
    label,
    hideLabel,
    description,
    error,
    invalid = false,
    resize = 'vertical',
    rows = 3,
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
  const { controlId, descriptionId, errorId } = useFieldIds(id, 'rh-textarea');
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
      <textarea
        ref={ref}
        id={controlId}
        rows={rows}
        className={cx('rh-control', 'rh-textarea', `rh-textarea--resize-${resize}`, className)}
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
    </FieldShell>
  );
});
