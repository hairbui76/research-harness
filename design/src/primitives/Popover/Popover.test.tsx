import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { computeAnchorPosition } from '../../hooks/useAnchorPosition';
import { Popover } from './Popover';

function Example({ trapFocus = false }: { trapFocus?: boolean }) {
  return (
    <div>
      <button type="button">Before</button>
      <Popover trapFocus={trapFocus}>
        <Popover.Trigger>Filters</Popover.Trigger>
        <Popover.Content aria-label="Filters">
          <button type="button">Accepted only</button>
          <button type="button">Contested only</button>
        </Popover.Content>
      </Popover>
      <button type="button">After</button>
    </div>
  );
}

describe('Popover', () => {
  it('opens from the trigger, is a labelled dialog and wires aria-expanded', async () => {
    const user = userEvent.setup();
    render(<Example />);
    const trigger = screen.getByRole('button', { name: 'Filters' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog');

    await user.click(trigger);
    const content = screen.getByRole('dialog', { name: 'Filters' });
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(trigger).toHaveAttribute('aria-controls', content.id);
    expect(screen.getByRole('button', { name: 'Accepted only' })).toHaveFocus();
  });

  it('closes on Escape and returns focus to the trigger', async () => {
    const user = userEvent.setup();
    render(<Example />);
    const trigger = screen.getByRole('button', { name: 'Filters' });
    await user.click(trigger);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it('closes on an outside press and leaves focus where the user pressed', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole('button', { name: 'Filters' }));
    await user.click(screen.getByRole('button', { name: 'After' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Filters' })).not.toHaveFocus();
  });

  it('keeps a press inside the surface open', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole('button', { name: 'Filters' }));
    await user.click(screen.getByRole('button', { name: 'Contested only' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('traps Tab when asked to', async () => {
    const user = userEvent.setup();
    render(<Example trapFocus />);
    await user.click(screen.getByRole('button', { name: 'Filters' }));
    await user.tab();
    expect(screen.getByRole('button', { name: 'Contested only' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Accepted only' })).toHaveFocus();
  });

  it('supports a controlled open state and an asChild trigger', async () => {
    const user = userEvent.setup();
    render(
      <Popover defaultOpen={false}>
        <Popover.Trigger asChild>
          <a href="#anchor">Open notes</a>
        </Popover.Trigger>
        <Popover.Content aria-label="Notes">Notes</Popover.Content>
      </Popover>,
    );
    const link = screen.getByRole('link', { name: 'Open notes' });
    expect(link).toHaveAttribute('aria-expanded', 'false');
    await user.click(link);
    expect(screen.getByRole('dialog', { name: 'Notes' })).toBeInTheDocument();
  });

  it('flips placement when the preferred side has no room', () => {
    const flipped = computeAnchorPosition({
      anchor: { top: 8, left: 100, width: 80, height: 24 },
      floating: { width: 200, height: 160 },
      viewport: { width: 1024, height: 768 },
      placement: 'top',
      offset: 8,
    });
    expect(flipped.placement).toBe('bottom');
    expect(flipped.top).toBe(40);

    const kept = computeAnchorPosition({
      anchor: { top: 400, left: 100, width: 80, height: 24 },
      floating: { width: 200, height: 160 },
      viewport: { width: 1024, height: 768 },
      placement: 'top',
      offset: 8,
    });
    expect(kept.placement).toBe('top');
    // Clamped into the viewport along the cross axis.
    expect(kept.left).toBe(40);
  });

  it('has no axe violations while open', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole('button', { name: 'Filters' }));
    await expectNoAxeViolations(document.body);
  });

  describeThemeDensitySnapshots(
    'Popover',
    () => (
      <Popover defaultOpen>
        <Popover.Trigger>Filters</Popover.Trigger>
        <Popover.Content aria-label="Filters">Accepted only</Popover.Content>
      </Popover>
    ),
    { target: 'portal' },
  );
});
