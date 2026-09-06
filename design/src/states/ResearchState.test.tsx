import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../tests/axe';
import { describeThemeDensitySnapshots } from '../../tests/variants';
import { ResearchState, describeResearchState } from './ResearchState';
import type { ResearchStateCase } from './ResearchState';

const CASES: ResearchStateCase[] = [
  { case: 'offline' },
  { case: 'provider-unavailable', provider: 'Local llama.cpp' },
  { case: 'attachment-unsupported', filename: 'scan.tiff' },
  { case: 'attachment-omitted', filename: 'appendix.pdf' },
  { case: 'egress-blocked', policy: 'The private session class' },
  { case: 'index-rebuilding', progress: 40 },
  { case: 'index-absent' },
  { case: 'index-unreadable' },
  { case: 'anchor-stale', anchor: 'p12:b3' },
  { case: 'latex-compile-failed', lastGoodPdf: true },
  { case: 'read-only-host' },
  { case: 'stream-interrupted' },
];

describe('ResearchState', () => {
  it('covers every named research case from the design spec', () => {
    expect(CASES).toHaveLength(12);
    for (const state of CASES) {
      const presentation = describeResearchState(state);
      expect(presentation.title.length).toBeGreaterThan(0);
      expect(presentation.description.length).toBeGreaterThan(0);
      // Each one says what happened to the draft or to the source.
      expect(
        presentation.safety.draft ?? presentation.safety.source ?? presentation.safety.note,
      ).toBeDefined();
    }
  });

  it('renders each case with an icon, a written kind and a safety statement', () => {
    for (const state of CASES) {
      const presentation = describeResearchState(state);
      const { unmount } = render(<ResearchState state={state} />);
      const node = screen.getByText(presentation.title).closest('.rh-state');
      expect(node).toHaveAttribute('data-case', state.case);
      expect(node).toHaveTextContent(presentation.description);
      expect(node?.querySelector('.rh-state__safety')).not.toBeNull();
      expect(node?.querySelector(`[data-icon="${presentation.icon}"]`)).not.toBeNull();
      unmount();
    }
  });

  it('describes offline work as safe and retryable', () => {
    render(<ResearchState state={{ case: 'offline' }} />);
    const state = screen.getByRole('status');
    expect(state).toHaveTextContent('Try again');
    expect(state).toHaveTextContent('You are offline');
    expect(state).toHaveTextContent('Your draft is safe.');
    expect(state).toHaveTextContent('Nothing was sent.');
  });

  it('treats a privacy block as blocked and announces it assertively', () => {
    render(<ResearchState state={{ case: 'egress-blocked', policy: 'The private class' }} />);
    const state = screen.getByRole('alert');
    expect(state).toHaveTextContent('Blocked');
    expect(state).toHaveTextContent('Nothing left the workspace.');
  });

  it('shows rebuild progress and says accepted objects are unaffected', () => {
    render(<ResearchState state={{ case: 'index-rebuilding', progress: 40 }} />);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40');
    expect(screen.getByRole('status')).toHaveTextContent('derived and disposable');
  });

  it.each(['index-absent', 'index-unreadable'] as const)(
    'presents %s as partial rather than as work in progress',
    (name) => {
      render(<ResearchState state={{ case: name }} />);
      const state = screen.getByRole('status');
      // The defect this exists to prevent: an index that is not being built must not be
      // dressed up as one that is - no LOADING, no spinner, no bar that never finishes.
      expect(state).toHaveAttribute('data-kind', 'partial');
      expect(state).not.toHaveAttribute('aria-busy');
      expect(state).toHaveTextContent('Partial');
      expect(state).not.toHaveTextContent('Loading');
      expect(screen.queryByRole('progressbar')).toBeNull();
      // It still says the thing that matters: the index is derived, and nothing accepted moved.
      expect(state).toHaveTextContent('derived and disposable');
    },
  );

  it('marks a stale anchor without claiming the evidence changed', () => {
    render(<ResearchState state={{ case: 'anchor-stale', anchor: 'p12:b3' }} />);
    const state = screen.getByRole('status');
    expect(state).toHaveTextContent('The anchor p12:b3 no longer matches its source');
    expect(state).toHaveTextContent('The source may have changed.');
    expect(state).toHaveTextContent('recorded quote are unchanged');
  });

  it('keeps the last good PDF language for a failed compile', () => {
    render(<ResearchState state={{ case: 'latex-compile-failed', lastGoodPdf: true }} />);
    expect(screen.getByRole('status')).toHaveTextContent('still shown and is marked stale');
    expect(screen.getByRole('status')).toHaveTextContent(
      'Your LaTeX source is saved exactly as you wrote it.',
    );
  });

  it('warns that a draft is at risk on a read-only host, politely', () => {
    render(<ResearchState state={{ case: 'read-only-host' }} />);
    // Announced as `status`, not `alert`. A read-only host is a standing condition of the
    // whole window, on every page for as long as it lasts — not an event that just
    // happened. `alert` interrupts whatever the reader is doing, and this notice would
    // interrupt them on each navigation, which teaches them to ignore the one assertive
    // channel the product has. The words are unchanged; only the politeness is.
    const state = screen.getByRole('status');
    expect(state).toHaveAttribute('data-case', 'read-only-host');
    expect(state).toHaveAttribute('data-kind', 'blocked');
    expect(state).toHaveTextContent('Your draft is not saved yet.');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('passes actions through without performing them', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <ResearchState
        state={{ case: 'provider-unavailable' }}
        actions={[{ label: 'Retry', onClick: onRetry }]}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('allows a surface to override the wording', () => {
    render(<ResearchState state={{ case: 'offline' }} title="No connection in this pane" />);
    expect(screen.getByText('No connection in this pane')).toBeInTheDocument();
  });

  it('has no axe violations for any case', async () => {
    for (const state of CASES) {
      const { container, unmount } = render(
        <ResearchState state={state} actions={[{ label: 'Retry', onClick: vi.fn() }]} />,
      );
      await expectNoAxeViolations(container);
      unmount();
    }
  });

  describeThemeDensitySnapshots('ResearchState', () => (
    <ResearchState
      state={{ case: 'stream-interrupted' }}
      actions={[{ label: 'Continue', onClick: () => undefined, variant: 'primary' }]}
      retained={<p>The partial reply so far.</p>}
    />
  ));
});
