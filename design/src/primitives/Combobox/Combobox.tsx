import { Fragment, forwardRef, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  ForwardedRef,
  InputHTMLAttributes,
  KeyboardEvent as ReactKeyboardEvent,
  ReactElement,
  ReactNode,
  Ref,
} from 'react';
import { Icon } from '../Icon';
import { useControllableState } from '../../hooks/useControllableState';
import { useDismiss } from '../../hooks/useDismiss';
import { useId } from '../../hooks/useId';
import { cx } from '../../utils/cx';

export interface ComboboxItem<T = unknown> {
  /** Stable identity; also the DOM id suffix of the option. */
  id: string;
  /** Text shown in the option and used as its accessible name. */
  label: string;
  /** Payload handed back to `onChange`. */
  value?: T;
  disabled?: boolean;
  /** Options sharing a group name are wrapped in a labelled `group`. */
  group?: string;
  /** Secondary line under the label. */
  description?: string;
}

/** What happens to the query text after a selection. */
export type ComboboxSelectionBehaviour = 'fill' | 'clear' | 'keep';

export interface ComboboxProps<T = unknown>
  extends Omit<
    InputHTMLAttributes<HTMLInputElement>,
    'value' | 'defaultValue' | 'onChange' | 'onSelect' | 'type' | 'role' | 'size'
  > {
  /**
   * The options to show, already filtered by the caller. The Combobox never filters:
   * matching is a research concern (fuzzy entity search, graph lookups, remote paging)
   * that belongs in the application, and it reports typing through `onQueryChange`.
   */
  items: ReadonlyArray<ComboboxItem<T>>;
  /**
   * Accessible name for the text box and the list.
   *
   * A host that draws its own visible label points at it with `aria-labelledby` instead;
   * the text box then takes its name from that element and carries no `aria-label`, so the
   * name a screen reader hears is the words on the page rather than a second string. The
   * listbox is a different element and keeps this one.
   */
  label: string;
  /** Controlled selected item id, or null. */
  value?: string | null;
  defaultValue?: string | null;
  onChange?: (item: ComboboxItem<T> | null) => void;
  /** Controlled query text. */
  query?: string;
  defaultQuery?: string;
  onQueryChange?: (query: string) => void;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Shows a busy row while the caller fetches matches. */
  loading?: boolean;
  loadingMessage?: ReactNode;
  /** Shown when `items` is empty and nothing is loading. */
  emptyMessage?: ReactNode;
  /** Renders the inside of an option. Receives active/selected state. */
  renderItem?: (item: ComboboxItem<T>, state: { active: boolean; selected: boolean }) => ReactNode;
  /** Open the list as soon as the text box receives focus. */
  openOnFocus?: boolean;
  /** What the query does after a selection. Default `fill`. */
  selectionBehaviour?: ComboboxSelectionBehaviour;
  className?: string;
}

interface GroupedItems<T> {
  group: string | undefined;
  items: ComboboxItem<T>[];
}

function groupItems<T>(items: ReadonlyArray<ComboboxItem<T>>): GroupedItems<T>[] {
  const groups: GroupedItems<T>[] = [];
  for (const item of items) {
    const last = groups[groups.length - 1];
    if (last && last.group === item.group) last.items.push(item);
    else groups.push({ group: item.group, items: [item] });
  }
  return groups;
}

