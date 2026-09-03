import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useRef, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { useDismiss } from './useDismiss';
import type { DismissReason } from './useDismiss';

function Surface({
  name,
  onDismiss,
  enabled = true,
  escapeKey = true,
  outsidePress = true,
}: {
  name: string;
  onDismiss: (reason: DismissReason) => void;
  enabled?: boolean;
  escapeKey?: boolean;
  outsidePress?: boolean;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  useDismiss({ enabled, onDismiss, refs: [ref], escapeKey, outsidePress });
  return (
    <div ref={ref} data-testid={name}>
      <button type="button">Inside {name}</button>
    </div>
  );
}

describe('useDismiss', () => {
  it('dismisses on Escape and on a press outside', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(
      <div>
        <Surface name="one" onDismiss={onDismiss} />
        <button type="button">Outside</button>
      </div>,
    );

    await user.keyboard('{Escape}');
    expect(onDismiss).toHaveBeenLastCalledWith('escape');

    await user.click(screen.getByRole('button', { name: 'Outside' }));
    expect(onDismiss).toHaveBeenLastCalledWith('outside-press');
  });

  it('ignores presses inside any of the supplied refs', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    render(<Surface name="one" onDismiss={onDismiss} />);
    await user.click(screen.getByRole('button', { name: 'Inside one' }));
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it('listens to nothing while disabled, or when a channel is turned off', async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();
    const { rerender } = render(<Surface name="one" onDismiss={onDismiss} enabled={false} />);
    await user.keyboard('{Escape}');
    expect(onDismiss).not.toHaveBeenCalled();

    rerender(<Surface name="one" onDismiss={onDismiss} escapeKey={false} />);
    await user.keyboard('{Escape}');
    expect(onDismiss).not.toHaveBeenCalled();

    rerender(<Surface name="one" onDismiss={onDismiss} outsidePress={false} />);
    await user.click(document.body);
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it('only lets the innermost open surface react to Escape', async () => {
    const user = userEvent.setup();
    const outer = vi.fn();
    const inner = vi.fn();

    function Nested() {
      const [innerOpen, setInnerOpen] = useState(false);
      return (
        <div>
          <Surface name="outer" onDismiss={outer} />
          <button type="button" onClick={() => setInnerOpen(true)}>
            Open inner
          </button>
          {innerOpen ? <Surface name="inner" onDismiss={inner} /> : null}
        </div>
      );
    }

    render(<Nested />);
    await user.click(screen.getByRole('button', { name: 'Open inner' }));
    // That click was outside the outer surface, which is the correct behaviour for it;
    // what matters here is who reacts to the Escape that follows.
    outer.mockClear();
    await user.keyboard('{Escape}');
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
  });
});
