import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { AuditFindingList } from './AuditFinding';
import type { AuditFindingModel } from '../models';

const findings: AuditFindingModel[] = [
  {
    id: 'A1',
    kind: 'unsupported_statement',
    severity: 'error',
    file: 'manuscript/main.tex',
    line: 88,
    message: 'No accepted Evidence supports "the effect doubles under load".',
    source: 'audit',
  },
  {
    id: 'A2',
    kind: 'wording_stronger_than_claim',
    severity: 'warning',
    file: 'manuscript/main.tex',
    line: 91,
    message: '"proves" overstates C0041, which is qualified to one dataset.',
    claim: { id: 'C0041', label: 'C0041' },
    source: 'audit',
  },
  {
    id: 'A3',
    kind: 'invalid_anchor',
    severity: 'info',
    message: 'The anchor for E0482 no longer resolves in A0017-3.',
    anchor: { id: 'AN0012' },
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
  it('leads each row with the audit kind, not a compiler severity word', () => {
    render(<AuditFindingList findings={findings} />);
    expect(screen.getByText('Unsupported statement')).toBeInTheDocument();
    expect(screen.getByText('Wording stronger than the claim')).toBeInTheDocument();
    expect(screen.getByText('Invalid source anchor')).toBeInTheDocument();
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

  it('opens the source position and follows the claim or anchor it names', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onNavigate = vi.fn();
    render(<AuditFindingList findings={findings} onOpen={onOpen} onNavigate={onNavigate} />);

    await user.click(screen.getByRole('button', { name: /No accepted Evidence supports/ }));
    expect(onOpen).toHaveBeenCalledWith('manuscript/main.tex', 88);

    await user.click(screen.getByRole('button', { name: 'C0041' }));
    expect(onNavigate).toHaveBeenCalledWith({ kind: 'claim', id: 'C0041' });

    await user.click(screen.getByRole('button', { name: 'AN0012' }));
    expect(onNavigate).toHaveBeenCalledWith({ kind: 'anchor', id: 'AN0012' });
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
