import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Button } from './Button';

describe('Button', () => {
  it('renders a button with its label and defaults to type=button', () => {
    render(<Button>Save to corpus</Button>);
    const button = screen.getByRole('button', { name: 'Save to corpus' });
    expect(button).toHaveAttribute('type', 'button');
    expect(button).toHaveClass('rh-button', 'rh-button--secondary', 'rh-button--md');
  });

  it.each(['primary', 'secondary', 'ghost', 'danger', 'accent'] as const)(
    'renders the %s variant',
    (variant) => {
      render(<Button variant={variant}>Run</Button>);
      expect(screen.getByRole('button')).toHaveAttribute('data-variant', variant);
    },
  );

  it('calls onClick for pointer and keyboard activation', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Send</Button>);
    const button = screen.getByRole('button');

    await user.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);

    button.focus();
    await user.keyboard('{Enter}');
    await user.keyboard(' ');
    expect(onClick).toHaveBeenCalledTimes(3);
  });

  it('is reachable by Tab and shows the focus ring class hook', async () => {
    const user = userEvent.setup();
    render(<Button>Focus me</Button>);
    await user.tab();
    expect(screen.getByRole('button')).toHaveFocus();
  });

  it('does not fire while disabled', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Send
      </Button>,
    );
    await user.click(screen.getByRole('button'));
    expect(onClick).not.toHaveBeenCalled();
    expect(screen.getByRole('button')).toBeDisabled();
  });

  it('keeps its label in the DOM while loading so the width does not jump', () => {
    render(<Button loading>Send</Button>);
    const button = screen.getByRole('button');
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(button).toBeDisabled();
    expect(button).toHaveClass('is-loading');
    expect(button.querySelector('.rh-button__label')).toHaveTextContent('Send');
    expect(button.querySelector('.rh-button__spinner')).not.toBeNull();
  });

  it('announces a loading label while the visible one is hidden', () => {
    render(
      <Button loading loadingLabel="Sending">
        Send
      </Button>,
    );
    expect(screen.getByRole('button')).toHaveTextContent('Sending');
  });

  it('renders leading and trailing icons', () => {
    const { container } = render(
      <Button iconStart="paperclip" iconEnd="chevron-down">
        Attach
      </Button>,
    );
    const icons = container.querySelectorAll('svg[data-icon]');
    expect(Array.from(icons).map((i) => i.getAttribute('data-icon'))).toEqual([
      'paperclip',
      'chevron-down',
    ]);
    for (const icon of icons) expect(icon).toHaveAttribute('aria-hidden', 'true');
  });

  it('forwards refs, className and style', () => {
    const ref = createRef<HTMLButtonElement>();
    render(
      <Button ref={ref} className="wide" style={{ marginTop: '4px' }}>
        Go
      </Button>,
    );
    expect(ref.current).toBe(screen.getByRole('button'));
    expect(ref.current).toHaveClass('wide');
    expect(ref.current).toHaveStyle({ marginTop: '4px' });
  });

  it('has no accessibility violations across its states', async () => {
    const { container } = render(
      <div>
        <Button variant="primary">Primary</Button>
        <Button variant="accent" iconStart="send">
          Send
        </Button>
        <Button variant="danger" disabled>
          Delete
        </Button>
        <Button loading>Loading</Button>
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('Button', () => (
  <div>
    <Button variant="primary">Primary</Button>
    <Button variant="secondary" iconStart="plus">
      Secondary
    </Button>
    <Button variant="ghost" size="sm">
      Ghost
    </Button>
    <Button variant="danger">Danger</Button>
    <Button variant="accent" iconStart="send">
      Send
    </Button>
    <Button loading>Loading</Button>
    <Button disabled>Disabled</Button>
  </div>
));
