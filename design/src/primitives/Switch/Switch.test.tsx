import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Switch } from './Switch';

describe('Switch', () => {
  it('exposes a labelled switch role', () => {
    render(<Switch label="Light theme" />);
    expect(screen.getByRole('switch', { name: 'Light theme' })).toBeInTheDocument();
  });

  it('toggles on its own when uncontrolled', async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(<Switch label="Light theme" onCheckedChange={onCheckedChange} />);
    const control = screen.getByRole('switch');
    await user.click(control);
    expect(control).toBeChecked();
    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });

  it('starts from defaultChecked', () => {
    render(<Switch label="Light theme" defaultChecked />);
    expect(screen.getByRole('switch')).toBeChecked();
  });

  it('obeys the parent when controlled', async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(<Switch label="Light theme" checked={false} onCheckedChange={onCheckedChange} />);
    await user.click(screen.getByRole('switch'));
    expect(screen.getByRole('switch')).not.toBeChecked();
    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });

  it('round-trips through a controlled parent', async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [on, setOn] = useState(false);
      return <Switch label="Light theme" checked={on} onCheckedChange={setOn} />;
    }
    render(<Controlled />);
    await user.click(screen.getByRole('switch'));
    expect(screen.getByRole('switch')).toBeChecked();
  });

  it('toggles with the Space key', async () => {
    const user = userEvent.setup();
    render(<Switch label="Light theme" />);
    await user.tab();
    expect(screen.getByRole('switch')).toHaveFocus();
    await user.keyboard(' ');
    expect(screen.getByRole('switch')).toBeChecked();
  });

  it('does not toggle while disabled', async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    render(<Switch label="Light theme" disabled onCheckedChange={onCheckedChange} />);
    await user.click(screen.getByRole('switch'));
    expect(onCheckedChange).not.toHaveBeenCalled();
    expect(screen.getByRole('switch')).toBeDisabled();
  });

  it('links a description', () => {
    render(<Switch label="Light theme" description="Stored on this machine only." />);
    const control = screen.getByRole('switch');
    const id = control.getAttribute('aria-describedby');
    expect(document.getElementById(id as string)).toHaveTextContent(
      'Stored on this machine only.',
    );
  });

  it('forwards a ref', () => {
    const ref = createRef<HTMLInputElement>();
    render(<Switch label="Light theme" ref={ref} />);
    expect(ref.current).toBe(screen.getByRole('switch'));
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        <Switch label="Light theme" description="Stored on this machine only." />
        <Switch label="Compact density" defaultChecked />
        <Switch label="Locked" disabled />
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('Switch', () => (
  <div>
    <Switch id="snap-theme" label="Light theme" description="Stored on this machine only." />
    <Switch id="snap-density" label="Compact density" defaultChecked />
    <Switch id="snap-locked" label="Locked" disabled />
  </div>
));
