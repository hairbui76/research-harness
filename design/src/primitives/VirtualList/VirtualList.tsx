import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type {
  ForwardedRef,
  HTMLAttributes,
  KeyboardEvent as ReactKeyboardEvent,
  ReactElement,
  ReactNode,
  Ref,
} from 'react';
import { cx } from '../../utils/cx';

export type VirtualListRole = 'list' | 'grid';

export type ScrollAlignment = 'auto' | 'start' | 'center' | 'end';

export interface VirtualListHandle {
  /** Brings an item into view. `auto` only scrolls when the item is outside the viewport. */
  scrollToIndex: (index: number, align?: ScrollAlignment) => void;
  scrollToOffset: (offset: number) => void;
  getVisibleRange: () => { start: number; end: number };
}

export interface VirtualListProps<T>
  extends Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'role'> {
  items: readonly T[];
  /** Stable key per item; also the measurement cache key, so heights survive reordering. */
  itemKey: (item: T, index: number) => string;
  renderItem: (item: T, index: number) => ReactNode;
  /** Height used before an item has been measured. Default 48. */
  estimatedItemHeight?: number;
  /** Extra items rendered above and below the viewport. Default 4. */
  overscan?: number;
  /** Viewport height. A number also seeds measurement where there is no layout (SSR, jsdom). */
  height?: number | string;
  /** `grid` renders rows with `aria-rowindex`; `renderItem` must then supply gridcells. */
  role?: VirtualListRole;
  /** Accessible name for the list. */
  label: string;
  onVisibleRangeChange?: (range: { start: number; end: number }) => void;
  /** Pixels moved by ArrowUp/ArrowDown. Defaults to `estimatedItemHeight`. */
  keyboardScrollStep?: number;
}

function findIndexAtOffset(offsets: readonly number[], offset: number): number {
  let low = 0;
  let high = offsets.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high + 1) / 2);
    if ((offsets[middle] ?? 0) <= offset) low = middle;
    else high = middle - 1;
  }
  return low;
}

