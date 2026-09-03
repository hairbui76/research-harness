import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { cx } from './cx';
import { joinIds, useAutoId, useFieldIds } from './ids';
import { useControllable } from './useControllable';

describe('cx', () => {
  it('joins strings and skips falsy values', () => {
    expect(cx('a', false, undefined, null, '', 'b')).toBe('a b');
  });

  it('takes arrays and condition maps', () => {
    expect(cx(['a', ['b']], { c: true, d: false, e: undefined })).toBe('a b c');
  });

  it('keeps zero, which is a legitimate class name fragment', () => {
    expect(cx(0)).toBe('0');
  });
});

describe('joinIds', () => {
  it('returns undefined rather than an empty aria-describedby', () => {
    expect(joinIds(undefined, false, null, '')).toBeUndefined();
  });

  it('joins only the ids that exist', () => {
    expect(joinIds('a', undefined, 'b')).toBe('a b');
  });
});

describe('useAutoId', () => {
  function Probe({ id }: { id?: string }) {
    return <span data-testid="probe" id={useAutoId(id, 'rh-probe')} />;
  }

  it('uses the caller id when given', () => {
    render(<Probe id="mine" />);
    expect(screen.getByTestId('probe')).toHaveAttribute('id', 'mine');
  });

  it('generates a colon-free prefixed id otherwise', () => {
    render(<Probe />);
    const id = screen.getByTestId('probe').getAttribute('id') ?? '';
    expect(id.startsWith('rh-probe-')).toBe(true);
    expect(id).not.toContain(':');
  });
});

describe('useFieldIds', () => {
  it('derives the description and error ids from the control id', () => {
    function Probe() {
      const ids = useFieldIds('field');
      return <span data-testid="probe" data-ids={JSON.stringify(ids)} />;
    }
    render(<Probe />);
    expect(JSON.parse(screen.getByTestId('probe').dataset.ids as string)).toEqual({
      controlId: 'field',
      descriptionId: 'field-description',
      errorId: 'field-error',
    });
  });
});

describe('useControllable', () => {
  function Probe({ value, onChange }: { value?: string; onChange?: (v: string) => void }) {
    const [current, set] = useControllable<string>({ value, defaultValue: 'a', onChange });
    return (
      <button type="button" onClick={() => set('b')}>
        {current}
      </button>
    );
  }

  it('keeps its own state when uncontrolled', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Probe onChange={onChange} />);
    expect(screen.getByRole('button')).toHaveTextContent('a');
    await user.click(screen.getByRole('button'));
    expect(screen.getByRole('button')).toHaveTextContent('b');
    expect(onChange).toHaveBeenCalledWith('b');
  });

  it('defers to the parent when controlled', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Probe value="fixed" onChange={onChange} />);
    await user.click(screen.getByRole('button'));
    expect(screen.getByRole('button')).toHaveTextContent('fixed');
    expect(onChange).toHaveBeenCalledWith('b');
  });

  it('follows a parent that stores what it is told', async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [value, setValue] = useState('a');
      return <Probe value={value} onChange={setValue} />;
    }
    render(<Controlled />);
    await user.click(screen.getByRole('button'));
    expect(screen.getByRole('button')).toHaveTextContent('b');
  });

  it('warns when a component changes mode mid-life', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { rerender } = render(<Probe />);
    rerender(<Probe value="now controlled" />);
    expect(warn).toHaveBeenCalledTimes(1);
    warn.mockRestore();
  });
});
