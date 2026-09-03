import { createContext, forwardRef, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { ButtonHTMLAttributes, HTMLAttributes, MouseEvent as ReactMouseEvent, ReactNode, RefObject } from 'react';
import { Icon } from '../Icon';
import { useControllableState } from '../../hooks/useControllableState';
import { useDismiss } from '../../hooks/useDismiss';
import { useFocusTrap } from '../../hooks/useFocusTrap';
import { useId } from '../../hooks/useId';
import { usePortal } from '../../hooks/usePortal';
import { cx } from '../../utils/cx';

export type DialogSize = 'sm' | 'md' | 'lg';
export type DialogRole = 'dialog' | 'alertdialog';

interface DialogContextValue {
  titleId: string;
  descriptionId: string;
  registerTitle: (present: boolean) => void;
  registerDescription: (present: boolean) => void;
  close: () => void;
  dismissible: boolean;
}

const DialogContext = createContext<DialogContextValue | null>(null);

function useDialogContext(component: string): DialogContextValue {
  const context = useContext(DialogContext);
  if (!context) throw new Error(`<${component}> must be rendered inside <Dialog>.`);
  return context;
}

/** Body scroll lock shared by every open dialog, so nesting cannot leave it stuck. */
let scrollLockCount = 0;
let previousBodyOverflow = '';

function lockBodyScroll(): () => void {
  if (typeof document === 'undefined') return () => undefined;
  if (scrollLockCount === 0) {
    previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
  }
  scrollLockCount += 1;
  return () => {
    scrollLockCount = Math.max(0, scrollLockCount - 1);
    if (scrollLockCount === 0) document.body.style.overflow = previousBodyOverflow;
  };
}

export interface DialogProps extends Omit<HTMLAttributes<HTMLDivElement>, 'role' | 'title'> {
  /** Controlled open state. */
  open?: boolean;
  /** Initial open state when uncontrolled. */
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /**
   * `alertdialog` for a destructive or blocking decision the researcher must answer
   * (discarding a draft, overwriting an accepted claim); `dialog` otherwise.
   */
  role?: DialogRole;
  size?: DialogSize;
  /** Escape and the header close button close the dialog. Default true. */
  dismissible?: boolean;
  /** Clicking the scrim closes. Defaults to `dismissible`; forced false for `alertdialog`. */
  closeOnScrimClick?: boolean;
  /** Focused when the dialog opens. Defaults to the first tabbable element. */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** Focused when the dialog closes. Defaults to the element that had focus before. */
  finalFocusRef?: RefObject<HTMLElement | null>;
  /** Portal target. Defaults to `document.body`. */
  container?: HTMLElement | null;
  children?: ReactNode;
}

const DialogRoot = forwardRef<HTMLDivElement, DialogProps>(function Dialog(
  {
    open,
    defaultOpen = false,
    onOpenChange,
    role = 'dialog',
    size = 'md',
    dismissible = true,
    closeOnScrimClick,
    initialFocusRef,
    finalFocusRef,
    container,
    className,
    children,
    id,
    ...rest
  },
  ref,
) {
  const [isOpen, setOpen] = useControllableState<boolean>({
    value: open,
    defaultValue: defaultOpen,
    onChange: onOpenChange,
  });

  const baseId = useId(id, 'rh-dialog');
  const titleId = `${baseId}-title`;
  const descriptionId = `${baseId}-description`;
  const [hasTitle, setHasTitle] = useState(false);
  const [hasDescription, setHasDescription] = useState(false);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const host = usePortal({ container, enabled: isOpen, name: 'dialog' });

  const close = useCallback(() => setOpen(false), [setOpen]);

  useFocusTrap({
    active: isOpen && host !== null,
    containerRef: panelRef,
    initialFocusRef,
    finalFocusRef,
  });

  useDismiss({
    enabled: isOpen && dismissible,
    onDismiss: (reason) => {
      if (reason === 'escape') close();
    },
    refs: [panelRef],
    outsidePress: false,
  });

  useEffect(() => {
    if (!isOpen) return;
    return lockBodyScroll();
  }, [isOpen]);

  const context = useMemo<DialogContextValue>(
    () => ({
      titleId,
      descriptionId,
      registerTitle: setHasTitle,
      registerDescription: setHasDescription,
      close,
      dismissible,
    }),
    [close, descriptionId, dismissible, titleId],
  );

  if (!isOpen || !host) return null;

  const scrimCloses = (closeOnScrimClick ?? dismissible) && role !== 'alertdialog';

  const onScrimMouseDown = (event: ReactMouseEvent<HTMLDivElement>): void => {
    if (!scrimCloses) return;
    if (event.target !== event.currentTarget) return;
    close();
  };

  return createPortal(
    <DialogContext.Provider value={context}>
      <div className="rh-dialog__scrim" data-rh-dialog-scrim="" onMouseDown={onScrimMouseDown}>
        <div
          ref={(node) => {
            panelRef.current = node;
            if (typeof ref === 'function') ref(node);
            else if (ref) ref.current = node;
          }}
          role={role}
          aria-modal="true"
          aria-labelledby={hasTitle ? titleId : undefined}
          aria-describedby={hasDescription ? descriptionId : undefined}
          data-size={size}
          className={cx('rh-dialog', className)}
          {...rest}
        >
          {children}
        </div>
      </div>
    </DialogContext.Provider>,
    host,
  );
});

export interface DialogHeaderProps extends HTMLAttributes<HTMLElement> {
  /** Rendered beside the title - status badges, a secondary action. */
  actions?: ReactNode;
  /** Show the close button. Defaults to the dialog's `dismissible`. */
  showClose?: boolean;
  /** Accessible name of the close button. */
  closeLabel?: string;
  children?: ReactNode;
}

export const DialogHeader = forwardRef<HTMLElement, DialogHeaderProps>(function DialogHeader(
  { actions, showClose, closeLabel = 'Close', className, children, ...rest },
  ref,
) {
  const { titleId, registerTitle, close, dismissible } = useDialogContext('Dialog.Header');

  useEffect(() => {
    registerTitle(true);
    return () => registerTitle(false);
  }, [registerTitle]);

  const withClose = showClose ?? dismissible;

  return (
    <header ref={ref} className={cx('rh-dialog__header', className)} {...rest}>
      <h2 id={titleId} className="rh-dialog__title">
        {children}
      </h2>
      <div className="rh-dialog__header-actions">
        {actions}
        {withClose ? (
          <button type="button" className="rh-dialog__close" aria-label={closeLabel} onClick={close}>
            <Icon name="x" size={16} />
          </button>
        ) : null}
      </div>
    </header>
  );
});

export type DialogBodyProps = HTMLAttributes<HTMLDivElement>;

export const DialogBody = forwardRef<HTMLDivElement, DialogBodyProps>(function DialogBody(
  { className, children, ...rest },
  ref,
) {
  const { descriptionId, registerDescription } = useDialogContext('Dialog.Body');

  useEffect(() => {
    registerDescription(true);
    return () => registerDescription(false);
  }, [registerDescription]);

  return (
    <div
      ref={ref}
      id={descriptionId}
      className={cx('rh-dialog__body', className)}
      {...rest}
    >
      {children}
    </div>
  );
});

export type DialogFooterProps = HTMLAttributes<HTMLElement>;

export const DialogFooter = forwardRef<HTMLElement, DialogFooterProps>(function DialogFooter(
  { className, children, ...rest },
  ref,
) {
  return (
    <footer ref={ref} className={cx('rh-dialog__footer', className)} {...rest}>
      {children}
    </footer>
  );
});

export type DialogCloseProps = ButtonHTMLAttributes<HTMLButtonElement>;

/** A button that closes the dialog; the cancel half of a decision footer. */
export const DialogClose = forwardRef<HTMLButtonElement, DialogCloseProps>(function DialogClose(
  { onClick, children, ...rest },
  ref,
) {
  const { close } = useDialogContext('Dialog.Close');
  return (
    <button
      ref={ref}
      type="button"
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) close();
      }}
      {...rest}
    >
      {children}
    </button>
  );
});

export const Dialog = Object.assign(DialogRoot, {
  Header: DialogHeader,
  Body: DialogBody,
  Footer: DialogFooter,
  Close: DialogClose,
});
