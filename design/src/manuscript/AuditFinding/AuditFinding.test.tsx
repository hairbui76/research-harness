import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { AuditFindingList } from './AuditFinding';
import type { AuditFindingModel } from '../models';

const UNANCHORED_SENTENCE =
  'The pretrained encoder improves F1 by 2.57 points over the strongest baseline.';

const findings: AuditFindingModel[] = [
  {
    id: 'A1',
    kind: 'unregistered_claim',
    severity: 'error',
    file: 'manuscript/main.tex',
    line: 88,
    sentence: UNANCHORED_SENTENCE,
    message: 'substantive sentence is attached to no Claim',
    source: 'audit',
  },
  {
    id: 'A2',
    kind: 'over_strong_wording',
    severity: 'warning',
    file: 'manuscript/main.tex',
    line: 91,
    sentence: 'This proves that pretraining transfers to every rare family.',
    message: "sentence reads L4 universal or absence via 'every', but C0041 allows only L2",
    claim: { id: 'C0041', label: 'C0041' },
    source: 'audit',
  },
  {
    id: 'A3',
    kind: 'invalid_evidence_anchor',
    severity: 'info',
    sentence: 'The held-out split is the only evidence that the encoder generalises.',
    message: 'E0482 no longer opens at its source, so C0005 is unprovenanced',
    anchor: { id: 'manuscript/main.tex:12' },
    source: 'audit',
  },
  {
    id: 'A4',
    kind: 'novel_rule_from_the_daemon',
    severity: 'warning',
    message: 'An audit kind this package has never heard of still renders.',
    source: 'audit',
  },
];

describe('AuditFindingList', () => {
  /**
   * The card used to open with a bracketed severity chip — an 11px uppercase word over the
   * kind, which is the eyebrow DESIGN.md bans. It opens with the manuscript now: the
   * researcher reads their own sentence before reading a verdict on it.
   */
  it('opens a finding with the manuscript’s own sentence, quoted', () => {
    render(<AuditFindingList findings={findings} />);
    const [first] = screen.getAllByRole('listitem');

    expect(first?.firstElementChild?.tagName).toBe('BLOCKQUOTE');
    expect(first?.textContent?.startsWith(UNANCHORED_SENTENCE)).toBe(true);
  });

  it('sets no heading, so nothing can sit over one as a kicker', () => {
    const { container } = render(<AuditFindingList findings={findings} />);
    expect(screen.queryAllByRole('heading')).toHaveLength(0);
    expect(container.querySelector('.rh-text-label')).toBeNull();
  });

  it('leads the finding with the audit kind, in the words the daemon’s vocabulary uses', () => {
    render(<AuditFindingList findings={findings} />);
    expect(screen.getByText('Unregistered claim')).toBeInTheDocument();
    expect(screen.getByText('Wording stronger than the Claim')).toBeInTheDocument();
    expect(screen.getByText('Invalid evidence anchor')).toBeInTheDocument();
    // An unregistered kind is humanised rather than dropped.
    expect(screen.getByText('Novel rule from the daemon')).toBeInTheDocument();
  });

  it('uses its own severity vocabulary so it cannot be read as compiler output', () => {
    render(<AuditFindingList findings={findings} />);
    expect(screen.getByText('Must fix')).toBeInTheDocument();
    expect(screen.getAllByText('Review')).toHaveLength(2);
    expect(screen.getByText('Note')).toBeInTheDocument();
    expect(screen.queryByText('Error')).not.toBeInTheDocument();
    expect(screen.queryByText('Warning')).not.toBeInTheDocument();
  });

  it('says what its severity means, on the page rather than in a tooltip', () => {
    render(<AuditFindingList findings={findings} />);
    expect(screen.getByText(/cannot ship as it stands/)).toBeInTheDocument();
    expect(screen.getAllByText(/has to decide about this/)).toHaveLength(2);
  });

  it('draws the severity in the scientific status family, never a feedback tone', () => {
    const { container } = render(<AuditFindingList findings={findings} />);
    const statuses = [...container.querySelectorAll('.rh-badge')].map((badge) =>
      badge.getAttribute('data-status'),
    );
    expect(statuses).toEqual(['contested', 'candidate', 'qualified', 'candidate']);
  });

  /**
   * The row used to end in a strip of reference chips — a claim id, an anchor key — which
   * is a lint tool's answer to "what now". Each card names one act instead, chosen by the
   * kind: wording that overstates its Claim is answered by reading the Claim, and a
   * sentence attached to nothing is answered in the source.
   */
  it('ends each card with the one act its kind asks for', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onNavigate = vi.fn();
    render(<AuditFindingList findings={findings} onOpen={onOpen} onNavigate={onNavigate} />);
    const cards = screen.getAllByRole('listitem');

    const [unregistered, overStrong, brokenAnchor, unknown] = cards;
    expect(within(unregistered as HTMLElement).getAllByRole('button')).toHaveLength(1);
    expect(
      within(overStrong as HTMLElement).getAllByRole('button')[0],
    ).toHaveAccessibleName('Open C0041');
    expect(within(unknown as HTMLElement).queryAllByRole('button')).toHaveLength(0);

    await user.click(within(unregistered as HTMLElement).getByRole('button'));
    expect(onOpen).toHaveBeenCalledWith('manuscript/main.tex', 88);

    await user.click(within(overStrong as HTMLElement).getByRole('button', { name: 'Open C0041' }));
    expect(onNavigate).toHaveBeenCalledWith({ kind: 'claim', id: 'C0041' });

    // With no file of its own, the finding still opens the sentence its anchor names.
    await user.click(
      within(brokenAnchor as HTMLElement).getByRole('button', {
        name: 'Open the anchored sentence',
      }),
    );
    expect(onNavigate).toHaveBeenCalledWith({ kind: 'anchor', id: 'manuscript/main.tex:12' });
  });

  it('keeps the source reachable even where the Claim is the first act', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<AuditFindingList findings={findings} onOpen={onOpen} onNavigate={vi.fn()} />);
    const overStrong = screen.getAllByRole('listitem')[1] as HTMLElement;

    await user.click(within(overStrong).getByRole('button', { name: 'Open the sentence' }));
    expect(onOpen).toHaveBeenCalledWith('manuscript/main.tex', 91);
  });

  it('is static text when the host can neither open a position nor follow a reference', () => {
    render(<AuditFindingList findings={findings} />);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });

  it('shows an empty state rather than an empty list', () => {
    render(<AuditFindingList findings={[]} />);
    expect(screen.getByText('No audit findings')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <AuditFindingList findings={findings} onOpen={vi.fn()} onNavigate={vi.fn()} />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('AuditFindingList', () => (
  <AuditFindingList findings={findings} onOpen={() => undefined} onNavigate={() => undefined} />
));
