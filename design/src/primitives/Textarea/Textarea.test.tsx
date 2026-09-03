import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef, useState } from 'react';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Textarea } from './Textarea';

describe('Textarea', () => {
  it('associates the label and defaults to three rows', () => {
    render(<Textarea label="Prompt" />);
    const control = screen.getByLabelText('Prompt');
    expect(control.tagName.toLowerCase()).toBe('textarea');
    expect(control).toHaveAttribute('rows', '3');
  });

  it('links description and error and marks itself invalid', () => {
    render(<Textarea label="Prompt" description="Shift+Enter for a newline." error="Too long." />);
    const control = screen.getByLabelText('Prompt');
    expect(control).toHaveAttribute('aria-invalid', 'true');
    const ids = control.getAttribute('aria-describedby')?.split(' ') ?? [];
    expect(ids).toHaveLength(2);
    for (const id of ids) expect(document.getElementById(id)).not.toBeNull();
  });

  it('types in the uncontrolled case', async () => {
    const user = userEvent.setup();
    render(<Textarea label="Prompt" defaultValue="Why" />);
    await user.type(screen.getByLabelText('Prompt'), ' now');
    expect(screen.getByLabelText('Prompt')).toHaveValue('Why now');
  });

  it('round-trips through a controlled parent', async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [value, setValue] = useState('');
      return <Textarea label="Prompt" value={value} onChange={(e) => setValue(e.target.value)} />;
    }
    render(<Controlled />);
    await user.type(screen.getByLabelText('Prompt'), 'hello');
    expect(screen.getByLabelText('Prompt')).toHaveValue('hello');
  });

  it('never resizes horizontally', () => {
    const { rerender } = render(<Textarea label="Prompt" />);
    expect(screen.getByLabelText('Prompt')).toHaveClass('rh-textarea--resize-vertical');
    rerender(<Textarea label="Prompt" resize="none" />);
    expect(screen.getByLabelText('Prompt')).toHaveClass('rh-textarea--resize-none');
  });

  it('does not accept input while disabled', async () => {
    const user = userEvent.setup();
    render(<Textarea label="Prompt" disabled />);
    await user.type(screen.getByLabelText('Prompt'), 'nope');
    expect(screen.getByLabelText('Prompt')).toHaveValue('');
  });

  it('forwards a ref', () => {
    const ref = createRef<HTMLTextAreaElement>();
    render(<Textarea label="Prompt" ref={ref} />);
    expect(ref.current).toBe(screen.getByLabelText('Prompt'));
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        <Textarea label="Prompt" description="Shift+Enter for a newline." required />
        <Textarea label="Notes" error="Too long." />
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('Textarea', () => (
  <div>
    <Textarea id="snap-prompt" label="Prompt" description="Shift+Enter for a newline." rows={2} />
    <Textarea id="snap-notes" label="Notes" error="Too long." rows={2} />
  </div>
));
