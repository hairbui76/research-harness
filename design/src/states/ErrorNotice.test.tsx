import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../tests/axe';
import { describeThemeDensitySnapshots } from '../../tests/variants';
import { ErrorNotice } from './ErrorNotice';

describe('ErrorNotice', () => {
  it('leads the title with the kind, in the title’s own type', () => {
    const { container } = render(
      <ErrorNotice kind="blocked" title="Privacy rule blocked this request" />,
    );
    const notice = screen.getByRole('alert');
    expect(notice).toHaveTextContent('Blocked:');
    expect(notice).toHaveTextContent('Privacy rule blocked this request');
    // Not a label standing above the heading: the kind is the first words of the title's
    // own sentence, and carries no size, tracking or case of its own.
    const lead = container.querySelector('.rh-error-notice__kind');
    expect(lead?.closest('.rh-error-notice__title')).not.toBeNull();
  });

  it('is polite for partial and stale, assertive for blocked and fatal', () => {
    const { rerender } = render(<ErrorNotice kind="partial" title="Partial reply" />);
    expect(screen.getByRole('status')).toBeInTheDocument();

    rerender(<ErrorNotice kind="fatal" title="Compile failed" />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('hides machine detail behind a disclosure', async () => {
    const user = userEvent.setup();
    render(
      <ErrorNotice
        kind="fatal"
        title="The manuscript did not compile"
        detail="! Undefined control sequence. l.42 \\citep"
      />,
    );
    const summary = screen.getByText('Technical detail');
    expect(screen.getByText(/Undefined control sequence/)).not.toBeVisible();
    await user.click(summary);
    expect(screen.getByText(/Undefined control sequence/)).toBeVisible();
  });

  it('reports safety and offers caller actions', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const onDismiss = vi.fn();
    render(
      <ErrorNotice
        kind="retryable"
        title="Send failed"
        safety={{ draft: 'safe', source: 'safe' }}
        actions={[{ label: 'Retry send', onClick: onRetry }]}
        onDismiss={onDismiss}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Your draft is safe.');
    await user.click(screen.getByRole('button', { name: 'Retry send' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <ErrorNotice
        kind="stale"
        title="Anchor no longer matches"
        description="Re-anchor before relying on it."
        detail="anchor=abc123"
        safety={{ source: 'at-risk' }}
        onDismiss={() => undefined}
      />,
    );
    await expectNoAxeViolations(container);
  });

  describeThemeDensitySnapshots('ErrorNotice', () => (
    <ErrorNotice
      kind="blocked"
      title="A privacy rule blocked this request"
      description="Change the session privacy class or remove the restricted content."
      safety={{ draft: 'safe', source: 'safe', note: 'Nothing left the workspace.' }}
      actions={[{ label: 'Open privacy settings', onClick: () => undefined }]}
    />
  ));
});
