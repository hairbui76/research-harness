import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Tooltip } from './Tooltip';

describe('Tooltip', () => {
  it('opens on focus without delay and describes its trigger', async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="Runs the retrieval step again">
        <button type="button">Re-run</button>
      </Tooltip>,
    );
    const trigger = screen.getByRole('button', { name: 'Re-run' });
    expect(trigger).not.toHaveAttribute('aria-describedby');

    await user.tab();
    expect(trigger).toHaveFocus();
    const tip = await screen.findByRole('tooltip');
    expect(tip).toHaveTextContent('Runs the retrieval step again');
    expect(trigger).toHaveAttribute('aria-describedby', tip.id);
    expect(trigger).toHaveAccessibleDescription('Runs the retrieval step again');

    await user.tab();
    await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
  });

  it('waits for the hover delay before opening', async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="Supplementary" openDelay={60}>
        <button type="button">Re-run</button>
      </Tooltip>,
    );
    await user.hover(screen.getByRole('button', { name: 'Re-run' }));
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    expect(await screen.findByRole('tooltip')).toBeInTheDocument();
  });

  it('stays open while the pointer travels onto the tooltip', async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="Supplementary" openDelay={0} closeDelay={400}>
        <button type="button">Re-run</button>
      </Tooltip>,
    );
    const trigger = screen.getByRole('button', { name: 'Re-run' });
    await user.hover(trigger);
    const tip = await screen.findByRole('tooltip');

    await user.unhover(trigger);
    await user.hover(tip);
    await new Promise((resolve) => {
      setTimeout(resolve, 600);
    });
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
  });

  it('dismisses with Escape while the trigger keeps focus', async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="Supplementary">
        <button type="button">Re-run</button>
      </Tooltip>,
    );
    await user.tab();
    expect(await screen.findByRole('tooltip')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Re-run' })).toHaveFocus();
  });

  it('supports a controlled open state and can be disabled entirely', async () => {
    const onOpenChange = vi.fn();
    const { rerender } = render(
      <Tooltip content="Supplementary" open onOpenChange={onOpenChange}>
        <button type="button">Re-run</button>
      </Tooltip>,
    );
    expect(await screen.findByRole('tooltip')).toBeInTheDocument();

    rerender(
      <Tooltip content="Supplementary" open={false} onOpenChange={onOpenChange}>
        <button type="button">Re-run</button>
      </Tooltip>,
    );
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    rerender(
      <Tooltip content="Supplementary" disabled>
        <button type="button">Re-run</button>
      </Tooltip>,
    );
    expect(screen.getByRole('button', { name: 'Re-run' })).toBeInTheDocument();
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('warns when the trigger is disabled, because it emits no events', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    render(
      <Tooltip content="Unavailable while offline">
        <button type="button" disabled>
          Send
        </button>
      </Tooltip>,
    );
    await waitFor(() => expect(warn).toHaveBeenCalledTimes(1));
    expect(warn.mock.calls[0]?.[0]).toContain('disabled element');
  });

  it('keeps the trigger own handlers working', async () => {
    const user = userEvent.setup();
    const onFocus = vi.fn();
    render(
      <Tooltip content="Supplementary">
        <button type="button" onFocus={onFocus}>
          Re-run
        </button>
      </Tooltip>,
    );
    await user.tab();
    expect(onFocus).toHaveBeenCalled();
  });

  it('has no axe violations while open', async () => {
    render(
      <Tooltip content="Supplementary" open>
        <button type="button">Re-run</button>
      </Tooltip>,
    );
    await screen.findByRole('tooltip');
    await expectNoAxeViolations(document.body);
  });

  describeThemeDensitySnapshots(
    'Tooltip',
    () => (
      <Tooltip content="Runs the retrieval step again" open>
        <button type="button">Re-run</button>
      </Tooltip>
    ),
    { target: 'portal' },
  );
});
