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

  /**
   * The four metadata facts are vocabulary words — `Experimental result`, `Direct`,
   * `Source observed` — and a first-timer met them on the review screen with nothing to
   * say what they meant (critique 2026-09-07, heuristic 10, Jordan). The host passes the
   * sentences the product states; the card makes them reachable the way the authority
   * badge above them already is.
   */
  it('makes a fact’s meaning reachable when it is given one', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <EvidenceCard
        evidence={SAMPLE_EVIDENCE}
        meanings={{ strength: 'How directly the source supports the evidence.' }}
      />,
    );

    const word = container.querySelector('.rh-described-term__word');
    expect(word).toHaveTextContent(SAMPLE_EVIDENCE.strength);
    expect(word).not.toHaveAttribute('title');
    const describedBy = word?.getAttribute('aria-describedby');
    expect(container.querySelector(`#${describedBy}`)).toHaveTextContent(
      'How directly the source supports the evidence.',
    );

    word?.dispatchEvent(new FocusEvent('focus', { bubbles: true }));
    await user.click(word!);
    expect(container.querySelector('.rh-described-term__hint')).toHaveTextContent(
      'How directly the source supports the evidence.',
    );
  });

  it('leaves a fact the product says nothing about out of the tab order', () => {
    const { container } = render(
      <EvidenceCard
        evidence={SAMPLE_EVIDENCE}
        meanings={{ strength: 'How directly the source supports the evidence.' }}
      />,
    );
    // One described fact, not four: `Work`, `Type` and `Origin` were given no sentence
    // here, so they stay plain text rather than offering a tab stop that leads nowhere.
    expect(container.querySelectorAll('.rh-described-term__word')).toHaveLength(1);
  });

  it('describes nothing at all when it is given no meanings', () => {
    const { container } = render(<EvidenceCard evidence={SAMPLE_EVIDENCE} />);
    expect(container.querySelector('.rh-described-term__word')).toBeNull();
    expect(container.querySelector('.rh-evidence-card__fact [tabindex]')).toBeNull();
  });

  it('opens a fact’s sentence beneath the terms, never inside the one it belongs to', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <EvidenceCard
        evidence={SAMPLE_EVIDENCE}
        meanings={{ strength: 'How directly the source supports the evidence.' }}
      />,
    );

    const word = container.querySelector('.rh-described-term__word');
    await user.click(word!);

    // The sentence is a child of the grid, after every fact — not a child of the fact it
    // describes. In the row it used to sit in it widened that fact to its own measure and
    // re-wrapped the whole row, which moved the terms beside it while the keyboard was on
    // its way to them; from a row of its own it moves nothing.
    const hint = container.querySelector('.rh-evidence-card__fact-hint');
    expect(hint).not.toBeNull();
    expect(hint!.parentElement).toHaveClass('rh-evidence-card__facts');
    expect(hint!.closest('.rh-evidence-card__fact')).toBeNull();
    const children = [...container.querySelector('.rh-evidence-card__facts')!.children];
    expect(children.indexOf(hint!)).toBe(children.length - 1);
  });

  it('drops the metadata grid when compact', () => {
    const { container } = render(<EvidenceCard evidence={SAMPLE_EVIDENCE} compact />);
    expect(container.querySelector('.rh-evidence-card__facts')).toBeNull();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <EvidenceCard
        evidence={SAMPLE_EVIDENCE}
        onOpen={() => undefined}
        meanings={{
          type: 'What kind of statement the evidence carries.',
          strength: 'How directly the source supports the evidence.',
          origin: 'Something the source measured or reported, visible in the artifact itself.',
        }}
      />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('EvidenceCard', () => (
  <EvidenceCard evidence={SAMPLE_EVIDENCE} />
));
