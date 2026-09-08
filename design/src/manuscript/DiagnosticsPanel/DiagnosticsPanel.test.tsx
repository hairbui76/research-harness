import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { DiagnosticsPanel } from './DiagnosticsPanel';
import type { AuditFindingModel, DiagnosticModel } from '../models';

const diagnostics: DiagnosticModel[] = [
  {
    id: 'D1',
    severity: 'error',
    file: 'manuscript/main.tex',
    line: 120,
    message: 'Undefined control sequence.',
    source: 'compiler',
  },
];

const findings: AuditFindingModel[] = [
  {
    id: 'A1',
    kind: 'citation_mismatch',
    severity: 'error',
    file: 'manuscript/main.tex',
    line: 44,
    sentence: 'Earlier sweeps report the same ordering on held-out traffic.',
    message: 'the key "smith2024" is cited but missing from refs.bib',
    source: 'audit',
  },
  {
    id: 'A2',
    kind: 'stale_claim',
    severity: 'warning',
    sentence: 'The gain is concentrated in the two rarest attack families.',
    message: 'C0041 moved since this paragraph was written',
    claim: { id: 'C0041' },
    source: 'audit',
  },
];

describe('DiagnosticsPanel', () => {
  it('keeps compiler output and scientific audit under separate headings and counts', () => {
    render(<DiagnosticsPanel diagnostics={diagnostics} findings={findings} />);

    const compiler = screen.getByRole('region', { name: /Compiler diagnostics/ });
    const audit = screen.getByRole('region', { name: /Scientific audit/ });
    expect(compiler).not.toBe(audit);
    expect(within(compiler).getByText('1 message')).toBeInTheDocument();
    expect(within(audit).getByText('2 findings')).toBeInTheDocument();

    // The audit rows are not inside the compiler section, and vice versa.
    expect(within(compiler).queryByText('Citation mismatch')).not.toBeInTheDocument();
    expect(within(audit).queryByText('Undefined control sequence.')).not.toBeInTheDocument();
  });

  it('reports a clean compile and a dirty audit at the same time without merging them', () => {
    render(<DiagnosticsPanel diagnostics={[]} findings={findings} />);
    expect(screen.getByText('No compiler errors or warnings')).toBeInTheDocument();
    expect(screen.getByText('Citation mismatch')).toBeInTheDocument();
  });

  it('renders the build status slot above both lists', () => {
    render(
      <DiagnosticsPanel
        diagnostics={diagnostics}
        findings={findings}
        status={<p data-testid="status">Compiled 12s ago</p>}
      />,
    );
    expect(screen.getByTestId('status')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <DiagnosticsPanel
        diagnostics={diagnostics}
        findings={findings}
        onOpenSource={vi.fn()}
        onNavigate={vi.fn()}
      />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('DiagnosticsPanel', () => (
  <DiagnosticsPanel diagnostics={diagnostics} findings={findings} />
));
