import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { CSSProperties, RefObject } from 'react';

export type AnchorPlacement = 'top' | 'bottom' | 'left' | 'right';
export type AnchorAlignment = 'start' | 'center' | 'end';

export interface AnchorRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface ComputeAnchorPositionInput {
  anchor: AnchorRect;
  floating: { width: number; height: number };
  viewport: { width: number; height: number };
  placement: AnchorPlacement;
  align?: AnchorAlignment;
  /** Gap between anchor and surface, in px. */
  offset?: number;
  /** Minimum distance kept from the viewport edge, in px. */
  padding?: number;
}

export interface AnchorPosition {
  top: number;
  left: number;
  /** The placement actually used, after any collision flip. */
  placement: AnchorPlacement;
}

const OPPOSITE: Record<AnchorPlacement, AnchorPlacement> = {
  top: 'bottom',
  bottom: 'top',
  left: 'right',
  right: 'left',
};

function spaceFor(
  placement: AnchorPlacement,
  anchor: AnchorRect,
  viewport: { width: number; height: number },
): number {
  switch (placement) {
    case 'top':
      return anchor.top;
    case 'bottom':
      return viewport.height - (anchor.top + anchor.height);
    case 'left':
      return anchor.left;
    case 'right':
      return viewport.width - (anchor.left + anchor.width);
  }
}

function clamp(value: number, min: number, max: number): number {
  if (max < min) return min;
  return Math.min(Math.max(value, min), max);
}

/**
 * Pure anchored placement with a single collision flip. Deliberately smaller than a
 * floating-ui dependency: the Research Harness surfaces are anchored menus, popovers and
 * tooltips, none of which need arrow positioning, virtual elements or auto-placement.
 * Coordinates are viewport coordinates, for use with `position: fixed`.
 */
export function computeAnchorPosition({
  anchor,
  floating,
  viewport,
  placement,
  align = 'center',
  offset = 8,
  padding = 8,
}: ComputeAnchorPositionInput): AnchorPosition {
  const needed = placement === 'top' || placement === 'bottom' ? floating.height : floating.width;
  const opposite = OPPOSITE[placement];
  const fits = spaceFor(placement, anchor, viewport) >= needed + offset + padding;
  const oppositeFitsBetter =
    !fits && spaceFor(opposite, anchor, viewport) > spaceFor(placement, anchor, viewport);
  const resolved = oppositeFitsBetter ? opposite : placement;

  let top = 0;
  let left = 0;

  if (resolved === 'top' || resolved === 'bottom') {
    top = resolved === 'top' ? anchor.top - floating.height - offset : anchor.top + anchor.height + offset;
    const alignedLeft =
      align === 'start'
        ? anchor.left
        : align === 'end'
          ? anchor.left + anchor.width - floating.width
          : anchor.left + anchor.width / 2 - floating.width / 2;
    left = clamp(alignedLeft, padding, viewport.width - floating.width - padding);
  } else {
    left = resolved === 'left' ? anchor.left - floating.width - offset : anchor.left + anchor.width + offset;
    const alignedTop =
      align === 'start'
        ? anchor.top
        : align === 'end'
          ? anchor.top + anchor.height - floating.height
          : anchor.top + anchor.height / 2 - floating.height / 2;
    top = clamp(alignedTop, padding, viewport.height - floating.height - padding);
  }

  return { top: Math.round(top), left: Math.round(left), placement: resolved };
}

export interface UseAnchorPositionOptions {
  anchorRef: RefObject<HTMLElement | null>;
  floatingRef: RefObject<HTMLElement | null>;
  placement?: AnchorPlacement | undefined;
  align?: AnchorAlignment | undefined;
  offset?: number | undefined;
  padding?: number | undefined;
  /** Only measures and listens while true. */
  enabled: boolean;
}

export interface UseAnchorPositionResult {
  style: CSSProperties;
  placement: AnchorPlacement;
  /** Force a re-measure (after content changes size, for example). */
  update: () => void;
}

/**
 * Positions a portalled surface against its anchor and keeps it there across scroll and
 * resize. In environments without layout (jsdom, SSR) every rect is zero, which yields a
 * stable top-left position rather than an error.
 */
export function useAnchorPosition({
  anchorRef,
  floatingRef,
  placement = 'bottom',
  align = 'center',
  offset = 8,
  padding = 8,
  enabled,
}: UseAnchorPositionOptions): UseAnchorPositionResult {
  const [position, setPosition] = useState<AnchorPosition>({ top: 0, left: 0, placement });
  const positionRef = useRef(position);
  positionRef.current = position;

  const update = useCallback((): void => {
    const anchor = anchorRef.current;
    const floating = floatingRef.current;
    if (!anchor || !floating || typeof window === 'undefined') return;
    const anchorBox = anchor.getBoundingClientRect();
    const floatingBox = floating.getBoundingClientRect();
    const next = computeAnchorPosition({
      anchor: {
        top: anchorBox.top,
        left: anchorBox.left,
        width: anchorBox.width,
        height: anchorBox.height,
      },
      floating: { width: floatingBox.width, height: floatingBox.height },
      viewport: {
        width: window.innerWidth || 0,
        height: window.innerHeight || 0,
      },
      placement,
      align,
      offset,
      padding,
    });
    const current = positionRef.current;
    if (
      current.top !== next.top ||
      current.left !== next.left ||
      current.placement !== next.placement
    ) {
      setPosition(next);
    }
  }, [align, anchorRef, floatingRef, offset, padding, placement]);

  useLayoutEffect(() => {
    if (!enabled) return;
    update();
  }, [enabled, update]);

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return;
    const onChange = (): void => update();
    window.addEventListener('scroll', onChange, true);
    window.addEventListener('resize', onChange);
    return () => {
      window.removeEventListener('scroll', onChange, true);
      window.removeEventListener('resize', onChange);
    };
  }, [enabled, update]);

  return {
    style: { position: 'fixed', top: position.top, left: position.left },
    placement: position.placement,
    update,
  };
}
