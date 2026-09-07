/**
 * The three states every research page shares.
 *
 * They are asserted here rather than eight times over because the pages agree to render
 * exactly these: a skeleton shaped like the content with one polite announcement, a
 * failure that keeps its retry, and an empty state that says what the page is for and
 * offers one real next step.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { DataTable, Empty, ErrorBox, Loading } from './Feedback';
import { expectNoAxeViolations } from '../test/harness';

describe('waiting for a read', () => {
  it('announces the wait once, politely, and draws no spinner', () => {
    const { container } = render(<Loading what="the claims" />);

    const announcements = screen.getAllByRole('status');
    expect(announcements).toHaveLength(1);
    expect(announcements[0]).toHaveTextContent('Reading the claims…');
    // The skeleton stands in for the content; the icon vocabulary for "spinning" is not here.
    expect(container.querySelector('.rh-skeleton')).toBeInTheDocument();
    expect(container.querySelector('[data-icon="loader"]')).not.toBeInTheDocument();
  });

  it('draws table rows for a table and panels for a run of cards', () => {
    const table = render(<Loading what="the stale set" shape="table" />);
    const rows = table.container.querySelectorAll('.rh-skeleton-group[data-direction="row"]');
    expect(rows.length).toBeGreaterThan(1);
    expect(rows[0]?.querySelectorAll('.rh-skeleton').length).toBeGreaterThan(1);
    table.unmount();

    const cards = render(<Loading what="the corpus" shape="cards" />);
    expect(cards.container.querySelectorAll('.rh-web-skeleton-card').length).toBeGreaterThan(1);
  });

  it('hides every placeholder bar from assistive technology', () => {
    const { container } = render(<Loading what="the corpus" shape="cards" />);

    for (const bar of container.querySelectorAll('.rh-skeleton, .rh-skeleton-group')) {
      expect(bar.closest('[aria-hidden="true"]')).not.toBeNull();
    }
  });

  it('has no automatically detectable accessibility violation', async () => {
    const { container } = render(<Loading what="the claims" shape="table" />);
    await expectNoAxeViolations(container);
  });
});

describe('an empty page', () => {
  it('states the fact, teaches what the page is for, and offers the next step', async () => {
    const user = userEvent.setup();
    const onAct = vi.fn();
    const { container } = render(
      <Empty
        description="The corpus holds the sources this project reads from."
        action={
          <button type="button" onClick={onAct}>
            Attach a source
          </button>
        }
      >
        No works in the corpus yet
      </Empty>,
    );

    expect(screen.getByText('No works in the corpus yet')).toBeInTheDocument();
    expect(
      screen.getByText('The corpus holds the sources this project reads from.'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Attach a source' }));
    expect(onAct).toHaveBeenCalledTimes(1);
    await expectNoAxeViolations(container);
  });

  it('still renders a bare title for a caller that passes nothing else', () => {
    const { container } = render(<Empty>Nothing is stale.</Empty>);

    expect(screen.getByText('Nothing is stale.')).toBeInTheDocument();
    expect(container.querySelector('.rh-state')).not.toHaveAttribute('data-flat');
  });

  it('names the state once, in the page’s own words', () => {
    render(<Empty>No works in the corpus yet</Empty>);

    expect(screen.getByText('No works in the corpus yet')).toBeInTheDocument();
    // The generic kind above the title would be a kicker repeating the sentence below it.
    expect(screen.queryByText('Nothing here yet')).not.toBeInTheDocument();
  });

  it('drops its own box when it sits inside a panel', () => {
    const { container } = render(<Empty flat>No decision recorded.</Empty>);
    expect(container.querySelector('.rh-state')).toHaveAttribute('data-flat');
  });
});

describe('a read that failed', () => {
  it('keeps the retry the caller supplied', async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    render(<ErrorBox error="the daemon is not answering" retry={retry} />);

    expect(screen.getByText('the daemon is not answering')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('offers no retry when there is nothing to retry', () => {
    render(<ErrorBox error="the daemon refused" />);
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
  });
});

describe('a research table', () => {
  /**
   * The wrapper is the queue: close rows, small gaps, tight cell padding. It is not a
   * second type scale — the critique measured these cells at 11.15px, under the size
   * anything meant to be read may be. `--rh-type-body-sm-size` is 13px now and
   * `.rh-web-table` clamps its computed size at `--rh-type-reading-min-size`, so the
   * density can stay exactly where it was.
   */
  it('keeps its compact rows', () => {
    const { container } = render(
      <DataTable label="Works" head={<tr><th>Title</th></tr>}>
        <tr>
          <td>A traffic classifier study</td>
        </tr>
      </DataTable>,
    );

    const table = container.querySelector('.rh-web-table');
    expect(table).toBeInTheDocument();
    expect(table?.closest('[data-density="compact"]')).not.toBeNull();
  });

  it('names the region a keyboard can reach when the table overflows', () => {
    const { container } = render(
      <DataTable label="Works" head={<tr><th>Title</th></tr>}>
        <tr>
          <td>A traffic classifier study</td>
        </tr>
      </DataTable>,
    );

    expect(screen.getByText('A traffic classifier study')).toBeInTheDocument();
    expect(container.querySelector('.rh-scroll-area')).toBeInTheDocument();
  });

  it('floors the cell size at the reading floor, at any density', () => {
    const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'styles.css'), 'utf8');
    const rule = /\.rh-web-table \{([^}]*)\}/.exec(css)?.[1] ?? '';

    expect(rule).toMatch(/font-size:\s*max\(/);
    expect(rule).toContain('--rh-type-reading-min-size');
    expect(rule).toContain('--rh-density-font-scale');
  });
});
