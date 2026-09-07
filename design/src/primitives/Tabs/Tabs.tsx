import { createContext, forwardRef, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react';
import { useControllableState } from '../../hooks/useControllableState';
import { useId } from '../../hooks/useId';
import { useRovingTabIndex } from '../../hooks/useRovingTabIndex';
import { cx } from '../../utils/cx';
import { Icon } from '../Icon';

export type TabsOrientation = 'horizontal' | 'vertical';
export type TabsActivation = 'automatic' | 'manual';
export type TabsOverflow = 'scroll' | 'wrap';

interface TabsContextValue {
  baseId: string;
  value: string;
  select: (value: string) => void;
  orientation: TabsOrientation;
  activation: TabsActivation;
  keepMounted: boolean;
}

const TabsContext = createContext<TabsContextValue | null>(null);

function useTabsContext(component: string): TabsContextValue {
  const context = useContext(TabsContext);
  if (!context) throw new Error(`<${component}> must be rendered inside <Tabs>.`);
  return context;
}

/** Values become part of DOM ids, so they are reduced to id-safe characters. */
function idPart(value: string): string {
  return value.replace(/[^A-Za-z0-9_-]/g, '-');
}

function tabId(baseId: string, value: string): string {
  return `${baseId}-tab-${idPart(value)}`;
}

function panelId(baseId: string, value: string): string {
  return `${baseId}-panel-${idPart(value)}`;
}

export interface TabsProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onChange'> {
  /** Controlled selected tab value. */
  value?: string;
  /** Initial selected tab value when uncontrolled. */
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  /** Arrow-key axis and visual direction. Default `horizontal`. */
  orientation?: TabsOrientation;
  /**
   * `automatic` selects a tab as soon as it receives focus (WAI-ARIA's default, right when
   * panels are cheap); `manual` waits for Enter, Space or a click, which is what a panel
   * that fetches or compiles should use.
   */
  activation?: TabsActivation;
  /** Keep unselected panels mounted (hidden) instead of unmounting them. */
  keepMounted?: boolean;
  /** Shared id prefix for tab/panel wiring; generated when omitted. */
  id?: string;
  children?: ReactNode;
}

const TabsRoot = forwardRef<HTMLDivElement, TabsProps>(function Tabs(
  {
    value,
    defaultValue = '',
    onValueChange,
    orientation = 'horizontal',
    activation = 'automatic',
    keepMounted = false,
    className,
    children,
    id,
    ...rest
  },
  ref,
) {
  const baseId = useId(id, 'rh-tabs');
  const [selected, setSelected] = useControllableState<string>({
    value,
    defaultValue,
    onChange: onValueChange,
  });

  const context = useMemo<TabsContextValue>(
    () => ({ baseId, value: selected, select: setSelected, orientation, activation, keepMounted }),
    [activation, baseId, keepMounted, orientation, selected, setSelected],
  );

  return (
    <TabsContext.Provider value={context}>
      <div
        ref={ref}
        className={cx('rh-tabs', className)}
        data-orientation={orientation}
        {...rest}
      >
        {children}
      </div>
    </TabsContext.Provider>
  );
});

/**
 * Bring a tab fully inside the strip without moving anything else on the page.
 *
 * Instantly, not smoothly: a tab reached with an arrow key has focus the moment the key is
 * pressed, and the strip has to be showing it at that same moment — an animation that is
 * still running when the next key lands (or that a busy machine stalls) leaves focus on a
 * tab a person cannot see. The strip's own chevrons keep the smooth scroll; they move the
 * strip, not the focus.
 */
function revealTab(tab: HTMLElement | null | undefined): void {
  if (!tab || typeof tab.scrollIntoView !== 'function') return;
  tab.scrollIntoView({ behavior: 'instant', block: 'nearest', inline: 'nearest' });
}

export interface TabListProps extends HTMLAttributes<HTMLDivElement> {
  /** Required unless `aria-labelledby` names the list. */
  'aria-label'?: string;
  /**
   * What the strip does when the tabs are wider than the space it has. `scroll` (the
   * default) keeps one row and says at which edge the hidden tabs are; `wrap` spends
   * vertical room instead, for a host that has some.
   */
  overflow?: TabsOverflow;
  children?: ReactNode;
}

/**
 * The tab strip.
 *
 * A pane is not always as wide as its tabs — the research inspector holds six of them in
 * about 350px — and a strip that simply clips is a strip whose last two tabs do not exist
 * as far as a researcher can tell. So the strip measures itself: when the row is wider
 * than the space it has, it says at which edge the rest of the tabs are and offers a
 * control to get there, and every tab reached with an arrow key is scrolled into view.
 * The controls are pointer affordances for something the keyboard can already do, so they
 * stay out of the tab order and out of the accessibility tree; the tabs themselves are the
 * only announced way through the strip.
 */
