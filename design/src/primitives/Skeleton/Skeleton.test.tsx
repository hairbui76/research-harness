import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Skeleton } from './Skeleton';

function stubMatchMedia(matches: boolean): void {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

describe('Skeleton', () => {
  afterEach(() => {
    Reflect.deleteProperty(window, 'matchMedia');
  });

  it('is hidden from assistive technology', () => {
    const { container } = render(<Skeleton width={200} height={12} />);
    const node = container.firstElementChild;
    expect(node).toHaveAttribute('aria-hidden', 'true');
    expect(node).toHaveStyle({ width: '200px', height: '12px' });
  });

  it('renders multiple text lines with a short last line', () => {
    const { container } = render(<Skeleton lines={3} />);
    const lines = container.querySelectorAll('.rh-skeleton');
    expect(lines).toHaveLength(3);
    expect(lines[2]).toHaveStyle({ width: '60%' });
  });

  it('renders one bar per requested width, in the order given', () => {
    const { container } = render(<Skeleton widths={['30%', 80, '10%']} />);
    const bars = container.querySelectorAll('.rh-skeleton');
    expect(bars).toHaveLength(3);
    expect(bars[0]).toHaveStyle({ width: '30%' });
    expect(bars[1]).toHaveStyle({ width: '80px' });
    // Explicit widths are exact: nothing is shortened the way the last text line is.
    expect(bars[2]).toHaveStyle({ width: '10%' });
  });

  it('lays a group out as a row when asked, and stacks it otherwise', () => {
    const { container, unmount } = render(<Skeleton direction="row" widths={['30%', '20%']} />);
    expect(container.firstElementChild).toHaveAttribute('data-direction', 'row');
    unmount();

    const stacked = render(<Skeleton lines={2} />);
    expect(stacked.container.firstElementChild).not.toHaveAttribute('data-direction');
  });

  it('hides a group from assistive technology, as it does a single bar', () => {
    const { container } = render(<Skeleton lines={3} />);
    expect(container.firstElementChild).toHaveAttribute('aria-hidden', 'true');
  });

  it('marks reduced motion when the user asks for it', () => {
    stubMatchMedia(true);
    const { container } = render(<Skeleton />);
    expect(container.firstElementChild).toHaveAttribute('data-motion', 'reduced');
  });

  it('animates when reduced motion is not requested', () => {
    stubMatchMedia(false);
    const { container } = render(<Skeleton />);
    expect(container.firstElementChild).toHaveAttribute('data-motion', 'full');
  });

  it('has no axe violations', async () => {
    const { container } = render(<Skeleton shape="block" />);
    await expectNoAxeViolations(container);
  });

  describeThemeDensitySnapshots('Skeleton', () => <Skeleton lines={2} />);
});