function ComboboxInner<T>(
  {
    items,
    label,
    value,
    defaultValue = null,
    onChange,
    query,
    defaultQuery = '',
    onQueryChange,
    open,
    defaultOpen = false,
    onOpenChange,
    loading = false,
    loadingMessage = 'Searching…',
    emptyMessage = 'No matches',
    renderItem,
    openOnFocus = false,
    selectionBehaviour = 'fill',
    className,
    disabled,
    onKeyDown,
    onFocus,
    id,
    'aria-labelledby': labelledBy,
    ...rest
  }: ComboboxProps<T>,
  ref: ForwardedRef<HTMLInputElement>,
): ReactElement {
  const baseId = useId(id, 'rh-combobox');
  const listboxId = `${baseId}-listbox`;
  const optionId = (itemId: string): string => `${baseId}-option-${itemId.replace(/[^A-Za-z0-9_-]/g, '-')}`;

  const [isOpen, setOpen] = useControllableState<boolean>({
    value: open,
    defaultValue: defaultOpen,
    onChange: onOpenChange,
  });
  const [selectedId, setSelectedId] = useControllableState<string | null>({
    value,
    defaultValue,
    onChange: undefined,
  });
  const [queryText, setQueryText] = useControllableState<string>({
    value: query,
    defaultValue: defaultQuery,
    onChange: onQueryChange,
  });
  const [activeId, setActiveId] = useState<string | null>(null);

  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const enabledItems = useMemo(() => items.filter((item) => item.disabled !== true), [items]);

  // Drop a stale active option when the caller swaps the result set.
  useEffect(() => {
    if (activeId !== null && !enabledItems.some((item) => item.id === activeId)) setActiveId(null);
  }, [activeId, enabledItems]);

  useDismiss({
    enabled: isOpen,
    onDismiss: () => setOpen(false),
    refs: [rootRef],
    escapeKey: false,
  });

  const setInputRef = useCallback(
    (node: HTMLInputElement | null): void => {
      inputRef.current = node;
      if (typeof ref === 'function') ref(node);
      else if (ref) ref.current = node;
    },
    [ref],
  );

  const select = useCallback(
    (item: ComboboxItem<T> | null): void => {
      setSelectedId(item?.id ?? null);
      onChange?.(item);
      if (item) {
        if (selectionBehaviour === 'fill') setQueryText(item.label);
        else if (selectionBehaviour === 'clear') setQueryText('');
      }
      setOpen(false);
      setActiveId(null);
    },
    [onChange, selectionBehaviour, setOpen, setQueryText, setSelectedId],
  );

  const moveActive = useCallback(
    (delta: number): void => {
      if (enabledItems.length === 0) return;
      const currentIndex = enabledItems.findIndex((item) => item.id === activeId);
      const nextIndex =
        currentIndex < 0
          ? delta > 0
            ? 0
            : enabledItems.length - 1
          : (currentIndex + delta + enabledItems.length) % enabledItems.length;
      setActiveId(enabledItems[nextIndex]?.id ?? null);
    },
    [activeId, enabledItems],
  );

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>): void => {
    onKeyDown?.(event);
    if (event.defaultPrevented) return;

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        if (!isOpen) {
          setOpen(true);
          setActiveId(enabledItems[0]?.id ?? null);
        } else moveActive(1);
        return;
      case 'ArrowUp':
        event.preventDefault();
        if (!isOpen) {
          setOpen(true);
          setActiveId(enabledItems[enabledItems.length - 1]?.id ?? null);
        } else moveActive(-1);
        return;
      case 'Enter': {
        if (!isOpen || activeId === null) return;
        event.preventDefault();
        const item = enabledItems.find((entry) => entry.id === activeId) ?? null;
        if (item) select(item);
        return;
      }
      case 'Escape':
        event.preventDefault();
        if (isOpen) {
          setOpen(false);
          setActiveId(null);
          return;
        }
        // Closed: Escape clears the search, matching the ARIA combobox pattern.
        setQueryText('');
        setSelectedId(null);
        onChange?.(null);
        return;
      case 'Tab':
        if (isOpen) setOpen(false);
        return;
      default:
    }
  };

  const groups = groupItems(items);
  const showEmpty = !loading && items.length === 0;

  return (
    <div
      ref={rootRef}
      className={cx('rh-combobox', className)}
      data-state={isOpen ? 'open' : 'closed'}
    >
      <input
        {...rest}
        ref={setInputRef}
        id={baseId}
        type="text"
        role="combobox"
        className="rh-combobox__input"
        {...(labelledBy === undefined
          ? { 'aria-label': label }
          : { 'aria-labelledby': labelledBy })}
        aria-expanded={isOpen}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={isOpen && activeId !== null ? optionId(activeId) : undefined}
        aria-busy={loading || undefined}
        autoComplete="off"
        disabled={disabled}
        value={queryText}
        onChange={(event) => {
          setQueryText(event.target.value);
          if (!isOpen) setOpen(true);
        }}
        onFocus={(event) => {
          onFocus?.(event);
          if (openOnFocus && !isOpen) setOpen(true);
        }}
        onKeyDown={handleKeyDown}
      />
      <div className="rh-combobox__panel" hidden={!isOpen}>
        <div id={listboxId} role="listbox" aria-label={label} className="rh-combobox__listbox">
          {groups.map((group) => {
          const options = group.items.map((item) => {
            const active = item.id === activeId;
            const selected = item.id === selectedId;
            return (
              <div
                key={item.id}
                id={optionId(item.id)}
                role="option"
                aria-selected={selected}
                aria-disabled={item.disabled === true ? true : undefined}
                data-active={active ? '' : undefined}
                className="rh-combobox__option"
                onMouseDown={(event) => {
                  // Keep focus in the text box so the caret and activedescendant survive.
                  event.preventDefault();
                }}
                onMouseEnter={() => {
                  if (item.disabled !== true) setActiveId(item.id);
                }}
                onClick={() => {
                  if (item.disabled !== true) select(item);
                }}
              >
                <span className="rh-combobox__option-content">
                  {renderItem ? (
                    renderItem(item, { active, selected })
                  ) : (
                    <>
                      <span className="rh-combobox__option-label">{item.label}</span>
                      {item.description ? (
                        <span className="rh-combobox__option-description">{item.description}</span>
                      ) : null}
                    </>
                  )}
                </span>
                {/* The mark for what is chosen, from the registry rather than as a glyph in
                    the text. `aria-selected` already carries it to a screen reader, so the
                    icon is decorative — the same division `Menu` draws between an item's
                    icon and its label. */}
                {selected ? (
                  <Icon name="check" size={14} className="rh-combobox__option-check" />
                ) : null}
              </div>
            );
          });

            if (group.group === undefined) {
              return <Fragment key="ungrouped">{options}</Fragment>;
            }
            return (
              <ComboboxGroup key={group.group} label={group.group}>
                {options}
              </ComboboxGroup>
            );
          })}
        </div>
        {loading ? (
          <div className="rh-combobox__status" role="status">
            {loadingMessage}
          </div>
        ) : null}
        {showEmpty ? (
          <div className="rh-combobox__status" role="status">
            {emptyMessage}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ComboboxGroup({ label, children }: { label: string; children: ReactNode }): ReactElement {
  const labelId = useId(undefined, 'rh-comboboxgroup');
  return (
    <div role="group" aria-labelledby={labelId} className="rh-combobox__group">
      <div id={labelId} className="rh-combobox__group-label">
        {label}
      </div>
      {children}
    </div>
  );
}

/**
 * A text box with a filtered listbox: the composer's `@` reference picker, model pickers
 * and corpus search all build on it. The caller owns matching and paging; the primitive
 * owns the keyboard contract and the ARIA wiring.
 */
export const Combobox = forwardRef(ComboboxInner) as <T>(
  props: ComboboxProps<T> & { ref?: Ref<HTMLInputElement> },
) => ReactElement;
