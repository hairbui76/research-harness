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

  /*
   * A workspace with no LaTeX toolchain has never compiled anything, and the panel used to
   * report that as "STARTED unknown time · FINISHED still running": one clock reading a
   * value it does not have, and one asserting that a build nobody started is in progress.
   * The build's own row says the absence once; the clocks say nothing until there is a
   * build to time.
   */
  it('reads no clock over a build that never started', () => {
    render(
      <CompilerStatus
        build={{
          status: 'failed',
          synctex: 'unavailable',
          setupGuidance: 'Install a LaTeX engine and add it to research.yaml.',
        }}
      />,
    );
    expect(screen.getByText('none yet')).toBeInTheDocument();
    expect(screen.queryByText('still running')).toBeNull();
    expect(screen.queryByText('unknown time')).toBeNull();
    expect(screen.queryByText('Started')).toBeNull();
    expect(screen.queryByText('Finished')).toBeNull();
  });

  /*
   * "Still running" belongs to the build that is running. A build that stopped without
   * recording an end — killed, or its record lost — is not running, and saying so would be
   * the same lie one state along.
   */
  it('does not call a stopped build with no end time a running one', () => {
    render(
      <CompilerStatus build={{ ...succeeded, status: 'failed', finishedAt: undefined }} />,
    );
    expect(screen.getByText('2026-09-03 09:59 UTC')).toBeInTheDocument();
    expect(screen.getByText('not recorded')).toBeInTheDocument();
    expect(screen.queryByText('still running')).toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <CompilerStatus build={{ ...succeeded, status: 'running' }} onStop={vi.fn()} />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('CompilerStatus', () => <CompilerStatus build={succeeded} />);
