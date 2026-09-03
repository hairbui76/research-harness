import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createPortal } from 'react-dom';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useControllableState } from './useControllableState';
import { useId } from './useId';
import { usePortal } from './usePortal';
import { useReducedMotion } from './useReducedMotion';

describe('useId', () => {
  it('generates a selector-safe id and honours a caller-supplied one', () => {
    function Probe({ id }: { id?: string }) {
      return <span data-testid="probe" id={useId(id, 'rh-probe')} />;
    }
    const { rerender } = render(<Probe />);
    const generated = screen.getByTestId('probe').id;
    expect(generated).toMatch(/^rh-probe-/);
    expect(generated).not.toContain(':');

    // Stable across renders.
    rerender(<Probe />);
    expect(screen.getByTestId('probe').id).toBe(generated);

    rerender(<Probe id="mine" />);
    expect(screen.getByTestId('probe').id).toBe('mine');
  });
});

describe('usePortal', () => {
  it('creates a host on mount and removes it on unmount', () => {
    function Portalled() {
      const host = usePortal({ name: 'probe' });
      return host ? createPortal(<p>In the portal</p>, host) : null;
    }
    const { unmount } = render(<Portalled />);
    expect(document.body.querySelector('[data-rh-portal="probe"]')).not.toBeNull();
    expect(screen.getByText('In the portal')).toBeInTheDocument();
    unmount();
    expect(document.body.querySelector('[data-rh-portal="probe"]')).toBeNull();
  });

  it('creates nothing while disabled and honours a custom container', () => {
    const container = document.createElement('section');
    document.body.appendChild(container);
    function Portalled({ enabled }: { enabled: boolean }) {
      const host = usePortal({ enabled, container, name: 'probe' });
      return host ? createPortal(<p>In the portal</p>, host) : null;
    }
    const { rerender } = render(<Portalled enabled={false} />);
    expect(container.querySelector('[data-rh-portal]')).toBeNull();
    rerender(<Portalled enabled />);
    expect(container.querySelector('[data-rh-portal]')).not.toBeNull();
    container.remove();
  });
});

describe('useReducedMotion', () => {
  afterEach(() => {
    Reflect.deleteProperty(window, 'matchMedia');
  });

  function Probe() {
    return <span data-testid="motion">{useReducedMotion() ? 'reduced' : 'full'}</span>;
  }

  it('is false where matchMedia is unavailable', () => {
    render(<Probe />);
    expect(screen.getByTestId('motion')).toHaveTextContent('full');
  });

  it('follows the media query and its changes', () => {
    let listener: ((event: MediaQueryListEvent) => void) | undefined;
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: (query: string) => ({
        matches: true,
        media: query,
        addEventListener: (_type: string, handler: (event: MediaQueryListEvent) => void) => {
          listener = handler;
        },
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
        onchange: null,
      }),
    });
    render(<Probe />);
    expect(screen.getByTestId('motion')).toHaveTextContent('reduced');
    act(() => listener?.({ matches: false } as MediaQueryListEvent));
    expect(screen.getByTestId('motion')).toHaveTextContent('full');
  });
});

describe('useControllableState', () => {
  function Counter({
    value,
    onChange,
  }: {
    value?: number;
    onChange?: (value: number) => void;
  }) {
    const [count, setCount] = useControllableState<number>({ value, defaultValue: 0, onChange });
    return (
      <div>
        <span data-testid="count">{count}</span>
        <button type="button" onClick={() => setCount(count + 1)}>
          Increment
        </button>
        <button type="button" onClick={() => setCount((previous) => previous + 10)}>
          Add ten
        </button>
        <button type="button" onClick={() => setCount(count)}>
          Set same
        </button>
      </div>
    );
  }

  it('owns its state when uncontrolled and reports every change', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Counter onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: 'Increment' }));
    expect(screen.getByTestId('count')).toHaveTextContent('1');
    await user.click(screen.getByRole('button', { name: 'Add ten' }));
    expect(screen.getByTestId('count')).toHaveTextContent('11');
    expect(onChange).toHaveBeenLastCalledWith(11);
  });

  it('does not fire onChange when the value did not move', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Counter onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: 'Set same' }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('defers to the caller when controlled', async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [value, setValue] = useState(5);
      return (
        <>
          <Counter value={value} onChange={setValue} />
          <span data-testid="outer">{value}</span>
        </>
      );
    }
    render(<Controlled />);
    expect(screen.getByTestId('count')).toHaveTextContent('5');
    await user.click(screen.getByRole('button', { name: 'Increment' }));
    expect(screen.getByTestId('outer')).toHaveTextContent('6');
    expect(screen.getByTestId('count')).toHaveTextContent('6');
  });

  it('ignores internal updates when controlled and the caller does not accept them', async () => {
    const user = userEvent.setup();
    render(<Counter value={5} />);
    await user.click(screen.getByRole('button', { name: 'Increment' }));
    expect(screen.getByTestId('count')).toHaveTextContent('5');
  });
});
