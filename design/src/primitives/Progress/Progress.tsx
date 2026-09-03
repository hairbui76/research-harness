import { forwardRef } from 'react';
import type { HTMLAttributes } from 'react';
import { useId } from '../../hooks/useId';
import { cx } from '../../utils/cx';

export type ProgressSize = 'sm' | 'md';
export type ProgressTone = 'accent' | 'neutral';

export interface ProgressProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  /** Current value between 0 and `max`. Ignored when `indeterminate`. */
  value?: number;
  max?: number;
  /** Work is running but its size is unknown - compiling, rebuilding an index, streaming. */
  indeterminate?: boolean;
  /** Visible label; also the accessible name. Use `aria-label` instead to hide it. */
  label?: string;
  /** Spoken value, e.g. "3 of 12 pages". Defaults to the percentage. */
  valueText?: string;
  /** Render the value beside the label. */
  showValue?: boolean;
  size?: ProgressSize;
  tone?: ProgressTone;
}

function clampToRange(value: number, max: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.min(Math.max(value, 0), max);
}

/**
 * A determinate or indeterminate progress bar. Progress is always available as text as
 * well as a bar - `valueText`, or the percentage - so it is never conveyed by fill alone.
 */
export const Progress = forwardRef<HTMLDivElement, ProgressProps>(function Progress(
  {
    value = 0,
    max = 100,
    indeterminate = false,
    label,
    valueText,
    showValue = false,
    size = 'md',
    tone = 'accent',
    className,
    id,
    ...rest
  },
  ref,
) {
  const baseId = useId(id, 'rh-progress');
  const labelId = `${baseId}-label`;
  const safeMax = max > 0 ? max : 100;
  const current = clampToRange(value, safeMax);
  const percent = Math.round((current / safeMax) * 100);
  const text = valueText ?? (indeterminate ? undefined : `${percent}%`);

  return (
    <div className={cx('rh-progress', className)} data-size={size}>
      {label !== undefined ? (
        <div className="rh-progress__header">
          <span className="rh-progress__label" id={labelId}>
            {label}
          </span>
          {showValue ? (
            <span className="rh-progress__value">{indeterminate ? 'Working…' : text}</span>
          ) : null}
        </div>
      ) : null}
      <div
        ref={ref}
        role="progressbar"
        id={baseId}
        aria-labelledby={label !== undefined ? labelId : undefined}
        aria-valuemin={indeterminate ? undefined : 0}
        aria-valuemax={indeterminate ? undefined : safeMax}
        aria-valuenow={indeterminate ? undefined : current}
        aria-valuetext={indeterminate ? undefined : text}
        data-state={indeterminate ? 'indeterminate' : 'determinate'}
        data-tone={tone}
        className="rh-progress__track"
        {...rest}
      >
        <div
          className="rh-progress__indicator"
          style={indeterminate ? undefined : { inlineSize: `${percent}%` }}
        />
      </div>
    </div>
  );
});
