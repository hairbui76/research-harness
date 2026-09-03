import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { IconButton } from './IconButton';

describe('IconButton', () => {
  it('takes its accessible name from the required label', () => {
    render(<IconButton icon="x" label="Close inspector" />);
    expect(screen.getByRole('button', { name: 'Close inspector' })).toBeInTheDocument();
  });

  it('hides the glyph from assistive technology', () => {
    const { container } = render(<IconButton icon="settings" label="Settings" />);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('activates from the keyboard', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<IconButton icon="send" label="Send" onClick={onClick} />);
    await user.tab();
    expect(screen.getByRole('button')).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('is inert while disabled or loading', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    const { rerender } = render(
      <IconButton icon="send" label="Send" disabled onClick={onClick} />,
    );
    await user.click(screen.getByRole('button'));
    expect(onClick).not.toHaveBeenCalled();

    rerender(<IconButton icon="send" label="Send" loading onClick={onClick} />);
    const button = screen.getByRole('button');
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(button.querySelector('svg')).toHaveAttribute('data-icon', 'loader');
  });

  it('forwards refs and extra classes', () => {
    const ref = createRef<HTMLButtonElement>();
    render(<IconButton ref={ref} icon="copy" label="Copy id" className="pinned" />);
    expect(ref.current).toHaveClass('rh-icon-button', 'pinned');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        <IconButton icon="panel-left" label="Collapse the rail" />
        <IconButton icon="trash-2" label="Delete" variant="danger" />
        <IconButton icon="send" label="Send" variant="accent" loading />
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('IconButton', () => (
  <div>
    <IconButton icon="panel-left" label="Collapse" />
    <IconButton icon="send" label="Send" variant="accent" />
    <IconButton icon="trash-2" label="Delete" variant="danger" size="sm" />
    <IconButton icon="refresh-cw" label="Retry" loading />
  </div>
));