export const TabList = forwardRef<HTMLDivElement, TabListProps>(function TabList(
  { className, children, onKeyDown, onScroll, overflow = 'scroll', ...rest },
  ref,
) {
  const { orientation, activation, select, value } = useTabsContext('TabList');
  const listRef = useRef<HTMLDivElement | null>(null);
  const [edges, setEdges] = useState({ start: false, end: false });
  const scrolls = overflow === 'scroll' && orientation === 'horizontal';

  const measure = useCallback((): void => {
    const node = listRef.current;
    if (!node || !scrolls) {
      setEdges((current) => (current.start || current.end ? { start: false, end: false } : current));
      return;
    }
    // A right-to-left strip reports its offset as a negative number.
    const offset = Math.abs(node.scrollLeft);
    const slack = node.scrollWidth - node.clientWidth;
    const next = { start: offset > 1, end: slack - offset > 1 };
    setEdges((current) =>
      current.start === next.start && current.end === next.end ? current : next,
    );
  }, [scrolls]);

  useEffect(() => {
    measure();
    const node = listRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(node);
    for (const child of Array.from(node.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [children, measure]);

  // A selection made somewhere else — a shortcut, a deep link, a restored session — has to
  // bring its tab into view too, not only the one that was clicked.
  useEffect(() => {
    if (!scrolls) return;
    revealTab(listRef.current?.querySelector<HTMLElement>('[role="tab"][data-state="selected"]'));
  }, [scrolls, value]);

  const nudge = (direction: -1 | 1): void => {
    const node = listRef.current;
    if (!node) return;
    const step = Math.max(node.clientWidth * 0.8, 96);
    if (typeof node.scrollBy === 'function') node.scrollBy({ left: direction * step });
    else node.scrollLeft += direction * step;
  };

  const roving = useRovingTabIndex({
    containerRef: listRef,
    itemSelector: '[role="tab"]',
    orientation,
    loop: true,
    onFocusChange: (item) => {
      if (scrolls) revealTab(item);
      if (activation !== 'automatic') return;
      const next = item.dataset.value;
      if (next !== undefined) select(next);
    },
    onActivate: (item) => {
      const next = item.dataset.value;
      if (next !== undefined) select(next);
    },
  });

  const overflowState = edges.start && edges.end ? 'both' : edges.start ? 'start' : edges.end ? 'end' : 'none';

  return (
    <div className="rh-tabs__strip" data-overflow={overflowState}>
      {edges.start ? <ScrollControl edge="start" onClick={() => nudge(-1)} /> : null}
      <div
        ref={(node) => {
          listRef.current = node;
          if (typeof ref === 'function') ref(node);
          else if (ref) ref.current = node;
        }}
        role="tablist"
        aria-orientation={orientation}
        data-overflow={overflow}
        className={cx('rh-tabs__list', className)}
        onKeyDown={(event) => {
          onKeyDown?.(event);
          roving.onKeyDown(event);
        }}
        onScroll={(event) => {
          onScroll?.(event);
          measure();
        }}
        {...rest}
      >
        {children}
      </div>
      {edges.end ? <ScrollControl edge="end" onClick={() => nudge(1)} /> : null}
    </div>
  );
});

/**
 * The pointer's way to the tabs the strip is hiding.
 *
 * `aria-hidden` is deliberate: arrow keys already walk every tab and scroll it into view,
 * so announcing two more controls would add nothing but noise. `tabIndex={-1}` keeps it
 * out of the tab order, which is what makes hiding it from assistive technology honest.
 */
function ScrollControl({ edge, onClick }: { edge: 'start' | 'end'; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-hidden="true"
      tabIndex={-1}
      className={cx('rh-tabs__scroll', `rh-tabs__scroll--${edge}`)}
      onClick={onClick}
    >
      <Icon name={edge === 'start' ? 'chevron-left' : 'chevron-right'} size={14} />
    </button>
  );
}

export interface TabProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'value'> {
  /** Identifies the tab and its panel. */
  value: string;
  children?: ReactNode;
}

export const Tab = forwardRef<HTMLButtonElement, TabProps>(function Tab(
  { value, className, children, disabled, onClick, ...rest },
  ref,
) {
  const { baseId, value: selectedValue, select } = useTabsContext('Tab');
  const selected = selectedValue === value;

  return (
    <button
      ref={ref}
      type="button"
      role="tab"
      id={tabId(baseId, value)}
      aria-selected={selected}
      aria-controls={panelId(baseId, value)}
      aria-disabled={disabled ? true : undefined}
      disabled={disabled}
      tabIndex={selected ? 0 : -1}
      data-value={value}
      data-state={selected ? 'selected' : 'idle'}
      data-rh-roving-item=""
      className={cx('rh-tabs__tab', className)}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) select(value);
      }}
      {...rest}
    >
      {children}
    </button>
  );
});

export interface TabPanelProps extends HTMLAttributes<HTMLDivElement> {
  value: string;
  /** Override the Tabs-level `keepMounted` for this panel. */
  keepMounted?: boolean;
  children?: ReactNode;
}

export const TabPanel = forwardRef<HTMLDivElement, TabPanelProps>(function TabPanel(
  { value, className, children, keepMounted, ...rest },
  ref,
) {
  const { baseId, value: selectedValue, keepMounted: groupKeepMounted } = useTabsContext('TabPanel');
  const selected = selectedValue === value;
  const stayMounted = keepMounted ?? groupKeepMounted;

  if (!selected && !stayMounted) return null;

  return (
    <div
      ref={ref}
      role="tabpanel"
      id={panelId(baseId, value)}
      aria-labelledby={tabId(baseId, value)}
      hidden={!selected}
      tabIndex={selected ? 0 : -1}
      data-state={selected ? 'selected' : 'idle'}
      className={cx('rh-tabs__panel', className)}
      {...rest}
    >
      {children}
    </div>
  );
});

export const Tabs = Object.assign(TabsRoot, {
  List: TabList,
  Tab,
  Panel: TabPanel,
});