function VirtualListInner<T>(
  {
    items,
    itemKey,
    renderItem,
    estimatedItemHeight = 48,
    overscan = 4,
    height,
    role = 'list',
    label,
    onVisibleRangeChange,
    keyboardScrollStep,
    className,
    style,
    onScroll,
    onKeyDown,
    ...rest
  }: VirtualListProps<T>,
  ref: ForwardedRef<VirtualListHandle>,
): ReactElement {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const windowRef = useRef<HTMLDivElement | null>(null);
  const heights = useRef(new Map<string, number>());
  const [measureVersion, setMeasureVersion] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  const [measuredViewport, setMeasuredViewport] = useState(
    typeof height === 'number' ? height : 0,
  );

  const offsets = useMemo(() => {
    const result: number[] = new Array<number>(items.length + 1);
    result[0] = 0;
    for (let index = 0; index < items.length; index += 1) {
      const item = items[index] as T;
      const measured = heights.current.get(itemKey(item, index));
      result[index + 1] = (result[index] as number) + (measured ?? estimatedItemHeight);
    }
    return result;
    // measureVersion invalidates the cache after a measurement pass.
  }, [estimatedItemHeight, itemKey, items, measureVersion]);

  const totalHeight = offsets[items.length] ?? 0;
  // Without layout (jsdom, SSR) fall back to a fixed window so the list still renders.
  const viewportHeight = measuredViewport > 0 ? measuredViewport : estimatedItemHeight * 8;

  const startIndex = items.length === 0 ? 0 : findIndexAtOffset(offsets, scrollTop);
  const endIndex =
    items.length === 0 ? 0 : Math.min(items.length, findIndexAtOffset(offsets, scrollTop + viewportHeight) + 1);
  const start = Math.max(0, startIndex - overscan);
  const end = Math.min(items.length, endIndex + overscan);

  const rangeRef = useRef({ start, end });
  useEffect(() => {
    if (rangeRef.current.start === start && rangeRef.current.end === end) return;
    rangeRef.current = { start, end };
    onVisibleRangeChange?.({ start, end });
  }, [end, onVisibleRangeChange, start]);

  // Measure what is on screen: offsetHeight first (works everywhere), then keep watching
  // with a ResizeObserver where one exists.
  useLayoutEffect(() => {
    const container = windowRef.current;
    if (!container) return;
    let changed = false;
    const measure = (element: HTMLElement): void => {
      const key = element.dataset.rhKey;
      if (key === undefined) return;
      const measured = element.offsetHeight;
      if (measured > 0 && heights.current.get(key) !== measured) {
        heights.current.set(key, measured);
        changed = true;
      }
    };
    const children = Array.from(container.children).filter(
      (child): child is HTMLElement => child instanceof HTMLElement,
    );
    for (const child of children) measure(child);
    if (changed) setMeasureVersion((version) => version + 1);

    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => {
      let observedChange = false;
      for (const entry of entries) {
        const element = entry.target;
        if (!(element instanceof HTMLElement)) continue;
        const key = element.dataset.rhKey;
        if (key === undefined) continue;
        const measured = element.offsetHeight;
        if (measured > 0 && heights.current.get(key) !== measured) {
          heights.current.set(key, measured);
          observedChange = true;
        }
      }
      if (observedChange) setMeasureVersion((version) => version + 1);
    });
    for (const child of children) observer.observe(child);
    return () => observer.disconnect();
  }, [end, items, start]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const apply = (): void => {
      if (viewport.clientHeight > 0) setMeasuredViewport(viewport.clientHeight);
    };
    apply();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(apply);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, []);

  const scrollToOffset = useCallback(
    (offset: number): void => {
      const max = Math.max(0, totalHeight - viewportHeight);
      const next = Math.min(Math.max(offset, 0), max);
      const viewport = viewportRef.current;
      if (viewport) viewport.scrollTop = next;
      setScrollTop(next);
    },
    [totalHeight, viewportHeight],
  );

  const scrollToIndex = useCallback(
    (index: number, align: ScrollAlignment = 'auto'): void => {
      const bounded = Math.min(Math.max(index, 0), Math.max(0, items.length - 1));
      const itemStart = offsets[bounded] ?? 0;
      const itemEnd = offsets[bounded + 1] ?? itemStart + estimatedItemHeight;
      const itemHeight = itemEnd - itemStart;
      switch (align) {
        case 'start':
          scrollToOffset(itemStart);
          return;
        case 'center':
          scrollToOffset(itemStart - viewportHeight / 2 + itemHeight / 2);
          return;
        case 'end':
          scrollToOffset(itemEnd - viewportHeight);
          return;
        default:
          if (itemStart < scrollTop) scrollToOffset(itemStart);
          else if (itemEnd > scrollTop + viewportHeight) scrollToOffset(itemEnd - viewportHeight);
      }
    },
    [estimatedItemHeight, items.length, offsets, scrollToOffset, scrollTop, viewportHeight],
  );

  useImperativeHandle(
    ref,
    () => ({
      scrollToIndex,
      scrollToOffset,
      getVisibleRange: () => ({ start, end }),
    }),
    [end, scrollToIndex, scrollToOffset, start],
  );

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>): void => {
    onKeyDown?.(event);
    if (event.defaultPrevented) return;
    const step = keyboardScrollStep ?? estimatedItemHeight;
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        scrollToOffset(scrollTop + step);
        return;
      case 'ArrowUp':
        event.preventDefault();
        scrollToOffset(scrollTop - step);
        return;
      case 'PageDown':
        event.preventDefault();
        scrollToOffset(scrollTop + viewportHeight);
        return;
      case 'PageUp':
        event.preventDefault();
        scrollToOffset(scrollTop - viewportHeight);
        return;
      case 'Home':
        event.preventDefault();
        scrollToOffset(0);
        return;
      case 'End':
        event.preventDefault();
        scrollToOffset(totalHeight);
        return;
      default:
    }
  };

  const visible: ReactNode[] = [];
  for (let index = start; index < end; index += 1) {
    const item = items[index] as T;
    const key = itemKey(item, index);
    visible.push(
      <div
        key={key}
        data-rh-key={key}
        data-index={index}
        role={role === 'grid' ? 'row' : 'listitem'}
        aria-rowindex={role === 'grid' ? index + 1 : undefined}
        // Only a window of the list exists in the DOM, so each item states where it sits
        // in the whole list rather than letting assistive technology count what it sees.
        aria-setsize={role === 'grid' ? undefined : items.length}
        aria-posinset={role === 'grid' ? undefined : index + 1}
        className="rh-virtual-list__item"
      >
        {renderItem(item, index)}
      </div>,
    );
  }

  return (
    <div
      ref={viewportRef}
      role={role}
      aria-label={label}
      aria-rowcount={role === 'grid' ? items.length : undefined}
      tabIndex={0}
      className={cx('rh-virtual-list', className)}
      style={{ ...style, height: typeof height === 'number' ? `${height}px` : height }}
      onScroll={(event) => {
        onScroll?.(event);
        setScrollTop(event.currentTarget.scrollTop);
      }}
      onKeyDown={handleKeyDown}
      {...rest}
    >
      <div className="rh-virtual-list__sizer" role="presentation" style={{ height: totalHeight }}>
        <div
          ref={windowRef}
          role="presentation"
          className="rh-virtual-list__window"
          style={{ transform: `translateY(${offsets[start] ?? 0}px)` }}
        >
          {visible}
        </div>
      </div>
    </div>
  );
}

/**
 * Windowed rendering for long transcripts, corpus tables and review queues. Items may vary
 * in height: each rendered item is measured and cached by its key, so scrolling does not
 * jump as messages expand. The whole list is one tab stop and scrolls from the keyboard.
 */
export const VirtualList = forwardRef(VirtualListInner) as <T>(
  props: VirtualListProps<T> & { ref?: Ref<VirtualListHandle> },
) => ReactElement;
