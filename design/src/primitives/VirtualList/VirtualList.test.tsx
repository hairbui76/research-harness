import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { VirtualList } from './VirtualList';
import type { VirtualListHandle } from './VirtualList';

interface Row {
  id: string;
  text: string;
}

const ROWS: Row[] = Array.from({ length: 200 }, (_unused, index) => ({
  id: `m-${index}`,
  text: `Message ${index}`,
}));

function List(props: Partial<React.ComponentProps<typeof VirtualList<Row>>> = {}) {
  return (
    <VirtualList<Row>
      label="Transcript"
      items={ROWS}
      itemKey={(item) => item.id}
      renderItem={(item) => <p>{item.text}</p>}
      estimatedItemHeight={40}
      overscan={2}
      height={200}
      {...props}
    />
  );
}

describe('VirtualList', () => {
  it('renders only the window around the scroll position', () => {
    render(<List />);
    const list = screen.getByRole('list', { name: 'Transcript' });
    expect(list).toHaveAttribute('tabindex', '0');
    // 200px viewport / 40px rows plus overscan on both sides, not 200 rows.
    const rendered = screen.getAllByRole('listitem');
    expect(rendered.length).toBeLessThan(15);
    expect(screen.getByText('Message 0')).toBeInTheDocument();
    expect(screen.queryByText('Message 100')).not.toBeInTheDocument();
  });

  it('tells assistive technology where each rendered item sits in the whole list', () => {
    render(<List />);
    const first = screen.getAllByRole('listitem')[0] as HTMLElement;
    expect(first).toHaveAttribute('aria-setsize', '200');
    expect(first).toHaveAttribute('aria-posinset', '1');
  });

  it('sizes the scroll area for every item', () => {
    const { container } = render(<List />);
    const sizer = container.querySelector('.rh-virtual-list__sizer') as HTMLElement;
    expect(sizer.style.height).toBe('8000px');
  });

  it('follows the scroll position', () => {
    render(<List />);
    const list = screen.getByRole('list');
    fireEvent.scroll(list, { target: { scrollTop: 4000 } });
    expect(screen.getByText('Message 100')).toBeInTheDocument();
    expect(screen.queryByText('Message 0')).not.toBeInTheDocument();
  });

  it('scrolls from the keyboard', async () => {
    const user = userEvent.setup();
    render(<List />);
    const list = screen.getByRole('list');
    await user.tab();
    expect(list).toHaveFocus();

    await user.keyboard('{End}');
    expect(screen.getByText('Message 199')).toBeInTheDocument();
    await user.keyboard('{Home}');
    expect(screen.getByText('Message 0')).toBeInTheDocument();
    await user.keyboard('{PageDown}');
    expect(screen.queryByText('Message 0')).not.toBeInTheDocument();
    await user.keyboard('{PageUp}');
    expect(screen.getByText('Message 0')).toBeInTheDocument();
  });

  it('exposes scrollToIndex and the visible range', () => {
    const ref = createRef<VirtualListHandle>();
    const onVisibleRangeChange = vi.fn();
    render(
      <VirtualList<Row>
        ref={ref}
        label="Transcript"
        items={ROWS}
        itemKey={(item) => item.id}
        renderItem={(item) => <p>{item.text}</p>}
        estimatedItemHeight={40}
        overscan={2}
        height={200}
        onVisibleRangeChange={onVisibleRangeChange}
      />,
    );

    act(() => ref.current?.scrollToIndex(120, 'start'));
    expect(screen.getByText('Message 120')).toBeInTheDocument();
    const range = ref.current?.getVisibleRange();
    expect(range?.start).toBeLessThanOrEqual(120);
    expect(range?.end).toBeGreaterThan(120);
    expect(onVisibleRangeChange).toHaveBeenCalled();
  });

  it('uses measured heights when the environment provides them', () => {
    const original = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.dataset.rhKey !== undefined ? 80 : 0;
      },
    });
    try {
      const { container } = render(<List />);
      const sizer = container.querySelector('.rh-virtual-list__sizer') as HTMLElement;
      // Measured rows are 80px, so the total exceeds the 40px estimate for those rows.
      expect(Number.parseFloat(sizer.style.height)).toBeGreaterThan(8000);
    } finally {
      if (original) Object.defineProperty(HTMLElement.prototype, 'offsetHeight', original);
    }
  });

  it('renders a grid with row indices when asked', () => {
    render(
      <List
        role="grid"
        renderItem={(item) => <span role="gridcell">{item.text}</span>}
      />,
    );
    const grid = screen.getByRole('grid', { name: 'Transcript' });
    expect(grid).toHaveAttribute('aria-rowcount', '200');
    expect(screen.getAllByRole('row')[0]).toHaveAttribute('aria-rowindex', '1');
  });

  it('handles an empty list', () => {
    render(<List items={[]} />);
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
  });

  it('has no axe violations', async () => {
    const { container } = render(<List />);
    await expectNoAxeViolations(container);
  });

  describeThemeDensitySnapshots('VirtualList', () => (
    <List items={ROWS.slice(0, 3)} height={120} />
  ));
});
