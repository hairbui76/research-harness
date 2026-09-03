import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { CandidateDiff } from './CandidateDiff';
import type { CandidateDiffModel } from '../models';

const diff: CandidateDiffModel = {
  id: 'CD0001',
  originMessageId: 'M0042',
  contextPackId: 'CP0007',
  file: 'manuscript/main.tex',
  hunks: [
    {
      header: '@@ -88,4 +88,4 @@',
      lines: [
        { kind: 'context', text: 'We measured the response under load.' },
        { kind: 'removed', text: 'The effect proves the mechanism.' },
        { kind: 'added', text: 'The effect is consistent with the mechanism.' },
        {
          kind: 'context',
          text: '\\cite{smith2024}',
          protected: { kind: 'citation', reason: 'Citations may not be reworded by a candidate.' },
        },
      ],
    },
  ],
  semanticSummary: {
    added: [],
    removed: [],
    weakened: ['"proves" becomes "is consistent with"'],
    strengthened: [],
  },
  auditStatus: 'passed',
};

describe('CandidateDiff', () => {
  it('names the file, marks the edit a candidate and reports the audit status', () => {
    render(<CandidateDiff diff={diff} />);
    expect(
      screen.getByRole('article', { name: 'Candidate edit to manuscript/main.tex' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Candidate')).toBeInTheDocument();
    expect(screen.getByText('Audit passed')).toBeInTheDocument();
  });

  it('summarises what the candidate does to the propositions', () => {
    render(<CandidateDiff diff={diff} />);
    expect(screen.getByText('Weakened propositions')).toBeInTheDocument();
    expect(screen.getByText('"proves" becomes "is consistent with"')).toBeInTheDocument();
    expect(screen.queryByText('Added propositions')).not.toBeInTheDocument();
  });

  it('marks a protected span with text as well as a tint', () => {
    render(<CandidateDiff diff={diff} />);
    expect(screen.getByText('protected: citation')).toBeInTheDocument();
  });

  it('switches between unified and side-by-side', async () => {
    const user = userEvent.setup();
    const onViewChange = vi.fn();
    const { container } = render(<CandidateDiff diff={diff} onViewChange={onViewChange} />);
    expect(container.firstChild).toHaveAttribute('data-view', 'unified');

    await user.click(screen.getByRole('button', { name: 'Side by side' }));
    expect(onViewChange).toHaveBeenCalledWith('side-by-side');
    expect(container.firstChild).toHaveAttribute('data-view', 'side-by-side');
    expect(screen.getByRole('heading', { name: 'Before' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'After' })).toBeInTheDocument();
  });

  it('applies only on an explicit click and never on render', async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    const onReject = vi.fn();
    render(<CandidateDiff diff={diff} onApply={onApply} onReject={onReject} />);
    expect(onApply).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Apply to source' }));
    expect(onApply).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: 'Reject' }));
    expect(onReject).toHaveBeenCalledTimes(1);
  });

  it('blocks Apply with the stated reason when a protected span changed', () => {
    render(
      <CandidateDiff
        diff={{
          ...diff,
          auditStatus: 'failed',
          blockedReason: 'A protected citation span changed; the candidate cannot be applied.',
        }}
        onApply={vi.fn()}
      />,
    );
    const apply = screen.getByRole('button', { name: 'Apply to source' });
    expect(apply).toBeDisabled();
    expect(apply).toHaveAttribute('aria-describedby');
    expect(
      screen.getByText('A protected citation span changed; the candidate cannot be applied.'),
    ).toBeInTheDocument();
  });

  it('blocks Apply on a failed audit even without an explicit reason', () => {
    render(<CandidateDiff diff={{ ...diff, auditStatus: 'failed' }} onApply={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Apply to source' })).toBeDisabled();
    expect(screen.getByText(/The scientific audit failed for this candidate/)).toBeInTheDocument();
  });

  it('opens the message the candidate came back from', async () => {
    const user = userEvent.setup();
    const onOpenOrigin = vi.fn();
    render(<CandidateDiff diff={diff} onOpenOrigin={onOpenOrigin} />);
    expect(screen.getByText('Context used: CP0007')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open message M0042' }));
    expect(onOpenOrigin).toHaveBeenCalledWith('M0042');
  });

  it('keeps added and removed lines distinguishable without colour', () => {
    render(<CandidateDiff diff={diff} />);
    const hunk = screen.getByRole('region', { name: '@@ -88,4 +88,4 @@' });
    expect(within(hunk).getByText('added')).toBeInTheDocument();
    expect(within(hunk).getByText('removed')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <CandidateDiff diff={diff} onApply={vi.fn()} onReject={vi.fn()} onOpenOrigin={vi.fn()} />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('CandidateDiff', () => (
  <CandidateDiff diff={diff} onApply={() => undefined} onReject={() => undefined} />
));
