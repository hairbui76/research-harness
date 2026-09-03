import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useRef, useState } from 'react';
import { describe, expect, it } from 'vitest';
import { getTabbable } from './focusable';
import { useFocusTrap } from './useFocusTrap';

function Trapped({ active, autoFocus = true }: { active: boolean; autoFocus?: boolean }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  useFocusTrap({ active, containerRef, autoFocus });
  return (
    <div ref={containerRef} data-testid="trap">
      <button type="button">First</button>
      <button type="button">Second</button>
    </div>
  );
}

function Harness() {
  const [active, setActive] = useState(false);
  return (
    <div>
      <button type="button" onClick={() => setActive(true)}>
        Open
      </button>
      <button type="button">Outside</button>
      {active ? (
        <>
          <Trapped active />
          <button type="button" onClick={() => setActive(false)}>
            Close
          </button>
        </>
      ) : null}
    </div>
  );
}

describe('useFocusTrap', () => {
  it('moves focus in, cycles Tab and restores focus to the opener', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole('button', { name: 'Open' });
    await user.click(opener);

    expect(screen.getByRole('button', { name: 'First' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Second' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'First' })).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole('button', { name: 'Second' })).toHaveFocus();

    // Deactivating restores focus to whatever had it before.
    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(opener).toHaveFocus();
  });

  it('focuses the container when it holds nothing tabbable', () => {
    function Empty() {
      const containerRef = useRef<HTMLDivElement | null>(null);
      useFocusTrap({ active: true, containerRef });
      return <div ref={containerRef} data-testid="empty" />;
    }
    render(<Empty />);
    const container = screen.getByTestId('empty');
    expect(container).toHaveFocus();
    expect(container).toHaveAttribute('tabindex', '-1');
  });

  it('leaves focus alone when autoFocus is off', () => {
    render(<Trapped active autoFocus={false} />);
    expect(document.body).toHaveFocus();
  });

  it('lists only reachable elements as tabbable', () => {
    render(
      <div data-testid="root">
        <button type="button">Visible</button>
        <button type="button" disabled>
          Disabled
        </button>
        <button type="button" tabIndex={-1}>
          Skipped
        </button>
        <div aria-hidden="true">
          <button type="button">Hidden</button>
        </div>
        <a href="#somewhere">Link</a>
      </div>,
    );
    const names = getTabbable(screen.getByTestId('root')).map((element) => element.textContent);
    expect(names).toEqual(['Visible', 'Link']);
  });
});
