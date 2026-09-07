import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Tabs } from './Tabs';

function Example({
  orientation,
  activation,
  keepMounted,
  overflow,
  onValueChange,
}: {
  orientation?: 'horizontal' | 'vertical';
  activation?: 'automatic' | 'manual';
  keepMounted?: boolean;
  overflow?: 'scroll' | 'wrap';
  onValueChange?: (value: string) => void;
}) {
  return (
    <Tabs
      defaultValue="sources"
      orientation={orientation}
      activation={activation}
      keepMounted={keepMounted}
      onValueChange={onValueChange}
    >
      <Tabs.List aria-label="Inspector" overflow={overflow}>
        <Tabs.Tab value="sources">Sources</Tabs.Tab>
        <Tabs.Tab value="claims" disabled>
          Claims
        </Tabs.Tab>
        <Tabs.Tab value="context">Context</Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel value="sources">Source list</Tabs.Panel>
      <Tabs.Panel value="claims">Claim list</Tabs.Panel>
      <Tabs.Panel value="context">Context receipt</Tabs.Panel>
    </Tabs>
  );
}

describe('Tabs', () => {
  it('wires tabs to panels with the ARIA tabs pattern', () => {
    render(<Example />);
    const list = screen.getByRole('tablist');
    expect(list).toHaveAttribute('aria-orientation', 'horizontal');
    expect(list).toHaveAccessibleName('Inspector');

    const selected = screen.getByRole('tab', { name: 'Sources' });
    expect(selected).toHaveAttribute('aria-selected', 'true');
    expect(selected).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('tab', { name: 'Context' })).toHaveAttribute('tabindex', '-1');

    const panel = screen.getByRole('tabpanel');
    expect(panel).toHaveAttribute('aria-labelledby', selected.id);
    expect(selected).toHaveAttribute('aria-controls', panel.id);
    expect(screen.queryByText('Context receipt')).not.toBeInTheDocument();
  });

  it('moves focus with arrow keys, skips disabled tabs and activates automatically', async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(<Example onValueChange={onValueChange} />);

    await user.tab();
    expect(screen.getByRole('tab', { name: 'Sources' })).toHaveFocus();

    await user.keyboard('{ArrowRight}');
    // "Claims" is disabled, so focus lands on "Context" and selects it.
    expect(screen.getByRole('tab', { name: 'Context' })).toHaveFocus();
    expect(onValueChange).toHaveBeenLastCalledWith('context');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Context receipt');

    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Sources' })).toHaveFocus();

    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: 'Context' })).toHaveFocus();
    await user.keyboard('{Home}');
    expect(screen.getByRole('tab', { name: 'Sources' })).toHaveFocus();
  });

  it('waits for Enter or Space with manual activation', async () => {
    const user = userEvent.setup();
    render(<Example activation="manual" />);

    await user.tab();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Context' })).toHaveFocus();
    expect(screen.getByRole('tab', { name: 'Context' })).toHaveAttribute('aria-selected', 'false');

    await user.keyboard('{Enter}');
    expect(screen.getByRole('tab', { name: 'Context' })).toHaveAttribute('aria-selected', 'true');
  });

  it('uses the vertical axis when the orientation says so', async () => {
    const user = userEvent.setup();
    render(<Example orientation="vertical" />);
    expect(screen.getByRole('tablist')).toHaveAttribute('aria-orientation', 'vertical');

    await user.tab();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Sources' })).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('tab', { name: 'Context' })).toHaveFocus();
  });

  it('supports a controlled value', async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [value, setValue] = useState('sources');
      return (
        <>
          <span data-testid="value">{value}</span>
          <Tabs value={value} onValueChange={setValue}>
            <Tabs.List aria-label="Inspector">
              <Tabs.Tab value="sources">Sources</Tabs.Tab>
              <Tabs.Tab value="context">Context</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="sources">Source list</Tabs.Panel>
            <Tabs.Panel value="context">Context receipt</Tabs.Panel>
          </Tabs>
        </>
      );
    }
    render(<Controlled />);
    await user.click(screen.getByRole('tab', { name: 'Context' }));
    expect(screen.getByTestId('value')).toHaveTextContent('context');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Context receipt');
  });

  it('keeps panels mounted but hidden when asked', () => {
    render(<Example keepMounted />);
    const hidden = screen.getByText('Context receipt');
    expect(hidden).toBeInTheDocument();
    expect(hidden).toHaveAttribute('hidden');
  });

  /*
   * jsdom lays nothing out, so a strip narrower than its tabs has to be stated rather than
   * produced. The component reads exactly these three numbers, so defining them and firing
   * the scroll the browser would fire drives the same code path a 352px pane does.
   */
  function narrowStrip(
    list: HTMLElement,
    { scrollWidth = 734, clientWidth = 320, scrollLeft = 0 } = {},
  ): void {
    Object.defineProperty(list, 'scrollWidth', { configurable: true, value: scrollWidth });
    Object.defineProperty(list, 'clientWidth', { configurable: true, value: clientWidth });
    Object.defineProperty(list, 'scrollLeft', { configurable: true, writable: true, value: scrollLeft });
    fireEvent.scroll(list);
  }

  it('offers a way to reach the tabs a narrow strip cannot show', async () => {
    const user = userEvent.setup();
    const { container } = render(<Example />);
    const list = screen.getByRole('tablist');
    list.scrollBy = vi.fn();

    // Nothing overflows yet, so the strip carries no controls at all.
    expect(container.querySelector('.rh-tabs__scroll')).toBeNull();

    narrowStrip(list);
    const forward = container.querySelector('.rh-tabs__scroll--end');
    expect(forward).not.toBeNull();
    // Nothing is scrolled past yet, so only the trailing edge is offered.
    expect(container.querySelector('.rh-tabs__scroll--start')).toBeNull();
    expect(container.querySelector('.rh-tabs__strip')).toHaveAttribute('data-overflow', 'end');

    await user.click(forward as HTMLElement);
    expect(list.scrollBy).toHaveBeenCalledWith(
      expect.objectContaining({ left: expect.any(Number) }),
    );
    expect((list.scrollBy as ReturnType<typeof vi.fn>).mock.calls[0]?.[0].left).toBeGreaterThan(0);

    narrowStrip(list, { scrollLeft: 200 });
    expect(container.querySelector('.rh-tabs__scroll--start')).not.toBeNull();
    expect(container.querySelector('.rh-tabs__strip')).toHaveAttribute('data-overflow', 'both');
  });

  it('keeps the strip controls out of the tab order and out of the tablist', () => {
    const { container } = render(<Example />);
    const list = screen.getByRole('tablist');
    narrowStrip(list);

    const control = container.querySelector('.rh-tabs__scroll--end') as HTMLElement;
    // Arrow keys already reach every tab, so the pointer affordance is not a second
    // announcement of the same thing — and it must never sit inside the tablist.
    expect(control).toHaveAttribute('aria-hidden', 'true');
    expect(control).toHaveAttribute('tabindex', '-1');
    expect(list.contains(control)).toBe(false);
    expect(screen.getAllByRole('tab')).toHaveLength(3);
  });

  it('scrolls the tab the arrow keys reach into view', async () => {
    const user = userEvent.setup();
    render(<Example />);
    const list = screen.getByRole('tablist');
    narrowStrip(list);
    const target = screen.getByRole('tab', { name: 'Context' });
    target.scrollIntoView = vi.fn();

    await user.tab();
    await user.keyboard('{ArrowRight}');

    expect(target).toHaveFocus();
    expect(target.scrollIntoView).toHaveBeenCalled();
  });

  it('spends vertical room instead of scrolling when the host asks it to', () => {
    const { container } = render(<Example overflow="wrap" />);
    const list = screen.getByRole('tablist');
    narrowStrip(list);

    expect(list).toHaveAttribute('data-overflow', 'wrap');
    expect(container.querySelector('.rh-tabs__scroll')).toBeNull();
  });

  it('has no axe violations while the strip is scrolled', async () => {
    const { container } = render(<Example />);
    narrowStrip(screen.getByRole('tablist'), { scrollLeft: 120 });
    await expectNoAxeViolations(container);
  });

  it('has no axe violations', async () => {
    const { container } = render(<Example />);
    await expectNoAxeViolations(container);
  });

  describeThemeDensitySnapshots('Tabs', () => <Example />);
});
