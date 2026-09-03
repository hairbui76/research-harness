import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { OMISSION_REASON_META } from '../models';
import { SAMPLE_PRIVATE_REF, SAMPLE_RECEIPT } from '../samples';
import { ContextReceipt } from './ContextReceipt';

const NOTHING_OMITTED = { ...SAMPLE_RECEIPT, omitted: [] };

describe('ContextReceipt', () => {
  it('names the provider, the model and the effective egress class', () => {
    render(<ContextReceipt receipt={SAMPLE_RECEIPT} />);
    expect(screen.getByText('Anthropic')).toBeInTheDocument();
    expect(screen.getByText('claude-opus-5')).toBeInTheDocument();
    expect(screen.getByText('External')).toBeInTheDocument();
    expect(screen.getByText('CP0007')).toBeInTheDocument();
  });

  it('opens by default whenever anything was omitted', () => {
    render(<ContextReceipt receipt={SAMPLE_RECEIPT} />);
    expect(screen.getByRole('button', { name: /Context used/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });

  it('stays closed when the pack left nothing out', () => {
    render(<ContextReceipt receipt={NOTHING_OMITTED} />);
    expect(screen.getByRole('button', { name: /Context used/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
  });

  it('counts the omissions in the header even when it is collapsed', () => {
    render(<ContextReceipt receipt={SAMPLE_RECEIPT} defaultOpen={false} />);
    expect(screen.getByText('2 omitted')).toBeInTheDocument();
  });

  it('gives every omission a reason', () => {
    const { container } = render(<ContextReceipt receipt={SAMPLE_RECEIPT} />);
    const reasons = Array.from(container.querySelectorAll('.rh-context-receipt__reason')).map(
      (node) => node.textContent,
    );
    expect(reasons).toEqual([
      OMISSION_REASON_META.privacy_policy.label,
      OMISSION_REASON_META.stale.label,
    ]);
    expect(
      screen.getByText('The session is marked private and the selected provider is external.'),
    ).toBeInTheDocument();
    // The fallback description stands in when the host supplied no detail.
    expect(screen.getByText(OMISSION_REASON_META.stale.description)).toBeInTheDocument();
  });

  it('reports the budget as a bar and as text', () => {
    render(<ContextReceipt receipt={SAMPLE_RECEIPT} />);
    const bars = screen.getAllByRole('progressbar');
    expect(bars).toHaveLength(SAMPLE_RECEIPT.allocation.length);
    expect(bars[0]).toHaveAttribute('aria-valuetext', '420 of 32,000 tokens');
  });

  it('collapses and expands from the keyboard', async () => {
    const user = userEvent.setup();
    render(<ContextReceipt receipt={NOTHING_OMITTED} />);
    const toggle = screen.getByRole('button', { name: /Context used/ });
    await user.tab();
    await user.keyboard('{Enter}');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await user.keyboard('{Enter}');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
  });

  it('opens a referenced object', async () => {
    const user = userEvent.setup();
    const onOpenRef = vi.fn();
    render(<ContextReceipt receipt={SAMPLE_RECEIPT} onOpenRef={onOpenRef} />);
    await user.click(screen.getByText('CS0004'));
    expect(onOpenRef).toHaveBeenCalledWith(SAMPLE_PRIVATE_REF);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<ContextReceipt receipt={SAMPLE_RECEIPT} />);
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('ContextReceipt', () => (
  <ContextReceipt receipt={SAMPLE_RECEIPT} />
));
