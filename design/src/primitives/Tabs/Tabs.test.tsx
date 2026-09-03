import { render, screen } from '@testing-library/react';
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
  onValueChange,
}: {
  orientation?: 'horizontal' | 'vertical';
  activation?: 'automatic' | 'manual';
  keepMounted?: boolean;
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
      <Tabs.List aria-label="Inspector">
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

  it('has no axe violations', async () => {
    const { container } = render(<Example />);
    await expectNoAxeViolations(container);
  });

  describeThemeDensitySnapshots('Tabs', () => <Example />);
});
