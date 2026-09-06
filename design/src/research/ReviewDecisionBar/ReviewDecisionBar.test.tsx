import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { REVIEW_DECISIONS, REVIEW_DECISION_META } from '../models';
import { ReviewDecisionBar } from './ReviewDecisionBar';

const AVAILABLE = ['accept', 'qualify', 'reject', 'defer'] as const;

describe('ReviewDecisionBar', () => {
  it('offers exactly the decisions the host says are available', () => {
    render(<ReviewDecisionBar available={AVAILABLE} onDecide={() => undefined} />);
    for (const decision of AVAILABLE) {
      expect(
        screen.getByRole('button', { name: REVIEW_DECISION_META[decision].label }),
      ).toBeInTheDocument();
    }
    expect(
      screen.queryByRole('button', { name: REVIEW_DECISION_META.request_more_evidence.label }),
    ).toBeNull();
  });

  it('is a named group', () => {
    render(<ReviewDecisionBar available={AVAILABLE} onDecide={() => undefined} />);
    expect(screen.getByRole('group', { name: 'Review decision' })).toBeInTheDocument();
  });

  it('reports the chosen decision from the keyboard', async () => {
    const user = userEvent.setup();
    const onDecide = vi.fn();
    render(<ReviewDecisionBar available={AVAILABLE} onDecide={onDecide} />);
    await user.tab();
    await user.keyboard('{Enter}');
    expect(onDecide).toHaveBeenCalledWith('accept');
  });

  it('prints the reason a read-only host cannot record a decision', () => {
    render(
      <ReviewDecisionBar
        available={AVAILABLE}
        disabledReason="This workspace is read-only here."
        onDecide={() => undefined}
      />,
    );
    expect(screen.getByText('This workspace is read-only here.')).toBeInTheDocument();
    for (const decision of AVAILABLE) {
      expect(screen.getByRole('button', { name: REVIEW_DECISION_META[decision].label })).toBeDisabled();
    }
    expect(screen.getByRole('group')).toHaveAttribute('data-blocked', 'true');
  });

  it('spins only the decision being recorded and holds the others', () => {
    render(<ReviewDecisionBar available={AVAILABLE} busy="accept" onDecide={() => undefined} />);
    const accept = screen.getByRole('button', { name: /Accept/ });
    expect(accept).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled();
  });

  it('records no decision with a destructive variant', () => {
    // Every decision here is a considered, recoverable record: rejecting marks the
    // candidate reviewed and destroys nothing that was accepted. Danger is reserved for
    // an action that loses work, so no review decision may claim it.
    expect(Object.values(REVIEW_DECISION_META).map((meta) => meta.variant)).not.toContain(
      'danger',
    );
    render(<ReviewDecisionBar available={AVAILABLE} onDecide={() => undefined} />);
    expect(screen.getByRole('button', { name: 'Reject' })).toHaveAttribute(
      'data-variant',
      'secondary',
    );
  });

  it('paints Accept with the primary action fill and no scientific status colour', () => {
    render(<ReviewDecisionBar available={AVAILABLE} onDecide={() => undefined} />);
    // `primary` is the neutral inverse fill; `accent` marks model activity and never says
    // whether a claim is true. Weight on this button comes from the confirmation, not hue.
    expect(screen.getByRole('button', { name: 'Accept' })).toHaveAttribute(
      'data-variant',
      'primary',
    );
  });

  it('gives every decision an accessible description rather than a title attribute', () => {
    render(<ReviewDecisionBar available={REVIEW_DECISIONS} onDecide={() => undefined} />);
    for (const decision of REVIEW_DECISIONS) {
      const button = screen.getByRole('button', { name: REVIEW_DECISION_META[decision].label });
      expect(button).toHaveAccessibleDescription(REVIEW_DECISION_META[decision].description);
      expect(button).not.toHaveAttribute('title');
    }
  });

  it('shows the focused decision’s description beneath the bar', async () => {
    const user = userEvent.setup();
    render(<ReviewDecisionBar available={AVAILABLE} onDecide={() => undefined} />);
    const hint = screen.getByTestId('rh-review-decision-hint');
    expect(hint).toBeEmptyDOMElement();

    for (const decision of AVAILABLE) {
      await user.tab();
      expect(hint).toHaveTextContent(REVIEW_DECISION_META[decision].description);
    }

    // Tabbing off the last decision leaves the line empty rather than stale.
    await user.tab();
    expect(hint).toBeEmptyDOMElement();
  });

  it('shows the hovered decision’s description without waiting for a tooltip', async () => {
    const user = userEvent.setup();
    render(<ReviewDecisionBar available={AVAILABLE} onDecide={() => undefined} />);
    await user.hover(screen.getByRole('button', { name: 'Qualify' }));
    expect(screen.getByTestId('rh-review-decision-hint')).toHaveTextContent(
      REVIEW_DECISION_META.qualify.description,
    );
    await user.unhover(screen.getByRole('button', { name: 'Qualify' }));
    expect(screen.getByTestId('rh-review-decision-hint')).toBeEmptyDOMElement();
  });

  it('has no accessibility violations, blocked or not', async () => {
    const { container } = render(
      <div>
        <ReviewDecisionBar available={REVIEW_DECISIONS} onDecide={() => undefined} />
        <ReviewDecisionBar
          available={REVIEW_DECISIONS}
          disabledReason="No write capability."
          onDecide={() => undefined}
        />
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('ReviewDecisionBar', () => (
  <ReviewDecisionBar available={REVIEW_DECISIONS} onDecide={() => undefined} />
));
