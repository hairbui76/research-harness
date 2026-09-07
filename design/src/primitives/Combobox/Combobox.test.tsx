import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Combobox } from './Combobox';
import type { ComboboxItem, ComboboxProps } from './Combobox';

const ITEMS: ComboboxItem<string>[] = [
  { id: 'c-12', label: 'Claim C-12', value: 'c-12', group: 'Claims', description: 'Contested' },
  { id: 'c-13', label: 'Claim C-13', value: 'c-13', group: 'Claims' },
  { id: 'e-4', label: 'Evidence E-4', value: 'e-4', group: 'Evidence' },
  { id: 'e-9', label: 'Evidence E-9', value: 'e-9', group: 'Evidence', disabled: true },
];

type ExampleProps = Partial<ComboboxProps<string>>;

/** The caller owns filtering, exactly as the primitive expects. */
function Example({ onQueryChange, ...props }: ExampleProps = {}) {
  const [query, setQuery] = useState('');
  const items = ITEMS.filter((item) => item.label.toLowerCase().includes(query.toLowerCase()));
  return (
    <Combobox<string>
      label="Insert reference"
      items={items}
      query={query}
      onQueryChange={(next) => {
        setQuery(next);
        onQueryChange?.(next);
      }}
      {...props}
    />
  );
}

