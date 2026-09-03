import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { CompilerDiagnosticList } from './CompilerDiagnostic';
import type { DiagnosticModel } from '../models';

const diagnostics: DiagnosticModel[] = [
  {
    id: 'D1',
    severity: 'error',
    file: 'manuscript/main.tex',
    line: 120,
    column: 3,
    message: 'Undefined control sequence \\includegraph.',
    code: 'Undefined control sequence',
    source: 'compiler',
  },
  {
    id: 'D2',
    severity: 'warning',
    file: 'manuscript/main.tex',
    line: 210,
    message: 'Overfull \\hbox (12.4pt too wide).',
    source: 'compiler',
  },
  {
    id: 'D3',
    severity: 'info',
    file: 'manuscript/refs.bib',
    line: 8,
    message: 'Entry "smith2024" has no year field.',
    source: 'compiler',
  },
];

describe('CompilerDiagnosticList', () => {
  it('groups rows by the file they were reported against', () => {
    render(<CompilerDiagnosticList diagnostics={diagnostics} />);
    const main = screen.getByRole('list', {
      name: 'Compiler diagnostics: manuscript/main.tex',
    });
    expect(within(main).getAllByRole('listitem')).toHaveLength(2);
    expect(
      screen.getByRole('list', { name: 'Compiler diagnostics: manuscript/refs.bib' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /manuscript\/refs\.bib/ })).toBeInTheDocument();
  });

  it('says the severity in words and opens the exact position', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<CompilerDiagnosticList diagnostics={diagnostics} onOpen={onOpen} />);

    expect(screen.getByText('Error')).toBeInTheDocument();
    expect(screen.getByText('Warning')).toBeInTheDocument();
    expect(screen.getByText('line 120, column 3')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Undefined control sequence/ }));
    expect(onOpen).toHaveBeenCalledWith('manuscript/main.tex', 120);
  });

  it('is static text when the host cannot open a position', () => {
    render(<CompilerDiagnosticList diagnostics={diagnostics} />);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });

  it('shows an empty state rather than an empty list', () => {
    render(<CompilerDiagnosticList diagnostics={[]} />);
    expect(screen.getByText('No compiler errors or warnings')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <CompilerDiagnosticList diagnostics={diagnostics} onOpen={vi.fn()} />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('CompilerDiagnosticList', () => (
  <CompilerDiagnosticList diagnostics={diagnostics} onOpen={() => undefined} />
));
