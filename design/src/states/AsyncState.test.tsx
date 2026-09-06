import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../tests/axe';
import { describeThemeDensitySnapshots } from '../../tests/variants';
import { AsyncState } from './AsyncState';
import { ASYNC_STATE_META } from './types';
import type { AsyncStateKind } from './types';

const KINDS: AsyncStateKind[] = [
  'loading',
  'empty',
  'partial',
  'stale',
  'blocked',
  'retryable',
  'fatal',
];

describe('AsyncState', () => {
  it('names every kind in text as well as with an icon', () => {
    for (const kind of KINDS) {
      const { unmount } = render(<AsyncState kind={kind} title={`${kind} title`} />);
      const meta = ASYNC_STATE_META[kind];
      // The written label is what carries the state; the icon only reinforces it.
      expect(screen.getByText(meta.label)).toBeInTheDocument();
      expect(document.querySelector(`[data-icon="${meta.icon}"]`)).toBeInTheDocument();
      expect(document.querySelector(`[data-icon="${meta.icon}"]`)).toHaveAttribute(
        'aria-hidden',
        'true',
      );
      unmount();
    }
  });

  it('announces politely by default and assertively when blocked or fatal', () => {
    const { rerender } = render(<AsyncState kind="loading" title="Loading sources" />);
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true');

    rerender(<AsyncState kind="fatal" title="Send failed" />);
    expect(screen.getByRole('alert')).toBeInTheDocument();

    rerender(<AsyncState kind="stale" title="Anchor moved" urgent />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('states whether the draft and the source are safe', () => {
    render(
      <AsyncState
        kind="retryable"
        title="Send failed"
        safety={{ draft: 'safe', source: 'at-risk', note: 'Nothing left the workspace.' }}
      />,
    );
    const state = screen.getByRole('status');
    expect(state).toHaveTextContent('Your draft is safe.');
    expect(state).toHaveTextContent('The source may have changed.');
    expect(state).toHaveTextContent('Nothing left the workspace.');
  });

  it('renders caller actions and never runs them itself', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <AsyncState
        kind="retryable"
        title="Send failed"
        actions={[
          { label: 'Retry', onClick: onRetry, variant: 'primary' },
          { label: 'Change model', onClick: vi.fn(), disabled: true },
        ]}
      />,
    );
    expect(onRetry).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Change model' })).toBeDisabled();
  });

  it('keeps content that already succeeded', () => {
    render(
      <AsyncState kind="stale" title="Index is behind" retained={<p>Previous 12 results</p>} />,
    );
    expect(screen.getByText('Previous 12 results')).toBeInTheDocument();
    expect(screen.getByText('Showing the last result that succeeded')).toBeInTheDocument();
  });

  it('shows determinate and indeterminate progress while loading', () => {
    const { rerender } = render(
      <AsyncState kind="loading" title="Rebuilding" progress={{ value: 40, label: 'Rebuild' }} />,
    );
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40');

    rerender(<AsyncState kind="loading" title="Rebuilding" progress={{ label: 'Rebuild' }} />);
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow');
  });

  it('drops its own frame when it sits inside one', () => {
    const { container, rerender } = render(<AsyncState kind="empty" title="No claims yet" flat />);
    expect(container.firstElementChild).toHaveAttribute('data-flat');

    rerender(<AsyncState kind="empty" title="No claims yet" />);
    expect(container.firstElementChild).not.toHaveAttribute('data-flat');
  });

  it('has no axe violations for any kind', async () => {
    for (const kind of KINDS) {
      const { container, unmount } = render(
        <AsyncState
          kind={kind}
          title="A state"
          description="What happened"
          safety={{ draft: 'safe' }}
          actions={[{ label: 'Retry', onClick: vi.fn() }]}
        />,
      );
      await expectNoAxeViolations(container);
      unmount();
    }
  });

  describeThemeDensitySnapshots('AsyncState', () => (
    <AsyncState
      kind="retryable"
      title="The model provider did not respond"
      description="No reply arrived, so nothing was recorded."
      safety={{ draft: 'safe', source: 'safe' }}
      actions={[{ label: 'Retry', onClick: () => undefined, variant: 'primary' }]}
    />
  ));
});
