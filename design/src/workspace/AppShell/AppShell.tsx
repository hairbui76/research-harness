import { forwardRef, useEffect, useRef, useState } from 'react';
import type { HTMLAttributes, ReactElement, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { useId } from '../../hooks/useId';
import { useDismiss } from '../../hooks/useDismiss';
import { focusElement, getTabbable } from '../../hooks/focusable';
import { IconButton } from '../../primitives/IconButton';
import { useOptionalTheme } from '../ThemeProvider';

export interface AppShellProps extends HTMLAttributes<HTMLDivElement> {
  /** The project rail. Becomes a drawer below `breakpoint`. */
  rail?: ReactNode;
  /** The active surface. Always mounted, drawer or not — a draft is never unmounted. */
  main: ReactNode;
  /** The research inspector. Becomes a drawer below `breakpoint`. */
  inspector?: ReactNode;
  inspectorOpen?: boolean;
  onInspectorOpenChange?: (open: boolean) => void;
  railOpen?: boolean;
  onRailOpenChange?: (open: boolean) => void;
  /** Force the narrow layout. Omit to track `(max-width: <breakpoint>px)`. */
  narrow?: boolean;
  /** Width in px at or below which the side panes become drawers. Default 960. */
  breakpoint?: number;
  skipLinkLabel?: string;
  mainLabel?: string;
  railLabel?: string;
  inspectorLabel?: string;
}

/**
 * Tracks a max-width media query.
 *
 * jsdom and SSR have no `matchMedia`, so both report "not narrow" and a test that needs
 * the drawer layout passes `narrow` explicitly rather than faking a browser.
 */
function useNarrow(breakpoint: number, override?: boolean): boolean {
  const [narrow, setNarrow] = useState(false);

  useEffect(() => {
    if (override !== undefined) return;
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia(`(max-width: ${breakpoint}px)`);
    setNarrow(query.matches);
    const listener = (event: MediaQueryListEvent): void => setNarrow(event.matches);
    if (typeof query.addEventListener === 'function') {
      query.addEventListener('change', listener);
      return () => query.removeEventListener('change', listener);
    }
    query.addListener(listener);
    return () => query.removeListener(listener);
  }, [breakpoint, override]);

  return override ?? narrow;
}

interface DrawerProps {
  open: boolean;
  side: 'start' | 'end';
  label: string;
  onClose: () => void;
  children: ReactNode;
}

/**
 * A side pane in its narrow form.
 *
 * `aria-modal` is false on purpose: the main surface stays mounted and readable behind
 * the scrim, because a researcher's unsent draft must not disappear when they open the
 * session list. Focus still moves in on open, Escape still closes, and focus goes back to
 * whatever opened it — the parts of the dialog contract that matter here.
 */
function Drawer({ open, side, label, onClose, children }: DrawerProps): ReactElement {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const opener = useRef<HTMLElement | null>(null);

  useDismiss({
    enabled: open,
    onDismiss: (reason) => {
      if (reason === 'escape') onClose();
    },
    refs: [panelRef],
    outsidePress: false,
  });

  useEffect(() => {
    if (!open) {
      const previous = opener.current;
      opener.current = null;
      if (previous) focusElement(previous);
      return;
    }
    if (typeof document === 'undefined') return;
    const active = document.activeElement;
    opener.current = active instanceof HTMLElement ? active : null;
    const panel = panelRef.current;
    if (!panel) return;
    const [first] = getTabbable(panel);
    focusElement(first ?? panel);
  }, [open]);

  return (
    <div
      className={cx('rh-app-shell__drawer', `rh-app-shell__drawer--${side}`)}
      data-open={open ? '' : undefined}
      hidden={!open}
    >
      <div className="rh-app-shell__scrim" onMouseDown={onClose} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="false"
        aria-label={label}
        tabIndex={-1}
        className="rh-app-shell__drawer-panel"
      >
        <div className="rh-app-shell__drawer-head">
          <IconButton icon="x" label={`Close ${label.toLowerCase()}`} size="sm" onClick={onClose} />
        </div>
        {children}
      </div>
    </div>
  );
}

/**
 * The frame every Research Harness screen sits in: a rail, a main surface, and a
 * collapsible inspector, with a skip link ahead of all three.
 *
 * Below the width breakpoint the two side panes become drawers over a scrim while `main`
 * stays exactly where it was — the composer's draft, the editor's buffer and the scroll
 * position all survive, because nothing about `main` is remounted.
 */
export const AppShell = forwardRef<HTMLDivElement, AppShellProps>(function AppShell(
  {
    rail,
    main,
    inspector,
    inspectorOpen = true,
    onInspectorOpenChange,
    railOpen = false,
    onRailOpenChange,
    narrow,
    breakpoint = 960,
    skipLinkLabel = 'Skip to main content',
    mainLabel = 'Workspace',
    railLabel = 'Project navigation',
    inspectorLabel = 'Research inspector',
    className,
    id,
    ...rest
  },
  ref,
) {
  const baseId = useId(id, 'rh-appshell');
  const mainId = `${baseId}-main`;
  const isNarrow = useNarrow(breakpoint, narrow);
  const appearance = useOptionalTheme();

  const showRailInline = rail !== undefined && !isNarrow;
  const showInspectorInline = inspector !== undefined && !isNarrow && inspectorOpen;

  return (
    <div
      ref={ref}
      id={baseId}
      className={cx('rh-app-shell', className)}
      data-narrow={isNarrow ? '' : undefined}
      data-inspector-open={inspectorOpen ? '' : undefined}
      data-theme={appearance?.theme}
      data-density={appearance?.density}
      {...rest}
    >
      <a className="rh-app-shell__skip" href={`#${mainId}`}>
        {skipLinkLabel}
      </a>

      {isNarrow ? (
        // A banner landmark, not a bare row: below the breakpoint this bar is the only
        // thing on screen that is not inside `main`, the rail or the inspector, so its
        // title and its two drawer toggles have nowhere else to belong (axe `region`).
        <header className="rh-app-shell__bar">
          {/*
            A disclosure button, so its name stays put and `aria-expanded` carries the
            state. A label that flips between "Open" and "Close" would also collide with
            the drawer's own close button.
          */}
          {rail !== undefined ? (
            <IconButton
              icon="panel-left"
              label={railLabel}
              size="sm"
              aria-expanded={railOpen}
              onClick={() => onRailOpenChange?.(!railOpen)}
            />
          ) : null}
          <span className="rh-app-shell__bar-title">{mainLabel}</span>
          {inspector !== undefined ? (
            <IconButton
              icon="panel-right"
              label={inspectorLabel}
              size="sm"
              aria-expanded={inspectorOpen}
              onClick={() => onInspectorOpenChange?.(!inspectorOpen)}
            />
          ) : null}
        </header>
      ) : null}

      <div className="rh-app-shell__body">
        {showRailInline ? <div className="rh-app-shell__rail">{rail}</div> : null}

        <main id={mainId} className="rh-app-shell__main" aria-label={mainLabel} tabIndex={-1}>
          {main}
        </main>

        {showInspectorInline ? (
          <aside className="rh-app-shell__inspector" aria-label={inspectorLabel}>
            {inspector}
          </aside>
        ) : null}
      </div>

      {isNarrow && rail !== undefined ? (
        <Drawer
          open={railOpen}
          side="start"
          label={railLabel}
          onClose={() => onRailOpenChange?.(false)}
        >
          {rail}
        </Drawer>
      ) : null}

      {isNarrow && inspector !== undefined ? (
        <Drawer
          open={inspectorOpen}
          side="end"
          label={inspectorLabel}
          onClose={() => onInspectorOpenChange?.(false)}
        >
          {inspector}
        </Drawer>
      ) : null}
    </div>
  );
});
