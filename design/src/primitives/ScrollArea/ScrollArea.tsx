import { forwardRef, useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, HTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';

export type ScrollAreaOrientation = 'vertical' | 'horizontal' | 'both';

export interface ScrollAreaProps extends HTMLAttributes<HTMLDivElement> {
  orientation?: ScrollAreaOrientation;
  maxHeight?: number | string;
  maxWidth?: number | string;
  /**
   * Accessible name used once the region actually scrolls. WCAG 2.2 requires a scrollable
   * region to be reachable by keyboard, and a keyboard-reachable region needs a name.
   */
  label?: string;
  /**
   * Force the focusable/scrollable treatment. Measurement needs layout, which jsdom and
   * SSR do not have, so a caller that already knows can say so.
   */
  scrollable?: boolean;
  children?: ReactNode;
}

function toLength(value: number | string | undefined): string | undefined {
  if (value === undefined) return undefined;
  return typeof value === 'number' ? `${value}px` : value;
}

/**
 * A thin wrapper around native scrolling: no custom scrollbar, no wheel hijacking, no
 * virtualisation. It only adds the part browsers leave to the author - a tab stop and an
 * accessible name once the content actually overflows.
 */
export const ScrollArea = forwardRef<HTMLDivElement, ScrollAreaProps>(function ScrollArea(
  { orientation = 'vertical', maxHeight, maxWidth, label, scrollable, className, style, children, ...rest },
  ref,
) {
  const innerRef = useRef<HTMLDivElement | null>(null);
  const [overflowing, setOverflowing] = useState(false);

  const measure = useCallback((): void => {
    const node = innerRef.current;
    if (!node) return;
    const vertical = node.scrollHeight > node.clientHeight;
    const horizontal = node.scrollWidth > node.clientWidth;
    const next =
      orientation === 'vertical' ? vertical : orientation === 'horizontal' ? horizontal : vertical || horizontal;
    setOverflowing(next);
  }, [orientation]);

  useEffect(() => {
    measure();
    const node = innerRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(node);
    for (const child of Array.from(node.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [children, measure]);

  const isScrollable = scrollable ?? overflowing;

  const mergedStyle: CSSProperties = {
    ...style,
    maxHeight: toLength(maxHeight),
    maxWidth: toLength(maxWidth),
  };

  return (
    <div
      ref={(node) => {
        innerRef.current = node;
        if (typeof ref === 'function') ref(node);
        else if (ref) ref.current = node;
      }}
      className={cx('rh-scroll-area', className)}
      data-orientation={orientation}
      data-scrollable={isScrollable ? '' : undefined}
      role={isScrollable ? 'region' : undefined}
      aria-label={isScrollable ? label : undefined}
      tabIndex={isScrollable ? 0 : undefined}
      style={mergedStyle}
      {...rest}
    >
      {children}
    </div>
  );
});
