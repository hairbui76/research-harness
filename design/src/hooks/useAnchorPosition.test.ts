import { describe, expect, it } from 'vitest';
import { computeAnchorPosition } from './useAnchorPosition';

const viewport = { width: 1000, height: 800 };
const anchor = { top: 400, left: 400, width: 100, height: 40 };
const floating = { width: 200, height: 100 };

describe('computeAnchorPosition', () => {
  it('places the surface on the requested side with the offset applied', () => {
    expect(computeAnchorPosition({ anchor, floating, viewport, placement: 'bottom', offset: 8 })).toEqual({
      top: 448,
      left: 350,
      placement: 'bottom',
    });
    expect(computeAnchorPosition({ anchor, floating, viewport, placement: 'top', offset: 8 })).toEqual({
      top: 292,
      left: 350,
      placement: 'top',
    });
    expect(computeAnchorPosition({ anchor, floating, viewport, placement: 'right', offset: 8 })).toEqual({
      top: 370,
      left: 508,
      placement: 'right',
    });
  });

  it('aligns to the start and the end along the cross axis', () => {
    expect(
      computeAnchorPosition({ anchor, floating, viewport, placement: 'bottom', align: 'start' }).left,
    ).toBe(400);
    expect(
      computeAnchorPosition({ anchor, floating, viewport, placement: 'bottom', align: 'end' }).left,
    ).toBe(300);
  });

  it('flips to the opposite side when the preferred one has no room', () => {
    const nearTop = { top: 10, left: 400, width: 100, height: 40 };
    const result = computeAnchorPosition({
      anchor: nearTop,
      floating,
      viewport,
      placement: 'top',
    });
    expect(result.placement).toBe('bottom');
    expect(result.top).toBe(58);
  });

  it('keeps the requested side when neither side fits but it has more room', () => {
    const tall = { width: 200, height: 700 };
    const result = computeAnchorPosition({
      anchor: { top: 600, left: 400, width: 100, height: 40 },
      floating: tall,
      viewport,
      placement: 'top',
    });
    expect(result.placement).toBe('top');
  });

  it('clamps the cross axis inside the viewport padding', () => {
    const atEdge = { top: 400, left: 0, width: 40, height: 40 };
    const result = computeAnchorPosition({
      anchor: atEdge,
      floating,
      viewport,
      placement: 'bottom',
      padding: 8,
    });
    expect(result.left).toBe(8);
  });
});
