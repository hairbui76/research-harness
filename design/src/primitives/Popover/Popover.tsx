import {
  cloneElement,
  createContext,
  forwardRef,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
} from 'react';
import { createPortal } from 'react-dom';
import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
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
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { getTabbable, focusElement } from '../../hooks/focusable';
import { useId } from '../../hooks/useId';
import { usePortal } from '../../hooks/usePortal';
import { cx } from '../../utils/cx';

interface PopoverContextValue {
  open: boolean;
  setOpen: (open: boolean) => void;
  triggerRef: MutableRefObject<HTMLElement | null>;
  contentRef: MutableRefObject<HTMLDivElement | null>;
  contentId: string;
  placement: AnchorPlacement;
  align: AnchorAlignment;
  offset: number;
  trapFocus: boolean;
  container: HTMLElement | null | undefined;
  restoreFocus: MutableRefObject<boolean>;
}

const PopoverContext = createContext<PopoverContextValue | null>(null);

function usePopoverContext(component: string): PopoverContextValue {
  const context = useContext(PopoverContext);
  if (!context) throw new Error(`<${component}> must be rendered inside <Popover>.`);
  return context;
}

export interface PopoverProps {
  children?: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  placement?: AnchorPlacement;
  align?: AnchorAlignment;
  offset?: number;
  /** Contain Tab inside the surface. Use for a popover that owns a small form. */
  trapFocus?: boolean;
  container?: HTMLElement | null;
}

/**
 * An anchored, non-modal surface: outside press and Escape dismiss it, focus moves into it
 * on open and back to the trigger on close (except when the researcher dismissed it by
 * clicking somewhere else, where moving focus would fight them).
 */
function PopoverRoot({
  children,
  open,
  defaultOpen = false,
  onOpenChange,
  placement = 'bottom',
  align = 'center',
  offset = 8,
  trapFocus = false,
  container,
}: PopoverProps): ReactElement {
  const [isOpen, setOpen] = useControllableState<boolean>({
    value: open,
    defaultValue: defaultOpen,
    onChange: onOpenChange,
  });
  const triggerRef = useRef<HTMLElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const restoreFocus = useRef(true);
  const contentId = useId(undefined, 'rh-popover');

  const value = useMemo<PopoverContextValue>(
    () => ({
      open: isOpen,
      setOpen,
      triggerRef,
      contentRef,
      contentId,
      placement,
      align,
      offset,
      trapFocus,
      container,
      restoreFocus,
    }),
    [align, container, contentId, isOpen, offset, placement, setOpen, trapFocus],
  );

  return <PopoverContext.Provider value={value}>{children}</PopoverContext.Provider>;
}

type ElementWithRef = ReactElement & { ref?: Ref<HTMLElement> };

export interface PopoverTriggerProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Use the single child element as the trigger instead of rendering a button. */
  asChild?: boolean;
  children?: ReactNode;
}

export const PopoverTrigger = forwardRef<HTMLButtonElement, PopoverTriggerProps>(
  function PopoverTrigger({ asChild = false, children, onClick, ...rest }, ref) {
    const { open, setOpen, triggerRef, contentId, restoreFocus } = usePopoverContext('Popover.Trigger');

    const setRef = useCallback(
      (node: HTMLElement | null): void => {
        triggerRef.current = node;
        if (typeof ref === 'function') ref(node as HTMLButtonElement | null);
        else if (ref) ref.current = node as HTMLButtonElement | null;
      },
      [ref, triggerRef],
    );

    const toggle = (event: ReactMouseEvent<HTMLElement>): void => {
      if (event.defaultPrevented) return;
      restoreFocus.current = true;
      setOpen(!open);
    };

    const shared = {
      'aria-expanded': open,
      'aria-haspopup': 'dialog' as const,
      'aria-controls': open ? contentId : undefined,
      'data-state': open ? 'open' : 'closed',
    };

    if (asChild) {
      const child = children as ElementWithRef;
      const childProps = (child.props ?? {}) as { onClick?: (event: ReactMouseEvent<HTMLElement>) => void };
      return cloneElement(child, {
        ...shared,
        ref: setRef,
        onClick: (event: ReactMouseEvent<HTMLElement>) => {
          childProps.onClick?.(event);
          toggle(event);
        },
      } as Partial<HTMLAttributes<HTMLElement>> & { ref: Ref<HTMLElement> });
    }

    return (
      <button
        type="button"
        ref={setRef as Ref<HTMLButtonElement>}
        {...shared}
        onClick={(event) => {
          onClick?.(event);
          toggle(event);
        }}
        {...rest}
      >
        {children}
      </button>
    );
  },
);

export interface PopoverContentProps extends HTMLAttributes<HTMLDivElement> {
  /** Accessible name. A popover is a `dialog`, so it needs one. */
  'aria-label'?: string;
  children?: ReactNode;
}

export const PopoverContent = forwardRef<HTMLDivElement, PopoverContentProps>(
  function PopoverContent({ className, children, ...rest }, ref) {
    const {
      open,
      setOpen,
      triggerRef,
      contentRef,
      contentId,
      placement,
      align,
      offset,
      trapFocus,
      container,
      restoreFocus,
    } = usePopoverContext('Popover.Content');

    const host = usePortal({ container, enabled: open, name: 'popover' });
    const { style, placement: resolvedPlacement } = useAnchorPosition({
      anchorRef: triggerRef,
      floatingRef: contentRef,
      placement,
      align,
      offset,
      enabled: open && host !== null,
    });

    useDismiss({
      enabled: open,
      onDismiss: (reason) => {
        restoreFocus.current = reason === 'escape';
        setOpen(false);
      },
      refs: [triggerRef, contentRef],
    });

    useFocusTrap({
      active: open && trapFocus && host !== null,
      containerRef: contentRef,
      restoreFocus: false,
    });

    // Focus in on open; focus back to the trigger on close unless the user pressed elsewhere.
    const didFocusIn = useRef(false);
    useEffect(() => {
      if (open && host && !didFocusIn.current) {
        const content = contentRef.current;
        if (content) {
          const target = getTabbable(content)[0] ?? content;
          if (target === content && !content.hasAttribute('tabindex')) {
            content.setAttribute('tabindex', '-1');
          }
          focusElement(target);
          didFocusIn.current = true;
        }
        return;
      }
      if (!open && didFocusIn.current) {
        didFocusIn.current = false;
        if (restoreFocus.current) focusElement(triggerRef.current);
      }
    }, [contentRef, host, open, restoreFocus, triggerRef]);

    if (!open || !host) return null;

    return createPortal(
      <div
        ref={(node) => {
          contentRef.current = node;
          if (typeof ref === 'function') ref(node);
          else if (ref) ref.current = node;
        }}
        id={contentId}
        role="dialog"
        data-placement={resolvedPlacement}
        className={cx('rh-popover', className)}
        style={style}
        {...rest}
      >
        {children}
      </div>,
      host,
    );
  },
);

export const Popover = Object.assign(PopoverRoot, {
  Trigger: PopoverTrigger,
  Content: PopoverContent,
});
