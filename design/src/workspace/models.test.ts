import { describe, expect, it } from 'vitest';
import { mergePaneSizes, resolvePaneSizes } from './models';

describe('resolvePaneSizes', () => {
  it('scales the visible panes to 100', () => {
    const sizes = resolvePaneSizes({ rail: 18, centre: 54, inspector: 28 }, ['rail', 'centre']);
    expect(sizes.reduce((total, size) => total + size, 0)).toBeCloseTo(100);
    // The rail keeps its share of the two panes that are left.
    expect(sizes[0]).toBeCloseTo(25);
  });

  it('gives an unknown pane an even share of what is left', () => {
    const sizes = resolvePaneSizes({ rail: 20 }, ['rail', 'centre', 'inspector']);
    expect(sizes[0]).toBeCloseTo(20);
    expect(sizes[1]).toBeCloseTo(40);
    expect(sizes[2]).toBeCloseTo(40);
  });

  it('falls back per pane before splitting evenly', () => {
    const sizes = resolvePaneSizes({}, ['a', 'b'], { a: 30, b: 70 });
    expect(sizes).toEqual([30, 70]);
  });

  it('splits evenly when nothing is known', () => {
    expect(resolvePaneSizes({}, ['a', 'b', 'c'])).toEqual([100 / 3, 100 / 3, 100 / 3]);
    expect(resolvePaneSizes({}, [])).toEqual([]);
  });
});

describe('mergePaneSizes', () => {
  it('writes the visible panes back and leaves the hidden ones alone', () => {
    const merged = mergePaneSizes({ rail: 18, centre: 54, inspector: 28 }, ['rail', 'centre'], [30, 70]);
    expect(merged).toEqual({ rail: 30, centre: 70, inspector: 28 });
  });

  it('ignores a short array rather than writing undefined', () => {
    expect(mergePaneSizes({ a: 1, b: 2 }, ['a', 'b'], [50])).toEqual({ a: 50, b: 2 });
  });
});
