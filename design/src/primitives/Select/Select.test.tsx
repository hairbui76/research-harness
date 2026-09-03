import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Select } from './Select';

const options = (
  <>
    <option value="local">Local model</option>
    <option value="hosted">Hosted model</option>
  </>
);

describe('Select', () => {
  it('renders a native select with its options', () => {
    render(<Select label="Model">{options}</Select>);
    const select = screen.getByLabelText('Model');
    expect(select.tagName.toLowerCase()).toBe('select');
    expect(screen.getAllByRole('option')).toHaveLength(2);
  });

  it('draws a decorative chevron', () => {
    const { container } = render(<Select label="Model">{options}</Select>);
    const chevron = container.querySelector('.rh-select__chevron');
    expect(chevron).toHaveAttribute('data-icon', 'chevron-down');
    expect(chevron).toHaveAttribute('aria-hidden', 'true');
  });

  it('selects in the uncontrolled case', async () => {
    const user = userEvent.setup();
    render(
      <Select label="Model" defaultValue="local">
        {options}
      </Select>,
    );
    const select = screen.getByLabelText('Model');
    await user.selectOptions(select, 'hosted');
    expect(select).toHaveValue('hosted');
  });

  it('stays controlled when the parent owns the value', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Select label="Model" value="local" onChange={onChange}>
        {options}
      </Select>,
    );
    const select = screen.getByLabelText('Model');
    await user.selectOptions(select, 'hosted');
    expect(select).toHaveValue('local');
    expect(onChange).toHaveBeenCalled();
  });

  it('round-trips through a controlled parent', async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [value, setValue] = useState('local');
      return (
        <Select label="Model" value={value} onChange={(e) => setValue(e.target.value)}>
          {options}
        </Select>
      );
    }
    render(<Controlled />);
    await user.selectOptions(screen.getByLabelText('Model'), 'hosted');
    expect(screen.getByLabelText('Model')).toHaveValue('hosted');
  });

  it('is keyboard reachable', async () => {
    const user = userEvent.setup();
    render(<Select label="Model">{options}</Select>);
    await user.tab();
    expect(screen.getByLabelText('Model')).toHaveFocus();
  });

  it('links description and error and marks itself invalid', () => {
    render(
      <Select label="Model" description="Used for the next send." error="Unavailable offline.">
        {options}
      </Select>,
    );
    const select = screen.getByLabelText('Model');
    expect(select).toHaveAttribute('aria-invalid', 'true');
    expect(select.getAttribute('aria-describedby')?.split(' ')).toHaveLength(2);
  });

  it('is inert while disabled', () => {
    render(
      <Select label="Model" disabled>
        {options}
      </Select>,
    );
    expect(screen.getByLabelText('Model')).toBeDisabled();
  });

  it('forwards a ref', () => {
    const ref = createRef<HTMLSelectElement>();
    render(
      <Select label="Model" ref={ref}>
        {options}
      </Select>,
    );
    expect(ref.current).toBe(screen.getByLabelText('Model'));
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        <Select label="Model" description="Used for the next send.">
          {options}
        </Select>
        <Select label="Fallback" error="Unavailable offline.">
          {options}
        </Select>
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('Select', () => (
  <div>
    <Select id="snap-model" label="Model" description="Used for the next send.">
      {options}
    </Select>
    <Select id="snap-fallback" label="Fallback" size="sm" error="Unavailable offline.">
      {options}
    </Select>
  </div>
));
