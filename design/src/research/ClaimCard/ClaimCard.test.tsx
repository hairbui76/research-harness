import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { SAMPLE_CLAIM } from '../samples';
import { ClaimCard } from './ClaimCard';

describe('ClaimCard', () => {
  it('shows the claim sentence, its type and its scope', () => {
    render(<ClaimCard claim={SAMPLE_CLAIM} />);
    expect(screen.getByText(SAMPLE_CLAIM.text)).toBeInTheDocument();
    expect(screen.getByText('causal')).toBeInTheDocument();
    expect(screen.getByText(SAMPLE_CLAIM.scope)).toBeInTheDocument();
  });

  it('shows contradicting evidence beside supporting evidence, never instead of it', () => {
    const { container } = render(<ClaimCard claim={SAMPLE_CLAIM} />);
    const relations = Array.from(
      container.querySelectorAll('.rh-claim-card__support-item'),
    ).map((item) => item.getAttribute('data-relation'));
    expect(relations).toEqual(['supports', 'contradicts', 'qualifies']);
    const contradicts = container.querySelector('[data-relation="contradicts"]');
    expect(contradicts).toHaveTextContent('1');
    expect(contradicts).toHaveTextContent('contradict');
  });

  it('prints the wording ceiling in full', () => {
    render(<ClaimCard claim={SAMPLE_CLAIM} />);
    expect(screen.getByText(SAMPLE_CLAIM.wordingCeiling as string)).toBeInTheDocument();
  });

  it('reports which relation the researcher asked to see', async () => {
    const user = userEvent.setup();
    const onOpenSupport = vi.fn();
    render(<ClaimCard claim={SAMPLE_CLAIM} onOpenSupport={onOpenSupport} />);
    await user.click(screen.getByRole('button', { name: /contradict/ }));
    expect(onOpenSupport).toHaveBeenCalledWith('contradicts', SAMPLE_CLAIM);
  });

  it('opens the claim from the keyboard', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<ClaimCard claim={SAMPLE_CLAIM} onOpen={onOpen} />);
    await user.tab();
    await user.keyboard('{Enter}');
    expect(onOpen).toHaveBeenCalledWith(SAMPLE_CLAIM);
  });

  it('carries the authority it is given', () => {
    const { container } = render(<ClaimCard claim={SAMPLE_CLAIM} />);
    expect(container.querySelector('.rh-claim-card')).toHaveAttribute(
      'data-authority',
      'qualified',
    );
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <ClaimCard claim={SAMPLE_CLAIM} onOpen={() => undefined} onOpenSupport={() => undefined} />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('ClaimCard', () => <ClaimCard claim={SAMPLE_CLAIM} />);