describe('Combobox', () => {
  it('exposes the ARIA combobox pattern', async () => {
    const user = userEvent.setup();
    render(<Example />);
    const input = screen.getByRole('combobox', { name: 'Insert reference' });
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(input).toHaveAttribute('aria-autocomplete', 'list');

    await user.click(input);
    await user.keyboard('{ArrowDown}');
    const listbox = screen.getByRole('listbox', { name: 'Insert reference' });
    expect(input).toHaveAttribute('aria-expanded', 'true');
    expect(input).toHaveAttribute('aria-controls', listbox.id);
    expect(screen.getAllByRole('group')).toHaveLength(2);
    expect(screen.getByRole('group', { name: 'Claims' })).toBeInTheDocument();
  });

  it('tracks the active option with aria-activedescendant and selects with Enter', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Example onChange={onChange} />);
    const input = screen.getByRole('combobox');

    await user.click(input);
    await user.keyboard('{ArrowDown}');
    const first = screen.getByRole('option', { name: /Claim C-12/ });
    expect(input).toHaveAttribute('aria-activedescendant', first.id);

    await user.keyboard('{ArrowDown}');
    expect(input).toHaveAttribute(
      'aria-activedescendant',
      screen.getByRole('option', { name: 'Claim C-13' }).id,
    );

    await user.keyboard('{Enter}');
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'c-13' }));
    expect(input).toHaveValue('Claim C-13');
    expect(input).toHaveAttribute('aria-expanded', 'false');
  });

  it('skips disabled options when moving and wraps around', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole('combobox'));
    await user.keyboard('{ArrowUp}');
    // E-9 is disabled, so the last reachable option is E-4.
    expect(screen.getByRole('combobox')).toHaveAttribute(
      'aria-activedescendant',
      screen.getByRole('option', { name: 'Evidence E-4' }).id,
    );
  });

  it('reports typing and shows the caller-filtered items', async () => {
    const user = userEvent.setup();
    const onQueryChange = vi.fn();
    render(<Example onQueryChange={onQueryChange} />);
    await user.click(screen.getByRole('combobox'));
    await user.keyboard('E-4');
    expect(onQueryChange).toHaveBeenCalled();
    await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(1));
    expect(screen.getByRole('option', { name: 'Evidence E-4' })).toBeInTheDocument();
  });

  it('closes on Escape, then clears the query and selection on a second Escape', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Example onChange={onChange} />);
    const input = screen.getByRole('combobox');
    await user.click(input);
    await user.keyboard('Claim');
    expect(input).toHaveAttribute('aria-expanded', 'true');

    await user.keyboard('{Escape}');
    expect(input).toHaveAttribute('aria-expanded', 'false');
    expect(input).toHaveValue('Claim');

    await user.keyboard('{Escape}');
    expect(input).toHaveValue('');
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it('selects with the pointer without stealing focus from the text box', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Example onChange={onChange} openOnFocus />);
    const input = screen.getByRole('combobox');
    await user.click(input);
    await user.click(screen.getByRole('option', { name: /Claim C-12/ }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'c-12' }));
    expect(input).toHaveFocus();
  });

  it('shows loading and empty states', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <Combobox label="Insert reference" items={[]} loading defaultOpen />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Searching…');

    rerender(<Combobox label="Insert reference" items={[]} defaultOpen />);
    expect(screen.getByRole('status')).toHaveTextContent('No matches');
    await user.keyboard('{Escape}');
  });

  it('renders custom item content and clears the query when asked', async () => {
    const user = userEvent.setup();
    render(
      <Example
        selectionBehaviour="clear"
        renderItem={(item, state) => (
          <span>
            {item.label}
            {state.active ? ' (active)' : ''}
          </span>
        )}
      />,
    );
    const input = screen.getByRole('combobox');
    await user.click(input);
    await user.keyboard('{ArrowDown}{Enter}');
    expect(input).toHaveValue('');
  });

  /*
   * What is chosen is marked with an icon from the registry, the way a menu marks it.
   *
   * It used to be `content: ' ✓'` on the label's `::after` — a text glyph standing in for an
   * icon, which is the one thing the icon registry exists to prevent: it takes the font's
   * shape rather than the system's 2px stroke, it cannot be sized or coloured with the rest
   * of the iconography, and it is text, so it lands in the accessible name of the option
   * beside a redundant `aria-selected`. The stylesheet draws no glyph now; the sweep in
   * `tests/tokens.test.ts` is what holds every stylesheet to that.
   */
  it('marks the selected option with the registry’s check rather than a text glyph', () => {
    render(<Combobox<string> label="Insert reference" items={ITEMS} defaultValue="c-13" defaultOpen />);
    const chosen = screen.getByRole('option', { name: 'Claim C-13' });
    expect(chosen).toHaveAttribute('aria-selected', 'true');
    expect(chosen.querySelector('[data-icon="check"]')).not.toBeNull();
    expect(chosen).toHaveTextContent(/^Claim C-13$/);

    const other = screen.getByRole('option', { name: /Claim C-12/ });
    expect(other).toHaveAttribute('aria-selected', 'false');
    expect(other.querySelector('[data-icon="check"]')).toBeNull();
  });

  it('closes when the pointer presses outside', async () => {
    const user = userEvent.setup();
    render(
      <div>
        <Example openOnFocus />
        <button type="button">Elsewhere</button>
      </div>,
    );
    await user.click(screen.getByRole('combobox'));
    expect(screen.getByRole('combobox')).toHaveAttribute('aria-expanded', 'true');
    await user.click(screen.getByRole('button', { name: 'Elsewhere' }));
    await waitFor(() =>
      expect(screen.getByRole('combobox')).toHaveAttribute('aria-expanded', 'false'),
    );
  });

  it('takes its name from the host’s own label when one is pointed at', async () => {
    // A control above which the host draws a visible label should be named by that label,
    // not by a second string only assistive technology hears. `aria-labelledby` wins over
    // `aria-label` in the accessible-name computation, so leaving both on the box would
    // publish a name nothing on screen accounts for; the box drops its own instead.
    render(
      <>
        <label id="picker-label" htmlFor="picker">
          Read a field down its column
        </label>
        <Combobox<string> id="picker" aria-labelledby="picker-label" label="Fallback" items={ITEMS} />
      </>,
    );
    const box = screen.getByRole('combobox', { name: 'Read a field down its column' });
    expect(box).not.toHaveAttribute('aria-label');
    // The list still carries a name of its own: it is a separate element and the host's
    // label points at the text box.
    expect(box).toHaveAttribute('aria-labelledby', 'picker-label');
  });

  it('has no axe violations while open', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole('combobox'));
    await user.keyboard('{ArrowDown}');
    await expectNoAxeViolations(document.body);
  });

  // One option is chosen, so the snapshot records the check the list draws on it.
  describeThemeDensitySnapshots('Combobox', () => (
    <Combobox<string> label="Insert reference" items={ITEMS} defaultValue="c-13" defaultOpen />
  ));
});
