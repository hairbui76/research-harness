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
  KeyboardEvent as ReactKeyboardEvent,
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
import { focusElement } from '../../hooks/focusable';
import { useId } from '../../hooks/useId';
import { usePortal } from '../../hooks/usePortal';
import { useRovingTabIndex } from '../../hooks/useRovingTabIndex';
import { cx } from '../../utils/cx';

type InitialFocus = 'first' | 'last';

interface MenuContextValue {
  open: boolean;
  setOpen: (open: boolean) => void;
  triggerRef: MutableRefObject<HTMLElement | null>;
  contentRef: MutableRefObject<HTMLDivElement | null>;
  menuId: string;
  triggerId: string;
  placement: AnchorPlacement;
  align: AnchorAlignment;
  offset: number;
  container: HTMLElement | null | undefined;
  initialFocus: MutableRefObject<InitialFocus>;
  restoreFocus: MutableRefObject<boolean>;
  closeAndRestore: () => void;
}

const MenuContext = createContext<MenuContextValue | null>(null);

function useMenuContext(component: string): MenuContextValue {
  const context = useContext(MenuContext);
  if (!context) throw new Error(`<${component}> must be rendered inside <Menu>.`);
  return context;
}

export interface MenuProps {
  children?: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  placement?: AnchorPlacement;
  align?: AnchorAlignment;
  offset?: number;
  container?: HTMLElement | null;
}

function MenuRoot({
  children,
  open,
  defaultOpen = false,
  onOpenChange,
  placement = 'bottom',
  align = 'start',
  offset = 4,
  container,
}: MenuProps): ReactElement {
  const [isOpen, setOpen] = useControllableState<boolean>({
    value: open,
    defaultValue: defaultOpen,
    onChange: onOpenChange,
  });
  const triggerRef = useRef<HTMLElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const initialFocus = useRef<InitialFocus>('first');
  const restoreFocus = useRef(true);
  const baseId = useId(undefined, 'rh-menu');

  const closeAndRestore = useCallback(() => {
    restoreFocus.current = true;
    setOpen(false);
  }, [setOpen]);

  const value = useMemo<MenuContextValue>(
    () => ({
      open: isOpen,
      setOpen,
      triggerRef,
      contentRef,
      menuId: `${baseId}-menu`,
      triggerId: `${baseId}-trigger`,
      placement,
      align,
      offset,
      container,
      initialFocus,
      restoreFocus,
      closeAndRestore,
    }),
    [align, baseId, closeAndRestore, container, isOpen, offset, placement, setOpen],
  );

  return <MenuContext.Provider value={value}>{children}</MenuContext.Provider>;
}

type ElementWithRef = ReactElement & { ref?: Ref<HTMLElement> };

export interface MenuTriggerProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Use the single child element as the trigger instead of rendering a button. */
  asChild?: boolean;
  children?: ReactNode;
}

export const MenuTrigger = forwardRef<HTMLButtonElement, MenuTriggerProps>(function MenuTrigger(
  { asChild = false, children, onClick, onKeyDown, ...rest },
  ref,
) {
  const { open, setOpen, triggerRef, menuId, triggerId, initialFocus, restoreFocus } =
    useMenuContext('MenuTrigger');

  const setRef = useCallback(
    (node: HTMLElement | null): void => {
      triggerRef.current = node;
      if (typeof ref === 'function') ref(node as HTMLButtonElement | null);
      else if (ref) ref.current = node as HTMLButtonElement | null;
    },
    [ref, triggerRef],
  );

  const openWith = (where: InitialFocus): void => {
    initialFocus.current = where;
    restoreFocus.current = true;
    setOpen(true);
  };

  const handleClick = (event: ReactMouseEvent<HTMLElement>): void => {
    if (event.defaultPrevented) return;
    if (open) {
      restoreFocus.current = true;
      setOpen(false);
    } else {
      openWith('first');
    }
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLElement>): void => {
    if (event.defaultPrevented) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      openWith('first');
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      openWith('last');
    }
  };

  const shared = {
    id: triggerId,
    'aria-haspopup': 'menu' as const,
    'aria-expanded': open,
    'aria-controls': open ? menuId : undefined,
    'data-state': open ? 'open' : 'closed',
  };

  if (asChild) {
    const child = children as ElementWithRef;
    const childProps = (child.props ?? {}) as {
      onClick?: (event: ReactMouseEvent<HTMLElement>) => void;
      onKeyDown?: (event: ReactKeyboardEvent<HTMLElement>) => void;
    };
    return cloneElement(child, {
      ...shared,
      ref: setRef,
      onClick: (event: ReactMouseEvent<HTMLElement>) => {
        childProps.onClick?.(event);
        handleClick(event);
      },
      onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => {
        childProps.onKeyDown?.(event);
        handleKeyDown(event);
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
        handleClick(event);
      }}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        handleKeyDown(event);
      }}
      {...rest}
    >
      {children}
    </button>
  );
});

export interface MenuContentProps extends HTMLAttributes<HTMLDivElement> {
  children?: ReactNode;
}

