import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from '../utils/cx';
import { Button } from '../primitives/Button';
import { Icon } from '../primitives/Icon';
import type { IconName } from '../primitives/Icon';
import { SafetyStatement } from './AsyncState';
import { ASYNC_STATE_META } from './types';
import type { AsyncStateKind, SafetyNote, StateAction } from './types';

/** The states that describe something going wrong, rather than something taking time. */
export type ErrorNoticeKind = Extract<
  AsyncStateKind,
  'partial' | 'stale' | 'blocked' | 'retryable' | 'fatal'
>;

export interface ErrorNoticeProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title' | 'role'> {
  kind: ErrorNoticeKind;
  title: ReactNode;
  description?: ReactNode;
  /** Machine diagnostics - a compiler log line, an exit code - shown on request, in mono. */
  detail?: string;
  detailLabel?: string;
  icon?: IconName;
  actions?: readonly StateAction[];
  safety?: SafetyNote;
  /** Renders a dismiss button. The notice never decides when to disappear. */
  onDismiss?: () => void;
  dismissLabel?: string;
  urgent?: boolean;
}

/**
 * An inline failure notice for a surface that already has content: the composer, a pane
 * header, a compiler strip. It states what happened, whether the draft or source is safe
 * and which actions exist - and it owns none of them. Use `AsyncState` when the failure
 * replaces the whole surface.
 */
export const ErrorNotice = forwardRef<HTMLDivElement, ErrorNoticeProps>(function ErrorNotice(
  {
    kind,
    title,
    description,
    detail,
    detailLabel = 'Technical detail',
    icon,
    actions,
    safety,
    onDismiss,
    dismissLabel = 'Dismiss',
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
      data-kind={kind}
      data-tone={meta.tone}
      className={cx('rh-error-notice', className)}
      {...rest}
    >
      <span className="rh-error-notice__icon">
        <Icon name={icon ?? meta.icon} size={16} />
      </span>
      <div className="rh-error-notice__body">
        <p className="rh-error-notice__title">
          <span className="rh-error-notice__kind">{meta.label}:</span> {title}
        </p>
        {description !== undefined ? (
          <p className="rh-error-notice__description">{description}</p>
        ) : null}
        {safety ? <SafetyStatement safety={safety} /> : null}
        {children}
        {detail !== undefined ? (
          <details className="rh-error-notice__detail">
            <summary>{detailLabel}</summary>
            <pre>{detail}</pre>
          </details>
        ) : null}
        {actions && actions.length > 0 ? (
          <div className="rh-error-notice__actions">
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
      </div>
      {onDismiss ? (
        <button
          type="button"
          className="rh-error-notice__dismiss"
          aria-label={dismissLabel}
          onClick={onDismiss}
        >
          <Icon name="x" size={14} />
        </button>
      ) : null}
    </div>
  );
});
