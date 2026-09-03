import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { SAMPLE_CLAIM_REF, SAMPLE_PROVENANCE } from '../samples';
import { ProvenancePath } from './ProvenancePath';

describe('ProvenancePath', () => {
  it('is an ordered list, so the chain has a direction for assistive technology', () => {
    const { container } = render(<ProvenancePath path={SAMPLE_PROVENANCE} />);
    expect(container.querySelector('ol')).not.toBeNull();
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
  });

  it('names each edge in words rather than leaving it to an arrow', () => {
    render(<ProvenancePath path={SAMPLE_PROVENANCE} />);
    expect(screen.getByText('supports')).toBeInTheDocument();
    expect(screen.getByText('anchored_at')).toBeInTheDocument();
  });

  it('shows a broken step where it breaks, not only at the end of the chain', () => {
    const { container } = render(<ProvenancePath path={SAMPLE_PROVENANCE} />);
    const steps = container.querySelectorAll('.rh-provenance-path__step');
    expect(steps[0]?.querySelector('[data-resolution="resolved"]')).not.toBeNull();
    expect(steps[2]?.querySelector('[data-resolution="stale"]')).not.toBeNull();
    expect(steps[2]).toHaveTextContent('Stale');
  });

  it('opens any step from the keyboard', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<ProvenancePath path={SAMPLE_PROVENANCE} onOpen={onOpen} />);
    await user.tab();
    await user.keyboard('{Enter}');
    expect(onOpen).toHaveBeenCalledWith(SAMPLE_CLAIM_REF);
  });

  it('is a navigation landmark with a name', () => {
    render(<ProvenancePath path={SAMPLE_PROVENANCE} label="Claim provenance" />);
    expect(screen.getByRole('navigation', { name: 'Claim provenance' })).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <ProvenancePath path={SAMPLE_PROVENANCE} onOpen={() => undefined} />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('ProvenancePath', () => (
  <ProvenancePath path={SAMPLE_PROVENANCE} />
));
