import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Menu } from './Menu';

function Example({ onRename = vi.fn(), onDelete = vi.fn() }: { onRename?: () => void; onDelete?: () => void }) {
  return (
    <div>
      <Menu>
        <Menu.Trigger>Session actions</Menu.Trigger>
        <Menu.Content>
          <Menu.Group label="Session">
            <Menu.Item onSelect={onRename} hint="R">
              Rename
            </Menu.Item>
            <Menu.Item disabled>Duplicate</Menu.Item>
            <Menu.Item>Export transcript</Menu.Item>
          </Menu.Group>
          <Menu.Separator />
          <Menu.Item onSelect={onDelete}>Delete</Menu.Item>
        </Menu.Content>
      </Menu>
      <button type="button">Elsewhere</button>
    </div>
  );
}

describe('Menu', () => {
  it('opens from the trigger with the menu pattern wired up', async () => {
    const user = userEvent.setup();
    render(<Example />);
    const trigger = screen.getByRole('button', { name: 'Session actions' });
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    await user.click(trigger);
    const menu = screen.getByRole('menu');
    expect(menu).toHaveAccessibleName('Session actions');
    expect(trigger).toHaveAttribute('aria-controls', menu.id);
    expect(screen.getAllByRole('menuitem')).toHaveLength(4);
    expect(screen.getByRole('menuitem', { name: /Rename/ })).toHaveFocus();
  });

  it('opens with ArrowUp focused on the last item', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.tab();
    await user.keyboard('{ArrowUp}');
    expect(screen.getByRole('menuitem', { name: 'Delete' })).toHaveFocus();
  });

  it('moves with arrows, skips disabled items and wraps', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole('button', { name: 'Session actions' }));

    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'Export transcript' })).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'Delete' })).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: /Rename/ })).toHaveFocus();
    await user.keyboard('{End}');
    expect(screen.getByRole('menuitem', { name: 'Delete' })).toHaveFocus();
    await user.keyboard('{Home}');
    expect(screen.getByRole('menuitem', { name: /Rename/ })).toHaveFocus();
  });

  it('supports typeahead', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole('button', { name: 'Session actions' }));
    await user.keyboard('ex');
    expect(screen.getByRole('menuitem', { name: 'Export transcript' })).toHaveFocus();
  });

  it('activates with Enter, closes and restores focus to the trigger', async () => {
    const user = userEvent.setup();
    const onRename = vi.fn();
    render(<Example onRename={onRename} />);
    const trigger = screen.getByRole('button', { name: 'Session actions' });
    await user.click(trigger);
    await user.keyboard('{Enter}');
    expect(onRename).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
  });

  it('does nothing for a disabled item', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole('button', { name: 'Session actions' }));
    const disabled = screen.getByRole('menuitem', { name: 'Duplicate' });
    expect(disabled).toHaveAttribute('aria-disabled', 'true');
    await user.click(disabled);
    expect(screen.getByRole('menu')).toBeInTheDocument();
  });

  it('closes on Escape with focus restored, and on an outside press without stealing focus', async () => {
    const user = userEvent.setup();
    render(<Example />);
    const trigger = screen.getByRole('button', { name: 'Session actions' });

    await user.click(trigger);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await user.click(screen.getByRole('button', { name: 'Elsewhere' }));
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Elsewhere' })).toHaveFocus();
  });

  it('closes on Tab because a menu is one tab stop', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole('button', { name: 'Session actions' }));
    await user.tab();
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument());
  });

  it('has no axe violations while open', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole('button', { name: 'Session actions' }));
    await expectNoAxeViolations(document.body);
  });

  describeThemeDensitySnapshots(
    'Menu',
    () => (
      <Menu defaultOpen>
        <Menu.Trigger>Session actions</Menu.Trigger>
        <Menu.Content>
          <Menu.Item hint="R">Rename</Menu.Item>
          <Menu.Separator />
          <Menu.Item disabled>Duplicate</Menu.Item>
        </Menu.Content>
      </Menu>
    ),
    { target: 'portal' },
  );
});
