import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Input } from './Input';

describe('Input', () => {
  it('associates the label with the control', () => {
    render(<Input label="Project title" />);
    expect(screen.getByLabelText('Project title')).toHaveClass('rh-control');
  });

  it('respects a caller-supplied id', () => {
    render(<Input id="title" label="Project title" />);
    expect(screen.getByLabelText('Project title')).toHaveAttribute('id', 'title');
  });

  it('links description and error through aria-describedby', () => {
    render(<Input label="Title" description="Shown in the rail." error="Title is required." />);
    const input = screen.getByLabelText('Title');
    const describedBy = input.getAttribute('aria-describedby')?.split(' ') ?? [];
    expect(describedBy).toHaveLength(2);
    for (const id of describedBy) {
      expect(document.getElementById(id)).not.toBeNull();
    }
    expect(screen.getByText('Shown in the rail.')).toBeInTheDocument();
    expect(screen.getByText('Title is required.')).toBeInTheDocument();
  });

  it('omits aria-describedby when there is nothing to describe', () => {
    render(<Input label="Title" />);
    expect(screen.getByLabelText('Title')).not.toHaveAttribute('aria-describedby');
  });

  it('marks itself invalid from either an error or the invalid flag', () => {
    const { rerender } = render(<Input label="Title" error="Required" />);
    expect(screen.getByLabelText('Title')).toHaveAttribute('aria-invalid', 'true');
    rerender(<Input label="Title" invalid />);
    expect(screen.getByLabelText('Title')).toHaveAttribute('aria-invalid', 'true');
    rerender(<Input label="Title" />);
    expect(screen.getByLabelText('Title')).not.toHaveAttribute('aria-invalid');
  });

  it('pairs the error text with a glyph, so it is not red text alone', () => {
    const { container } = render(<Input label="Title" error="Required" />);
    expect(container.querySelector('.rh-field__error svg')).toHaveAttribute(
      'data-icon',
      'alert-circle',
    );
  });

  it('shows a required marker and sets the required attribute', () => {
    const { container } = render(<Input label="Title" required />);
    expect(screen.getByLabelText(/Title/)).toBeRequired();
    expect(container.querySelector('.rh-field__required')).toHaveAttribute('aria-hidden', 'true');
  });

  it('types in the uncontrolled case', async () => {
    const user = userEvent.setup();
    render(<Input label="Title" defaultValue="Traffic" />);
    const input = screen.getByLabelText('Title');
    await user.type(input, ' study');
    expect(input).toHaveValue('Traffic study');
  });

  it('stays controlled when the parent owns the value', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Input label="Title" value="fixed" onChange={onChange} />);
    const input = screen.getByLabelText('Title');
    await user.type(input, 'x');
    expect(input).toHaveValue('fixed');
    expect(onChange).toHaveBeenCalled();
  });

  it('round-trips through a controlled parent', async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [value, setValue] = useState('');
      return <Input label="Title" value={value} onChange={(e) => setValue(e.target.value)} />;
    }
    render(<Controlled />);
    await user.type(screen.getByLabelText('Title'), 'hello');
    expect(screen.getByLabelText('Title')).toHaveValue('hello');
  });

  it('does not accept input while disabled', async () => {
    const user = userEvent.setup();
    render(<Input label="Title" disabled />);
    const input = screen.getByLabelText('Title');
    await user.type(input, 'nope');
    expect(input).toBeDisabled();
    expect(input).toHaveValue('');
  });

  it('renders a decorative leading icon', () => {
    const { container } = render(<Input label="Search" iconStart="search" />);
    const icon = container.querySelector('.rh-input__icon');
    expect(icon).toHaveAttribute('data-icon', 'search');
    expect(icon).toHaveAttribute('aria-hidden', 'true');
  });

  it('keeps the label available to assistive technology when hidden', () => {
    const { container } = render(<Input label="Search corpus" hideLabel />);
    expect(screen.getByLabelText('Search corpus')).toBeInTheDocument();
    expect(container.querySelector('.rh-field__label')).toHaveClass('rh-visually-hidden');
  });

  it('forwards a ref to the input', () => {
    const ref = createRef<HTMLInputElement>();
    render(<Input label="Title" ref={ref} />);
    expect(ref.current).toBe(screen.getByLabelText('Title'));
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        <Input label="Title" description="Shown in the rail." required />
        <Input label="Doi" error="Not a valid DOI." />
        <Input label="Disabled" disabled />
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('Input', () => (
  <div>
    <Input id="snap-title" label="Title" description="Shown in the rail." required />
    <Input id="snap-doi" label="DOI" error="Not a valid DOI." />
    <Input id="snap-search" label="Search" iconStart="search" size="sm" hideLabel />
    <Input id="snap-locked" label="Locked" disabled defaultValue="read only" />
  </div>
));
