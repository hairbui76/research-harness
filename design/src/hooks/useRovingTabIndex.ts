import { useCallback, useMemo, useRef } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, RefObject } from 'react';
import { focusElement, isDisabledElement, isFocusVisible } from './focusable';

export type RovingOrientation = 'horizontal' | 'vertical' | 'both';

export interface UseRovingTabIndexOptions {
  /** Element that owns the items (a tablist, a menu, a toolbar). */
  containerRef: RefObject<HTMLElement | null>;
  /** How items are found inside the container. */
  itemSelector?: string | undefined;
  /** Which arrow keys move focus. Default `horizontal`. */
  orientation?: RovingOrientation | undefined;
  /** Wrap from last to first. Default true. */
  loop?: boolean | undefined;
  /** Home/End jump to the ends. Default true. */
  homeEnd?: boolean | undefined;
  /** Printable characters jump to the next item whose text starts with them. Default false. */
  typeahead?: boolean | undefined;
  /** Called after focus moves - Tabs uses it for automatic activation. */
  onFocusChange?: ((item: HTMLElement, index: number) => void) | undefined;
  /** Called for Enter and Space on the focused item. */
  onActivate?: ((item: HTMLElement, index: number) => void) | undefined;
  /** Override the disabled test. Defaults to `disabled` / `aria-disabled`. */
  isDisabled?: ((item: HTMLElement) => boolean) | undefined;
}

export interface RovingTabIndexApi {
  /** Attach to the container's `onKeyDown`. */
  onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => void;
  /** Enabled items, in document order. */
  getItems: () => HTMLElement[];
  /** Index of the item holding focus, or -1. */
  getActiveIndex: () => number;
  focusItemAt: (index: number) => HTMLElement | null;
  focusFirst: () => HTMLElement | null;
  focusLast: () => HTMLElement | null;
}

const TYPEAHEAD_RESET_MS = 500;

/**
 * The one keyboard model behind Tabs and Menu: one tab stop for the whole group, arrow
 * keys to move within it, Home/End to the ends, optional typeahead, Enter/Space to
 * activate. Items are read from the DOM rather than registered, so composition (fragments,
 * groups, separators, conditionally rendered items) needs no bookkeeping from the caller.
 */
export function useRovingTabIndex({
  containerRef,
  itemSelector = '[data-rh-roving-item]',
  orientation = 'horizontal',
  loop = true,
  homeEnd = true,
  typeahead = false,
  onFocusChange,
  onActivate,
  isDisabled,
}: UseRovingTabIndexOptions): RovingTabIndexApi {
  const typeaheadBuffer = useRef({ text: '', at: 0 });
  const callbacks = useRef({ onFocusChange, onActivate, isDisabled });
  callbacks.current = { onFocusChange, onActivate, isDisabled };

  const getItems = useCallback((): HTMLElement[] => {
    const container = containerRef.current;
    if (!container) return [];
    const disabledTest = callbacks.current.isDisabled ?? isDisabledElement;
    return Array.from(container.querySelectorAll<HTMLElement>(itemSelector)).filter(
      (item) => isFocusVisible(item) && !disabledTest(item),
    );
  }, [containerRef, itemSelector]);

  const getActiveIndex = useCallback((): number => {
    const active = document.activeElement;
    if (!(active instanceof HTMLElement)) return -1;
    return getItems().findIndex((item) => item === active || item.contains(active));
  }, [getItems]);

  const focusItemAt = useCallback(
    (index: number): HTMLElement | null => {
      const items = getItems();
      if (items.length === 0) return null;
      const bounded = loop
        ? ((index % items.length) + items.length) % items.length
        : Math.min(Math.max(index, 0), items.length - 1);
      const item = items[bounded];
      if (!item) return null;
      focusElement(item);
      callbacks.current.onFocusChange?.(item, bounded);
      return item;
    },
    [getItems, loop],
  );

  const focusFirst = useCallback(() => focusItemAt(0), [focusItemAt]);
  const focusLast = useCallback(() => {
    const items = getItems();
    return focusItemAt(items.length - 1);
  }, [focusItemAt, getItems]);

  const runTypeahead = useCallback(
    (key: string): boolean => {
      const now = Date.now();
      const buffer = typeaheadBuffer.current;
      buffer.text = now - buffer.at > TYPEAHEAD_RESET_MS ? key : buffer.text + key;
      buffer.at = now;
      const needle = buffer.text.toLowerCase();
      const items = getItems();
      if (items.length === 0) return false;
      const start = getActiveIndex();
      // Repeating one character cycles through the items starting with it.
      const offset = buffer.text.length === 1 ? 1 : 0;
      for (let step = 0; step < items.length; step += 1) {
        const index = (start + offset + step + items.length) % items.length;
        const item = items[index];
        const label = (item?.textContent ?? '').trim().toLowerCase();
        if (item && label.startsWith(needle)) {
          focusItemAt(index);
          return true;
        }
      }
      return false;
    },
    [focusItemAt, getActiveIndex, getItems],
  );

  const onKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLElement>): void => {
      if (event.defaultPrevented) return;
      const horizontal = orientation === 'horizontal' || orientation === 'both';
      const vertical = orientation === 'vertical' || orientation === 'both';
      const current = getActiveIndex();
      const { key } = event;

      const next = (delta: number): void => {
        event.preventDefault();
        focusItemAt(current < 0 ? (delta > 0 ? 0 : -1) : current + delta);
      };

      if ((key === 'ArrowRight' && horizontal) || (key === 'ArrowDown' && vertical)) {
        next(1);
        return;
      }
      if ((key === 'ArrowLeft' && horizontal) || (key === 'ArrowUp' && vertical)) {
        next(-1);
        return;
      }
      if (homeEnd && key === 'Home') {
        event.preventDefault();
        focusFirst();
        return;
      }
      if (homeEnd && key === 'End') {
        event.preventDefault();
        focusLast();
        return;
      }
      if (key === 'Enter' || key === ' ' || key === 'Spacebar') {
        const items = getItems();
        const item = current >= 0 ? items[current] : undefined;
        if (item && callbacks.current.onActivate) {
          event.preventDefault();
          callbacks.current.onActivate(item, current);
        }
        return;
      }
      if (
        typeahead &&
        key.length === 1 &&
        key !== ' ' &&
        !event.ctrlKey &&
        !event.metaKey &&
        !event.altKey
      ) {
        if (runTypeahead(key)) event.preventDefault();
      }
    },
    [focusFirst, focusItemAt, focusLast, getActiveIndex, getItems, homeEnd, orientation, runTypeahead, typeahead],
  );

  return useMemo(
    () => ({ onKeyDown, getItems, getActiveIndex, focusItemAt, focusFirst, focusLast }),
    [focusFirst, focusItemAt, focusLast, getActiveIndex, getItems, onKeyDown],
  );
}
