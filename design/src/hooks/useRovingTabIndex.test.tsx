import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useRef } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { useRovingTabIndex } from './useRovingTabIndex';
import type { RovingOrientation } from './useRovingTabIndex';

function Toolbar({
  orientation = 'horizontal',
  loop = true,
  typeahead = false,
  onActivate,
}: {
  orientation?: RovingOrientation;
  loop?: boolean;
  typeahead?: boolean;
  onActivate?: (label: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const roving = useRovingTabIndex({
    containerRef,
    orientation,
    loop,
    typeahead,
    onActivate: (item) => onActivate?.(item.textContent ?? ''),
  });
  return (
    <div ref={containerRef} onKeyDown={roving.onKeyDown} data-testid="toolbar">
      {['Alpha', 'Beta', 'Gamma'].map((label, index) => (
        <button
          key={label}
          type="button"
          data-rh-roving-item=""
          tabIndex={index === 0 ? 0 : -1}
          aria-disabled={label === 'Beta' ? true : undefined}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

describe('useRovingTabIndex', () => {
  it('moves along the orientation axis, skipping disabled items, and wraps', async () => {
    const user = userEvent.setup();
    render(<Toolbar />);
    await user.tab();
    expect(screen.getByRole('button', { name: 'Alpha' })).toHaveFocus();

    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('button', { name: 'Gamma' })).toHaveFocus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('button', { name: 'Alpha' })).toHaveFocus();
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('button', { name: 'Gamma' })).toHaveFocus();

    // The other axis is ignored.
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('button', { name: 'Gamma' })).toHaveFocus();
  });

  it('stops at the ends when looping is off', async () => {
    const user = userEvent.setup();
    render(<Toolbar loop={false} />);
    await user.tab();
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('button', { name: 'Alpha' })).toHaveFocus();
  });

  it('jumps to the ends with Home and End', async () => {
    const user = userEvent.setup();
    render(<Toolbar />);
    await user.tab();
    await user.keyboard('{End}');
    expect(screen.getByRole('button', { name: 'Gamma' })).toHaveFocus();
    await user.keyboard('{Home}');
    expect(screen.getByRole('button', { name: 'Alpha' })).toHaveFocus();
  });

  it('activates with Enter and Space', async () => {
    const user = userEvent.setup();
    const onActivate = vi.fn();
    render(<Toolbar onActivate={onActivate} />);
    await user.tab();
    await user.keyboard('{Enter}');
    expect(onActivate).toHaveBeenLastCalledWith('Alpha');
    await user.keyboard(' ');
    expect(onActivate).toHaveBeenLastCalledWith('Alpha');
  });

  it('supports typeahead when enabled', async () => {
    const user = userEvent.setup();
    render(<Toolbar typeahead />);
    await user.tab();
    await user.keyboard('g');
    expect(screen.getByRole('button', { name: 'Gamma' })).toHaveFocus();
  });

  it('uses the vertical axis when asked', async () => {
    const user = userEvent.setup();
    render(<Toolbar orientation="vertical" />);
    await user.tab();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByRole('button', { name: 'Gamma' })).toHaveFocus();
  });
});
