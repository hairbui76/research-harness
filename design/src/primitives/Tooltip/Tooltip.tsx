import { cloneElement, useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type {
  FocusEvent as ReactFocusEvent,
  MouseEvent as ReactMouseEvent,
  MutableRefObject,
  ReactElement,
  ReactNode,
  Ref,
} from 'react';
import { useAnchorPosition } from '../../hooks/useAnchorPosition';
import type { AnchorAlignment, AnchorPlacement } from '../../hooks/useAnchorPosition';
import { useControllableState } from '../../hooks/useControllableState';
import { useDismiss } from '../../hooks/useDismiss';
import { useId } from '../../hooks/useId';
import { usePortal } from '../../hooks/usePortal';
import { cx } from '../../utils/cx';

declare const process: { env?: { NODE_ENV?: string } } | undefined;

function isDevelopment(): boolean {
  return typeof process === 'undefined' || process?.env?.NODE_ENV !== 'production';
}

type ElementWithRef = ReactElement & { ref?: Ref<HTMLElement> };

interface TriggerProps {
  onMouseEnter?: (event: ReactMouseEvent<HTMLElement>) => void;
  onMouseLeave?: (event: ReactMouseEvent<HTMLElement>) => void;
  onFocus?: (event: ReactFocusEvent<HTMLElement>) => void;
  onBlur?: (event: ReactFocusEvent<HTMLElement>) => void;
  onMouseDown?: (event: ReactMouseEvent<HTMLElement>) => void;
  'aria-describedby'?: string;
  disabled?: boolean;
}

export interface TooltipProps {
  /**
   * Supplementary text. A tooltip is never the only place information lives: anything a
   * researcher needs in order to make a decision - authority state, a source anchor, why
   * an action is unavailable - must also be present in the visible UI or in the element's
   * accessible name. Tooltips are hidden from touch users and from anyone reading with
   * a magnifier, so treat them as a convenience layer only.
   */
  content: ReactNode;
  /**
   * A single element that can receive focus. A disabled control fires no pointer or focus
   * events, so wrap it in a focusable element (`<span tabIndex={0}>`) and put the tooltip
   * on the wrapper; in development a disabled child logs a warning.
   */
  children: ReactElement;
  placement?: AnchorPlacement;
  align?: AnchorAlignment;
  offset?: number;
  /** Pointer hover delay in ms. Keyboard focus always opens immediately. Default 400. */
  openDelay?: number;
  /** Grace period before closing, so the pointer can travel into the tooltip. Default 120. */
  closeDelay?: number;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Renders the trigger untouched, with no tooltip behaviour. */
  disabled?: boolean;
  id?: string;
  container?: HTMLElement | null;
  className?: string;
}

/**
 * A hover/focus description that follows WCAG 2.2 "Content on Hover or Focus": Escape
 * dismisses it, the pointer can move onto it without dismissing it, and it stays visible
 * until focus or hover leaves.
 */
export function Tooltip({
  content,
  children,
  placement = 'top',
  align = 'center',
  offset = 8,
  openDelay = 400,
  closeDelay = 120,
  open,
  defaultOpen = false,
  onOpenChange,
  disabled = false,
  id,
  container,
  className,
}: TooltipProps): ReactElement {
  const [isOpen, setOpen] = useControllableState<boolean>({
    value: open,
    defaultValue: defaultOpen,
    onChange: onOpenChange,
  });
  const tooltipId = useId(id, 'rh-tooltip');
  const triggerRef = useRef<HTMLElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const timer = useRef<number | null>(null);
  const [warned, setWarned] = useState(false);

  const host = usePortal({ container, enabled: isOpen && !disabled, name: 'tooltip' });
  const { style, placement: resolvedPlacement } = useAnchorPosition({
    anchorRef: triggerRef,
    floatingRef: tooltipRef,
    placement,
    align,
    offset,
    enabled: isOpen && host !== null,
  });

  const clearTimer = useCallback((): void => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  const schedule = useCallback(
    (next: boolean, delay: number): void => {
      clearTimer();
      if (delay <= 0) {
        setOpen(next);
        return;
      }
      timer.current = window.setTimeout(() => {
        timer.current = null;
        setOpen(next);
      }, delay);
    },
    [clearTimer, setOpen],
  );

  useEffect(() => clearTimer, [clearTimer]);

  useDismiss({
    enabled: isOpen && !disabled,
    onDismiss: (reason) => {
      if (reason === 'escape') {
        clearTimer();
        setOpen(false);
      }
    },
    refs: [triggerRef, tooltipRef],
    outsidePress: false,
  });

  const child = children as ElementWithRef;
  const childProps = (child.props ?? {}) as TriggerProps;

  useEffect(() => {
    if (disabled || warned || !isDevelopment()) return;
    const node = triggerRef.current as (HTMLElement & { disabled?: boolean }) | null;
    if (node?.disabled === true || childProps.disabled === true) {
      setWarned(true);
      console.warn(
        '[rh] Tooltip: a disabled element does not emit hover or focus events. Wrap it in a focusable element and put the Tooltip on the wrapper.',
      );
    }
  }, [childProps.disabled, disabled, warned]);

  const setTriggerRef = useCallback(
    (node: HTMLElement | null): void => {
      triggerRef.current = node;
      const childRef = child.ref;
      if (typeof childRef === 'function') childRef(node);
      else if (childRef && typeof childRef === 'object') {
        (childRef as MutableRefObject<HTMLElement | null>).current = node;
      }
    },
    [child],
  );

  if (disabled) return children;

  const trigger = cloneElement(child, {
    ref: setTriggerRef,
    'aria-describedby': isOpen
      ? [childProps['aria-describedby'], tooltipId].filter(Boolean).join(' ')
      : childProps['aria-describedby'],
    onMouseEnter: (event: ReactMouseEvent<HTMLElement>) => {
      childProps.onMouseEnter?.(event);
      schedule(true, openDelay);
    },
    onMouseLeave: (event: ReactMouseEvent<HTMLElement>) => {
      childProps.onMouseLeave?.(event);
      schedule(false, closeDelay);
    },
    onFocus: (event: ReactFocusEvent<HTMLElement>) => {
      childProps.onFocus?.(event);
      schedule(true, 0);
    },
    onBlur: (event: ReactFocusEvent<HTMLElement>) => {
      childProps.onBlur?.(event);
      schedule(false, 0);
    },
    onMouseDown: (event: ReactMouseEvent<HTMLElement>) => {
      childProps.onMouseDown?.(event);
      clearTimer();
      setOpen(false);
    },
  } as Partial<TriggerProps> & { ref: Ref<HTMLElement> });

  return (
    <>
      {trigger}
      {isOpen && host
        ? createPortal(
            <div
              ref={tooltipRef}
              role="tooltip"
              id={tooltipId}
              data-placement={resolvedPlacement}
              className={cx('rh-tooltip', className)}
              style={style}
              onMouseEnter={() => clearTimer()}
              onMouseLeave={() => schedule(false, closeDelay)}
            >
              {content}
            </div>,
            host,
          )
        : null}
    </>
  );
}