export const MenuContent = forwardRef<HTMLDivElement, MenuContentProps>(function MenuContent(
  { className, children, onKeyDown, ...rest },
  ref,
) {
  const {
    open,
    setOpen,
    triggerRef,
    contentRef,
    menuId,
    triggerId,
    placement,
    align,
    offset,
    container,
    initialFocus,
    restoreFocus,
    closeAndRestore,
  } = useMenuContext('MenuContent');

  const host = usePortal({ container, enabled: open, name: 'menu' });
  const { style, placement: resolvedPlacement } = useAnchorPosition({
    anchorRef: triggerRef,
    floatingRef: contentRef,
    placement,
    align,
    offset,
    enabled: open && host !== null,
  });

  const roving = useRovingTabIndex({
    containerRef: contentRef,
    itemSelector: '[role="menuitem"]',
    orientation: 'vertical',
    typeahead: true,
    onActivate: (item) => item.click(),
  });

  useDismiss({
    enabled: open,
    onDismiss: (reason) => {
      restoreFocus.current = reason === 'escape';
      setOpen(false);
    },
    refs: [triggerRef, contentRef],
  });

  const didFocusIn = useRef(false);
  useEffect(() => {
    if (open && host && !didFocusIn.current) {
      if (initialFocus.current === 'last') roving.focusLast();
      else roving.focusFirst();
      didFocusIn.current = true;
      return;
    }
    if (!open && didFocusIn.current) {
      didFocusIn.current = false;
      if (restoreFocus.current) focusElement(triggerRef.current);
    }
  }, [host, initialFocus, open, restoreFocus, roving, triggerRef]);

  if (!open || !host) return null;

  return createPortal(
    <div
      ref={(node) => {
        contentRef.current = node;
        if (typeof ref === 'function') ref(node);
        else if (ref) ref.current = node;
      }}
      id={menuId}
      role="menu"
      aria-labelledby={rest['aria-label'] === undefined ? triggerId : undefined}
      data-placement={resolvedPlacement}
      className={cx('rh-menu', className)}
      style={style}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (event.key === 'Tab') {
          // A menu is a single tab stop: Tab closes it rather than walking its items.
          event.preventDefault();
          closeAndRestore();
          return;
        }
        roving.onKeyDown(event);
      }}
      {...rest}
    >
      {children}
    </div>,
    host,
  );
});

export interface MenuItemProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onSelect'> {
  /** Called on click, Enter or Space. The menu closes afterwards. */
  onSelect?: () => void;
  disabled?: boolean;
  /** Leading decoration; hidden from assistive technology. */
  icon?: ReactNode;
  /** Trailing hint such as a keyboard shortcut. */
  hint?: ReactNode;
  children?: ReactNode;
}

export const MenuItem = forwardRef<HTMLDivElement, MenuItemProps>(function MenuItem(
  { onSelect, disabled = false, icon, hint, className, children, onClick, ...rest },
  ref,
) {
  const { closeAndRestore } = useMenuContext('MenuItem');
  return (
    <div
      ref={ref}
      role="menuitem"
      tabIndex={-1}
      aria-disabled={disabled ? true : undefined}
      data-rh-roving-item=""
      className={cx('rh-menu__item', className)}
      onClick={(event) => {
        onClick?.(event);
        if (disabled || event.defaultPrevented) return;
        onSelect?.();
        closeAndRestore();
      }}
      {...rest}
    >
      {icon ? (
        <span className="rh-menu__item-icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      <span className="rh-menu__item-label">{children}</span>
      {hint ? <span className="rh-menu__item-hint">{hint}</span> : null}
    </div>
  );
});

export type MenuSeparatorProps = HTMLAttributes<HTMLDivElement>;

export const MenuSeparator = forwardRef<HTMLDivElement, MenuSeparatorProps>(
  function MenuSeparator({ className, ...rest }, ref) {
    return (
      <div
        ref={ref}
        role="separator"
        aria-orientation="horizontal"
        className={cx('rh-menu__separator', className)}
        {...rest}
      />
    );
  },
);

export interface MenuGroupProps extends HTMLAttributes<HTMLDivElement> {
  /** Visible group heading, also the group's accessible name. */
  label: ReactNode;
  children?: ReactNode;
}

export const MenuGroup = forwardRef<HTMLDivElement, MenuGroupProps>(function MenuGroup(
  { label, className, children, ...rest },
  ref,
) {
  const labelId = useId(undefined, 'rh-menugroup');
  return (
    <div
      ref={ref}
      role="group"
      aria-labelledby={labelId}
      className={cx('rh-menu__group', className)}
      {...rest}
    >
      <div id={labelId} className="rh-menu__group-label">
        {label}
      </div>
      {children}
    </div>
  );
});

export const Menu = Object.assign(MenuRoot, {
  Trigger: MenuTrigger,
  Content: MenuContent,
  Item: MenuItem,
  Separator: MenuSeparator,
  Group: MenuGroup,
});
