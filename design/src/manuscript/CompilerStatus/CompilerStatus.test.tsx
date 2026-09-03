import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { CompilerStatus } from './CompilerStatus';
import type { BuildModel } from '../models';

const succeeded: BuildModel = {
  buildId: 'B0007',
  status: 'succeeded',
  engine: 'latexmk -pdf',
  startedAt: '2026-09-03T09:59:48Z',
  finishedAt: '2026-09-03T10:00:12Z',
  pdf: { url: '/pdf', stale: false, producedAt: '2026-09-03T10:00:12Z' },
  synctex: 'available',
};

describe('CompilerStatus', () => {
  it('names the state, the engine and the timestamps', () => {
    render(<CompilerStatus build={succeeded} />);
    expect(screen.getByRole('status')).toHaveTextContent('Compiled');
    expect(screen.getByText('latexmk -pdf')).toBeInTheDocument();
    expect(screen.getByText('2026-09-03 09:59 UTC')).toBeInTheDocument();
    expect(screen.getByText('2026-09-03 10:00 UTC')).toBeInTheDocument();
    expect(screen.getByText('24s')).toBeInTheDocument();
  });

  it('shows progress and a stop control while running', async () => {
    const user = userEvent.setup();
    const onStop = vi.fn();
    render(
      <CompilerStatus
        build={{ ...succeeded, status: 'running', finishedAt: undefined }}
        onStop={onStop}
      />,
    );
    expect(screen.getByRole('progressbar')).toHaveAttribute('data-state', 'indeterminate');
    expect(screen.getByText('still running')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Stop' }));
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it('explains an unavailable synctex mapping instead of guessing', () => {
    render(
      <CompilerStatus
        build={{ ...succeeded, synctex: 'unavailable', synctexReason: 'the engine wrote no .synctex.gz' }}
      />,
    );
    expect(
      screen.getByText(
        'Source and PDF navigation is unavailable: the engine wrote no .synctex.gz',
      ),
    ).toBeInTheDocument();
  });

  it('carries setup guidance and the last good PDF forward through a failure', () => {
    render(
      <CompilerStatus
        build={{
          status: 'failed',
          synctex: 'unavailable',
          setupGuidance: 'Install a LaTeX engine and add it to research.yaml.',
          lastGood: { url: '/pdf', producedAt: '2026-09-03T09:41:00Z' },
        }}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Compilation failed');
    expect(screen.getByText('Install a LaTeX engine and add it to research.yaml.')).toBeInTheDocument();
    expect(screen.getByText('Last successful PDF: 2026-09-03 09:41 UTC')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <CompilerStatus build={{ ...succeeded, status: 'running' }} onStop={vi.fn()} />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('CompilerStatus', () => <CompilerStatus build={succeeded} />);
