import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useRef, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Dialog } from './Dialog';
import type { DialogProps } from './Dialog';

function Harness(props: Partial<DialogProps> = {}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        Promote candidate
      </button>
      <Dialog open={open} onOpenChange={setOpen} {...props}>
        <Dialog.Header>Promote candidate claim?</Dialog.Header>
        <Dialog.Body>
          This records a promotion request for review. Nothing is accepted yet.
        </Dialog.Body>
        <Dialog.Footer>
          <Dialog.Close>Cancel</Dialog.Close>
          <button type="button">Request promotion</button>
        </Dialog.Footer>
      </Dialog>
    </div>
  );
}

describe('Dialog', () => {
  it('is a labelled, described modal when open and renders nothing when closed', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Promote candidate' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAccessibleName('Promote candidate claim?');
    expect(dialog).toHaveAccessibleDescription(
      'This records a promotion request for review. Nothing is accepted yet.',
    );
    expect(dialog).toHaveAttribute('data-size', 'md');
  });

  it('moves focus in, traps Tab and restores focus to the opener', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole('button', { name: 'Promote candidate' });
    await user.click(opener);

    const close = screen.getByRole('button', { name: 'Close' });
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    const confirm = screen.getByRole('button', { name: 'Request promotion' });
    expect(close).toHaveFocus();

    await user.tab();
    expect(cancel).toHaveFocus();
    await user.tab();
    expect(confirm).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(opener).toHaveFocus();
  });

  it('honours initialFocusRef', async () => {
    const user = userEvent.setup();
    function WithInitialFocus() {
      const inputRef = useRef<HTMLInputElement | null>(null);
      return (
        <Dialog defaultOpen initialFocusRef={inputRef}>
          <Dialog.Header>Rename session</Dialog.Header>
          <Dialog.Body>
            <label htmlFor="title">Title</label>
            <input id="title" ref={inputRef} />
          </Dialog.Body>
        </Dialog>
      );
    }
    render(<WithInitialFocus />);
    await waitFor(() => expect(screen.getByLabelText('Title')).toHaveFocus());
    await user.keyboard('a');
    expect(screen.getByLabelText('Title')).toHaveValue('a');
  });

  it('closes on a scrim press but not on a press inside the panel', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Promote candidate' }));

    await user.click(screen.getByRole('dialog'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    const scrim = document.querySelector('[data-rh-dialog-scrim]');
    expect(scrim).not.toBeNull();
    await user.click(scrim as Element);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('ignores Escape and scrim presses when not dismissible', async () => {
    const user = userEvent.setup();
    render(<Harness dismissible={false} />);
    await user.click(screen.getByRole('button', { name: 'Promote candidate' }));

    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.click(document.querySelector('[data-rh-dialog-scrim]') as Element);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('renders an alertdialog that the scrim cannot dismiss', async () => {
    const user = userEvent.setup();
    render(<Harness role="alertdialog" size="sm" />);
    await user.click(screen.getByRole('button', { name: 'Promote candidate' }));
    expect(screen.getByRole('alertdialog')).toHaveAttribute('data-size', 'sm');
    await user.click(document.querySelector('[data-rh-dialog-scrim]') as Element);
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  });

  it('locks body scroll while open and restores it on close', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'Promote candidate' }));
    expect(document.body.style.overflow).toBe('hidden');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(document.body.style.overflow).not.toBe('hidden'));
  });

  it('supports an uncontrolled dialog and reports open changes', async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(
      <Dialog defaultOpen onOpenChange={onOpenChange}>
        <Dialog.Header>Uncontrolled</Dialog.Header>
        <Dialog.Body>Body</Dialog.Body>
      </Dialog>,
    );
    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    render(<Harness defaultOpen open />);
    await expectNoAxeViolations(document.body);
  });

  describeThemeDensitySnapshots(
    'Dialog',
    () => (
      <Dialog open>
        <Dialog.Header>Promote candidate claim?</Dialog.Header>
        <Dialog.Body>Nothing is accepted yet.</Dialog.Body>
        <Dialog.Footer>
          <Dialog.Close>Cancel</Dialog.Close>
        </Dialog.Footer>
      </Dialog>
    ),
    { target: 'portal' },
  );
});
