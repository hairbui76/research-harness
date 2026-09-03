import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Checkbox } from './Checkbox';

describe('Checkbox', () => {
  it('associates the label with the input', () => {
    render(<Checkbox label="Include prior sessions" />);
    expect(screen.getByRole('checkbox', { name: 'Include prior sessions' })).toBeInTheDocument();
  });

  it('toggles on its own when uncontrolled', async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(<Checkbox label="Include" onCheckedChange={onCheckedChange} />);
    const box = screen.getByRole('checkbox');
    expect(box).not.toBeChecked();
    await user.click(box);
    expect(box).toBeChecked();
    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });

  it('starts from defaultChecked', () => {
    render(<Checkbox label="Include" defaultChecked />);
    expect(screen.getByRole('checkbox')).toBeChecked();
  });

  it('obeys the parent when controlled', async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    const { rerender } = render(
      <Checkbox label="Include" checked={false} onCheckedChange={onCheckedChange} />,
    );
    await user.click(screen.getByRole('checkbox'));
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(onCheckedChange).toHaveBeenCalledWith(true);
    rerender(<Checkbox label="Include" checked onCheckedChange={onCheckedChange} />);
    expect(screen.getByRole('checkbox')).toBeChecked();
  });

  it('toggles with the Space key', async () => {
    const user = userEvent.setup();
    render(<Checkbox label="Include" />);
    await user.tab();
    expect(screen.getByRole('checkbox')).toHaveFocus();
    await user.keyboard(' ');
    expect(screen.getByRole('checkbox')).toBeChecked();
  });

  it('toggles when the label is clicked', async () => {
    const user = userEvent.setup();
    render(<Checkbox label="Include prior sessions" />);
    await user.click(screen.getByText('Include prior sessions'));
    expect(screen.getByRole('checkbox')).toBeChecked();
  });

  it('sets the indeterminate DOM property and its glyph', () => {
    const { container } = render(<Checkbox label="All" indeterminate />);
    expect((screen.getByRole('checkbox') as HTMLInputElement).indeterminate).toBe(true);
    expect(container.querySelector('.rh-checkbox__box svg')).toHaveAttribute('data-icon', 'minus');
  });

  it('does not toggle while disabled', async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(<Checkbox label="Include" disabled onCheckedChange={onCheckedChange} />);
    await user.click(screen.getByRole('checkbox'));
    expect(onCheckedChange).not.toHaveBeenCalled();
    expect(screen.getByRole('checkbox')).toBeDisabled();
  });

  it('reports an error state through aria-invalid and a described error line', () => {
    render(<Checkbox label="Agree" error="You must agree to continue." />);
    const box = screen.getByRole('checkbox');
    expect(box).toHaveAttribute('aria-invalid', 'true');
    const ids = box.getAttribute('aria-describedby')?.split(' ') ?? [];
    expect(ids).toHaveLength(1);
    expect(document.getElementById(ids[0] as string)).toHaveTextContent(
      'You must agree to continue.',
    );
  });

  it('forwards a ref while still owning the indeterminate property', () => {
    const ref = createRef<HTMLInputElement>();
    render(<Checkbox label="All" ref={ref} indeterminate />);
    expect(ref.current).toBe(screen.getByRole('checkbox'));
    expect(ref.current?.indeterminate).toBe(true);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        <Checkbox label="Include prior sessions" description="Adds relevance-selected excerpts." />
        <Checkbox label="Agree" error="You must agree to continue." />
        <Checkbox label="Locked" disabled />
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('Checkbox', () => (
  <div>
    <Checkbox
      id="snap-include"
      label="Include prior sessions"
      description="Adds relevance-selected excerpts."
      defaultChecked
    />
    <Checkbox id="snap-all" label="All works" indeterminate />
    <Checkbox id="snap-agree" label="Agree" error="You must agree to continue." />
    <Checkbox id="snap-locked" label="Locked" disabled />
  </div>
));
