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

  /**
   * The whole row used to be one button whose accessible name was the compiler's sentence,
   * which named the diagnostic rather than the act. The row is a card now, in the shape the
   * audit beside it uses, and the act at the end of it says what it does — and says it
   * differently for each row, so three diagnostics in one file are three distinct names.
   */
  it('says the severity in words and ends in the act that opens the position', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<CompilerDiagnosticList diagnostics={diagnostics} onOpen={onOpen} />);

    expect(screen.getByText('Error')).toBeInTheDocument();
    expect(screen.getByText('Warning')).toBeInTheDocument();
    expect(screen.getByText('line 120, column 3')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Open line 120' }));
    expect(onOpen).toHaveBeenCalledWith('manuscript/main.tex', 120);
    expect(screen.getByRole('button', { name: 'Open line 210' })).toBeInTheDocument();
  });

  it('sets the severity as the first word of the sentence, never as a chip over it', () => {
    const { container } = render(<CompilerDiagnosticList diagnostics={diagnostics} />);
    const [first] = container.querySelectorAll('.rh-diagnostic');

    // The severity opens the sentence the compiler wrote, in that sentence's own type.
    expect(first?.querySelector('.rh-diagnostic__found')?.textContent).toBe(
      'Error — Undefined control sequence \\includegraph.',
    );
    expect(first?.querySelector('.rh-text-label')).toBeNull();
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
