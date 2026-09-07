import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { ToastProvider, useToast } from './Toast';
import type { ToastOptions, ToastProviderProps } from './Toast';

function Trigger({ label = 'Notify', ...options }: ToastOptions & { label?: string }): ReactElement {
  const { toast, dismissAll } = useToast();
  return (
    <>
      <button type="button" onClick={() => toast(options)}>
        {label}
      </button>
      <button type="button" onClick={dismissAll}>
        Clear all
      </button>
    </>
  );
}

function withProvider(children: ReactNode, props: Partial<ToastProviderProps> = {}): ReactElement {
  return <ToastProvider {...props}>{children}</ToastProvider>;
}

describe('Toast', () => {
  it('announces politely by default and assertively for errors', async () => {
    const user = userEvent.setup();
    render(
      withProvider(
        <>
          <Trigger label="Saved" title="Saved to corpus" duration={null} />
        </>,
      ),
    );
    await user.click(screen.getByRole('button', { name: 'Saved' }));
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Saved to corpus');
    expect(status).toHaveAttribute('aria-atomic', 'true');
    // The tone is spelled out, so it never depends on the border colour alone.
    expect(status).toHaveTextContent('Information:');
  });

  it('places the viewport at the top, clear of the controls a task ends on', async () => {
    const user = userEvent.setup();
    render(withProvider(<Trigger title="Candidate deferred" duration={null} />));
    await user.click(screen.getByRole('button', { name: 'Notify' }));
    // Bottom-right is where an app puts what it wants read next: a decision's outcome, the
    // way on, the switch beside it. A notification lands above the work instead.
    expect(screen.getByRole('region', { name: 'Notifications' })).toHaveAttribute(
      'data-placement',
      'top-right',
    );
  });

  it('uses role=alert for the error tone', async () => {
    const user = userEvent.setup();
    render(withProvider(<Trigger title="Provider unavailable" tone="error" duration={null} />));
    await user.click(screen.getByRole('button', { name: 'Notify' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Provider unavailable');
    expect(screen.getByRole('alert')).toHaveTextContent('Error:');
  });

  it('auto-dismisses after the duration and pauses while hovered', async () => {
    const user = userEvent.setup();
    render(withProvider(<Trigger title="Draft saved" duration={80} />));
    await user.click(screen.getByRole('button', { name: 'Notify' }));
    const toast = screen.getByRole('status');
    await user.hover(toast);
    await new Promise((resolve) => {
      setTimeout(resolve, 250);
    });
    expect(screen.getByRole('status')).toBeInTheDocument();
    await user.unhover(toast);
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  });

  it('dismisses from the close button and runs an action once', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      withProvider(
        <Trigger title="Retry send" duration={null} action={{ label: 'Retry', onClick }} />,
      ),
    );
    await user.click(screen.getByRole('button', { name: 'Notify' }));
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Notify' }));
    await user.click(screen.getByRole('button', { name: 'Dismiss notification' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('honours the queue limit and promotes queued toasts as slots free', async () => {
    const user = userEvent.setup();
    render(withProvider(<Trigger title="Queued" duration={null} />, { limit: 2 }));
    const notify = screen.getByRole('button', { name: 'Notify' });
    await user.click(notify);
    await user.click(notify);
    await user.click(notify);
    expect(screen.getAllByRole('status')).toHaveLength(2);

    await user.click(screen.getAllByRole('button', { name: 'Dismiss notification' })[0] as Element);
    await waitFor(() => expect(screen.getAllByRole('status')).toHaveLength(2));

    await user.click(screen.getByRole('button', { name: 'Clear all' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('replaces a toast that reuses an id instead of stacking it', async () => {
    const user = userEvent.setup();
    render(withProvider(<Trigger title="Compiling" id="compile" duration={null} />));
    await user.click(screen.getByRole('button', { name: 'Notify' }));
    await user.click(screen.getByRole('button', { name: 'Notify' }));
    expect(screen.getAllByRole('status')).toHaveLength(1);
  });

  it('throws a useful error when used outside a provider', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    function Orphan() {
      useToast();
      return null;
    }
    expect(() => render(<Orphan />)).toThrow(/ToastProvider/);
    error.mockRestore();
  });

  it('has no axe violations', async () => {
    const user = userEvent.setup();
    render(withProvider(<Trigger title="Saved to corpus" duration={null} />));
    await user.click(screen.getByRole('button', { name: 'Notify' }));
    await expectNoAxeViolations(document.body);
  });

  describeThemeDensitySnapshots(
    'Toast',
    () => (
      <ToastProvider>
        <ToastSpecimen />
      </ToastProvider>
    ),
    { target: 'portal' },
  );
});

/** Renders one polite and one assertive toast for the visual variants. */
function ToastSpecimen(): null {
  const { toast } = useToast();
  useEffect(() => {
    toast({
      title: 'Saved to corpus',
      description: 'Evidence linked to claim C-12.',
      duration: null,
    });
    toast({ title: 'Provider unavailable', tone: 'error', duration: null });
  }, [toast]);
  return null;
}
