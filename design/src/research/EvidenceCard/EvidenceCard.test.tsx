import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { SAMPLE_EVIDENCE, SAMPLE_STALE_ANCHOR } from '../samples';
import { EvidenceCard } from './EvidenceCard';

describe('EvidenceCard', () => {
  it('leads with the quote and names the work', () => {
    const { container } = render(<EvidenceCard evidence={SAMPLE_EVIDENCE} />);
    expect(container.querySelector('.rh-evidence-card__quote')).toHaveTextContent(
      'Storage modulus rose from 1.2 to 8.4 kPa',
    );
    expect(screen.getByText(SAMPLE_EVIDENCE.workLabel)).toBeInTheDocument();
  });

  it('shows the extracted measurement with its unit and metric', () => {
    render(<EvidenceCard evidence={SAMPLE_EVIDENCE} />);
    expect(screen.getByText('8.4 kPa')).toBeInTheDocument();
    expect(screen.getByText('storage modulus')).toBeInTheDocument();
  });

  it('renders the authority it is given and never a control to change it', () => {
    const { container } = render(<EvidenceCard evidence={SAMPLE_EVIDENCE} />);
    expect(container.querySelector('.rh-evidence-card')).toHaveAttribute(
      'data-authority',
      'accepted',
    );
    expect(container.querySelectorAll('button')).toHaveLength(0);
  });

  it('marks the card stale when its anchor is stale', () => {
    const { container } = render(
      <EvidenceCard evidence={{ ...SAMPLE_EVIDENCE, anchor: SAMPLE_STALE_ANCHOR }} />,
    );
    expect(container.querySelector('.rh-evidence-card')).toHaveAttribute('data-stale', '');
  });

  it('opens the evidence and its anchor from the keyboard', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onOpenAnchor = vi.fn();
    render(
      <EvidenceCard evidence={SAMPLE_EVIDENCE} onOpen={onOpen} onOpenAnchor={onOpenAnchor} />,
    );
    await user.tab();
    await user.keyboard('{Enter}');
    expect(onOpen).toHaveBeenCalledWith(SAMPLE_EVIDENCE);
    await user.tab();
    await user.keyboard('{Enter}');
    expect(onOpenAnchor).toHaveBeenCalledWith(SAMPLE_EVIDENCE.anchor);
  });

  it('names the evidence with the name it is given, and prints no identifier then', () => {
    const { container } = render(
      <EvidenceCard evidence={SAMPLE_EVIDENCE} title="Metric result · W0001" />,
    );
    expect(screen.getByText('Metric result · W0001')).toBeInTheDocument();
    // 2E: the daemon's own identifier is addressable, never printed, once the card has
    // the name the page already calls this evidence by.
    expect(container).not.toHaveTextContent(SAMPLE_EVIDENCE.id);
    expect(container.querySelector('.rh-evidence-card')).toHaveAttribute(
      'data-evidence-id',
      SAMPLE_EVIDENCE.id,
    );
  });

  it('falls back to the object id when it is given no name', () => {
    const { container } = render(<EvidenceCard evidence={SAMPLE_EVIDENCE} />);
    expect(container.querySelector('.rh-evidence-card__id')).toHaveTextContent(
      SAMPLE_EVIDENCE.id,
    );
    expect(screen.getByText(SAMPLE_EVIDENCE.workLabel)).toBeInTheDocument();
  });

  it('drops the metadata grid when compact', () => {
    const { container } = render(<EvidenceCard evidence={SAMPLE_EVIDENCE} compact />);
    expect(container.querySelector('.rh-evidence-card__facts')).toBeNull();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <EvidenceCard evidence={SAMPLE_EVIDENCE} onOpen={() => undefined} />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('EvidenceCard', () => (
  <EvidenceCard evidence={SAMPLE_EVIDENCE} />
));
