import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Radio, RadioGroup } from './Radio';

function Group(props: { value?: string | null; onValueChange?: (value: string) => void }) {
  return (
    <RadioGroup label="Promote as" defaultValue="note" {...props}>
      <Radio value="note" label="Note" />
      <Radio value="question" label="Question" />
      <Radio value="claim" label="Claim candidate" />
    </RadioGroup>
  );
}

describe('RadioGroup', () => {
  it('exposes a labelled radiogroup', () => {
    render(<Group />);
    expect(screen.getByRole('radiogroup', { name: 'Promote as' })).toBeInTheDocument();
    expect(screen.getAllByRole('radio')).toHaveLength(3);
  });

  it('gives every radio the same generated name', () => {
    render(<Group />);
    const names = screen.getAllByRole('radio').map((r) => (r as HTMLInputElement).name);
    expect(new Set(names).size).toBe(1);
    expect(names[0]).not.toBe('');
  });

  it('selects on its own from a default value', async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(<Group onValueChange={onValueChange} />);
    expect(screen.getByRole('radio', { name: 'Note' })).toBeChecked();
    await user.click(screen.getByRole('radio', { name: 'Question' }));
    expect(screen.getByRole('radio', { name: 'Question' })).toBeChecked();
    expect(onValueChange).toHaveBeenCalledWith('question');
  });

  it('obeys the parent when controlled', async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(<Group value="note" onValueChange={onValueChange} />);
    await user.click(screen.getByRole('radio', { name: 'Claim candidate' }));
    expect(screen.getByRole('radio', { name: 'Note' })).toBeChecked();
    expect(onValueChange).toHaveBeenCalledWith('claim');
  });

  it('supports a controlled group with nothing chosen yet', () => {
    render(<Group value={null} />);
    for (const radio of screen.getAllByRole('radio')) expect(radio).not.toBeChecked();
  });

  it('round-trips through a controlled parent', async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [value, setValue] = useState<string | null>(null);
      return <Group value={value} onValueChange={setValue} />;
    }
    render(<Controlled />);
    await user.click(screen.getByRole('radio', { name: 'Question' }));
    expect(screen.getByRole('radio', { name: 'Question' })).toBeChecked();
  });

  it('moves the selection with the arrow keys', async () => {
    const user = userEvent.setup();
    render(<Group />);
    await user.tab();
    expect(screen.getByRole('radio', { name: 'Note' })).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('radio', { name: 'Question' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Question' })).toHaveFocus();
  });

  it('disables every radio when the group is disabled', async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <RadioGroup label="Promote as" disabled onValueChange={onValueChange}>
        <Radio value="note" label="Note" />
        <Radio value="question" label="Question" />
      </RadioGroup>,
    );
    for (const radio of screen.getAllByRole('radio')) expect(radio).toBeDisabled();
    await user.click(screen.getByRole('radio', { name: 'Note' }));
    expect(onValueChange).not.toHaveBeenCalled();
  });

  it('links an error to the group', () => {
    render(
      <RadioGroup label="Promote as" error="Choose a destination.">
        <Radio value="note" label="Note" />
      </RadioGroup>,
    );
    const group = screen.getByRole('radiogroup');
    expect(group).toHaveAttribute('aria-invalid', 'true');
    const id = group.getAttribute('aria-describedby');
    expect(document.getElementById(id as string)).toHaveTextContent('Choose a destination.');
  });

  it('works standalone, outside a group', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Radio name="solo" value="only" label="Only option" onChange={onChange} />);
    await user.click(screen.getByRole('radio'));
    expect(onChange).toHaveBeenCalled();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<Group />);
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('RadioGroup', () => (
  <RadioGroup label="Promote as" name="snap-promote" defaultValue="note">
    <Radio id="snap-note" value="note" label="Note" description="Working context only." />
    <Radio id="snap-question" value="question" label="Question" />
    <Radio id="snap-claim" value="claim" label="Claim candidate" disabled />
  </RadioGroup>
));
