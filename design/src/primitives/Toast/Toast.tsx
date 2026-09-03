import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ReactElement, ReactNode } from 'react';
import { Icon } from '../Icon';
import type { IconName } from '../Icon';
import { usePortal } from '../../hooks/usePortal';

export type ToastTone = 'info' | 'success' | 'warning' | 'error';

export type ToastPlacement =
  | 'top-left'
  | 'top-center'
  | 'top-right'
  | 'bottom-left'
  | 'bottom-center'
  | 'bottom-right';

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  title: ReactNode;
  description?: ReactNode;
  /** `error` is announced assertively; every other tone is announced politely. */
  tone?: ToastTone;
  /** ms before auto-dismiss, or `null` to stay until dismissed. Defaults to the provider. */
  duration?: number | null;
  /** A single recovery action. The toast never performs the action itself. */
  action?: ToastAction;
  /** Show the dismiss button. Default true. */
  dismissible?: boolean;
  /** Supply an id to replace an existing toast instead of stacking another one. */
  id?: string;
}

export interface ToastRecord extends ToastOptions {
  id: string;
}

export interface ToastApi {
  /** Queues a toast and returns its id. */
  toast: (options: ToastOptions) => string;
  dismiss: (id: string) => void;
  dismissAll: () => void;
  /** Currently visible toasts, oldest first. */
  toasts: readonly ToastRecord[];
}

const ToastContext = createContext<ToastApi | null>(null);

/** The imperative handle: `const { toast } = useToast()`. */
export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast() must be called inside <ToastProvider>.');
  return context;
}

const TONE_ICON: Record<ToastTone, IconName> = {
  info: 'info',
  success: 'circle-check',
  warning: 'alert-triangle',
  error: 'alert-circle',
};

const TONE_LABEL: Record<ToastTone, string> = {
  info: 'Information',
  success: 'Success',
  warning: 'Warning',
  error: 'Error',
};

export interface ToastProviderProps {
  children?: ReactNode;
  /** Maximum simultaneously visible toasts; the rest wait in a queue. Default 3. */
  limit?: number;
  /** Default auto-dismiss in ms, or `null` for sticky toasts. Default 6000. */
  duration?: number | null;
  placement?: ToastPlacement;
  /** Accessible name of the notification region. */
  label?: string;
  container?: HTMLElement | null;
}

export function ToastProvider({
  children,
  limit = 3,
  duration = 6000,
  placement = 'bottom-right',
  label = 'Notifications',
  container,
}: ToastProviderProps): ReactElement {
  const [visible, setVisible] = useState<ToastRecord[]>([]);
  const [queued, setQueued] = useState<ToastRecord[]>([]);
  const counter = useRef(0);
  const host = usePortal({ container, name: 'toast' });

  const dismiss = useCallback((id: string) => {
    setVisible((current) => current.filter((entry) => entry.id !== id));
    setQueued((current) => current.filter((entry) => entry.id !== id));
  }, []);

  const dismissAll = useCallback(() => {
    setVisible([]);
    setQueued([]);
  }, []);

  const toast = useCallback(
    (options: ToastOptions): string => {
      counter.current += 1;
      const id = options.id ?? `rh-toast-${counter.current}`;
      const record: ToastRecord = { tone: 'info', duration, dismissible: true, ...options, id };
      setVisible((currentVisible) => {
        const replacing = currentVisible.some((entry) => entry.id === id);
        if (replacing) {
          return currentVisible.map((entry) => (entry.id === id ? record : entry));
        }
        if (currentVisible.length < limit) return [...currentVisible, record];
        setQueued((currentQueued) => [
          ...currentQueued.filter((entry) => entry.id !== id),
          record,
        ]);
        return currentVisible;
      });
      return id;
    },
    [duration, limit],
  );

  // Promote queued toasts as slots free up.
  useEffect(() => {
    if (queued.length === 0 || visible.length >= limit) return;
    const promoted = queued.slice(0, limit - visible.length);
    setQueued((current) => current.slice(promoted.length));
    setVisible((current) => [...current, ...promoted]);
  }, [limit, queued, visible.length]);

  const api = useMemo<ToastApi>(
    () => ({ toast, dismiss, dismissAll, toasts: visible }),
    [dismiss, dismissAll, toast, visible],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      {host
        ? createPortal(
            <div className="rh-toast-viewport" data-placement={placement} role="region" aria-label={label}>
              {visible.map((entry) => (
                <ToastItem key={entry.id} toast={entry} onDismiss={dismiss} />
              ))}
            </div>,
            host,
          )
        : null}
    </ToastContext.Provider>
  );
}

interface ToastItemProps {
  toast: ToastRecord;
  onDismiss: (id: string) => void;
}

function ToastItem({ toast, onDismiss }: ToastItemProps): ReactElement {
  const tone = toast.tone ?? 'info';
  const [paused, setPaused] = useState(false);
  const remaining = useRef<number | null>(toast.duration ?? null);
  const startedAt = useRef(0);

  useEffect(() => {
    const ms = remaining.current;
    if (ms === null || paused) return;
    startedAt.current = Date.now();
    const handle = window.setTimeout(() => onDismiss(toast.id), ms);
    return () => {
      window.clearTimeout(handle);
      if (remaining.current !== null) {
        remaining.current = Math.max(0, remaining.current - (Date.now() - startedAt.current));
      }
    };
  }, [onDismiss, paused, toast.id]);

  return (
    <div
      className="rh-toast"
      data-tone={tone}
      role={tone === 'error' ? 'alert' : 'status'}
      aria-atomic="true"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <span className="rh-toast__icon">
        <Icon name={TONE_ICON[tone]} size={16} />
      </span>
      <div className="rh-toast__content">
        <p className="rh-toast__title">
          <span className="rh-toast__tone-label">{TONE_LABEL[tone]}:</span> {toast.title}
        </p>
        {toast.description ? <p className="rh-toast__description">{toast.description}</p> : null}
      </div>
      {toast.action ? (
        <button
          type="button"
          className="rh-toast__action"
          onClick={() => {
            toast.action?.onClick();
            onDismiss(toast.id);
          }}
        >
          {toast.action.label}
        </button>
      ) : null}
      {toast.dismissible === false ? null : (
        <button
          type="button"
          className="rh-toast__close"
          aria-label="Dismiss notification"
          onClick={() => onDismiss(toast.id)}
        >
          <Icon name="x" size={14} />
        </button>
      )}
    </div>
  );
}
