import { createContext, forwardRef, useContext, useMemo, useRef } from 'react';
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react';
import { useControllableState } from '../../hooks/useControllableState';
import { useId } from '../../hooks/useId';
import { useRovingTabIndex } from '../../hooks/useRovingTabIndex';
import { cx } from '../../utils/cx';

export type TabsOrientation = 'horizontal' | 'vertical';
export type TabsActivation = 'automatic' | 'manual';

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

export interface TabListProps extends HTMLAttributes<HTMLDivElement> {
  /** Required unless `aria-labelledby` names the list. */
  'aria-label'?: string;
  children?: ReactNode;
}

export const TabList = forwardRef<HTMLDivElement, TabListProps>(function TabList(
  { className, children, onKeyDown, ...rest },
  ref,
) {
  const { orientation, activation, select } = useTabsContext('TabList');
  const listRef = useRef<HTMLDivElement | null>(null);

  const roving = useRovingTabIndex({
    containerRef: listRef,
    itemSelector: '[role="tab"]',
    orientation,
    loop: true,
    onFocusChange: (item) => {
      if (activation !== 'automatic') return;
      const next = item.dataset.value;
      if (next !== undefined) select(next);
    },
    onActivate: (item) => {
      const next = item.dataset.value;
      if (next !== undefined) select(next);
    },
  });

  return (
    <div
      ref={(node) => {
        listRef.current = node;
        if (typeof ref === 'function') ref(node);
        else if (ref) ref.current = node;
      }}
      role="tablist"
      aria-orientation={orientation}
      className={cx('rh-tabs__list', className)}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        roving.onKeyDown(event);
      }}
      {...rest}
    >
      {children}
    </div>
  );
});

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
