import { forwardRef } from 'react';
import type { HTMLAttributes, ReactElement, ReactNode } from 'react';
import { cx } from '../utils/cx';
import { Button } from '../primitives/Button';
import { Icon } from '../primitives/Icon';
import type { IconName } from '../primitives/Icon';
import { Progress } from '../primitives/Progress';
import { ASYNC_STATE_META, SAFETY_SENTENCE } from './types';
import type { AsyncStateKind, SafetyNote, StateAction } from './types';

export interface AsyncStateProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title' | 'role'> {
  kind: AsyncStateKind;
  /** One line naming what happened, in the researcher's terms. */
  title: ReactNode;
  /** What it means and what happens next. */
  description?: ReactNode;
  /** Override the kind's icon. The kind label is always rendered as text as well. */
  icon?: IconName;
  /** Recovery actions. This component never performs them. */
  actions?: readonly StateAction[];
  /** Whether the researcher's draft and source survived. */
  safety?: SafetyNote;
  /** Content that arrived successfully before this state, kept on screen. */
  retained?: ReactNode;
  retainedLabel?: string;
  /** Progress for `loading`; omit `value` for an indeterminate bar. */
  progress?: { value?: number; max?: number; label?: string };
  /** A single row, for inline use inside a list or a pane header. */
  compact?: boolean;
  /** Force the live-region politeness rather than taking it from the kind. */
  urgent?: boolean;
}

export function SafetyStatement({ safety }: { safety: SafetyNote }): ReactElement | null {
  const sentences: string[] = [];
  if (safety.draft) sentences.push(SAFETY_SENTENCE.draft[safety.draft]);
  if (safety.source) sentences.push(SAFETY_SENTENCE.source[safety.source]);
  if (sentences.length === 0 && safety.note === undefined) return null;
  return (
    <p className="rh-state__safety">
      <Icon name="lock" size={14} />
      <span>
        {sentences.join(' ')}
        {safety.note !== undefined ? <> {safety.note}</> : null}
      </span>
    </p>
  );
}

/**
 * The one presentation for loading, empty, partial, stale, blocked, retryable and fatal
 * states. It owns no recovery logic: the caller passes a typed state, optional actions and
 * whatever content already succeeded, and this renders them consistently - always with a
 * written kind label beside the icon, never with colour as the only signal.
 */
export const AsyncState = forwardRef<HTMLDivElement, AsyncStateProps>(function AsyncState(
  {
    kind,
    title,
    description,
    icon,
    actions,
    safety,
    retained,
    retainedLabel = 'Showing the last result that succeeded',
    progress,
    compact = false,
    urgent,
    className,
    children,
    ...rest
  },
  ref,
) {
  const meta = ASYNC_STATE_META[kind];
  const assertive = urgent ?? meta.urgent;

  return (
    <div
      ref={ref}
      role={assertive ? 'alert' : 'status'}
      aria-busy={kind === 'loading' ? true : undefined}
      data-kind={kind}
      data-tone={meta.tone}
      data-compact={compact ? '' : undefined}
      className={cx('rh-state', className)}
      {...rest}
    >
      <span className="rh-state__icon">
        <Icon name={icon ?? meta.icon} size={compact ? 16 : 20} />
      </span>
      <div className="rh-state__body">
        <p className="rh-state__kind">{meta.label}</p>
        <p className="rh-state__title">{title}</p>
        {description !== undefined ? <p className="rh-state__description">{description}</p> : null}
        {progress ? (
          <Progress
            className="rh-state__progress"
            value={progress.value ?? 0}
            max={progress.max ?? 100}
            indeterminate={progress.value === undefined}
            label={progress.label}
          />
        ) : null}
        {safety ? <SafetyStatement safety={safety} /> : null}
        {children}
        {actions && actions.length > 0 ? (
          <div className="rh-state__actions">
            {actions.map((action) => (
              <Button
                key={action.label}
                size="sm"
                variant={action.variant ?? 'secondary'}
                disabled={action.disabled}
                iconStart={action.iconStart}
                onClick={action.onClick}
              >
                {action.label}
              </Button>
            ))}
          </div>
        ) : null}
        {retained !== undefined ? (
          <div className="rh-state__retained">
            <p className="rh-state__retained-label">{retainedLabel}</p>
            {retained}
          </div>
        ) : null}
      </div>
    </div>
  );
});
