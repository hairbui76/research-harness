/**
 * The three states every research page shares.
 *
 * They are asserted here rather than eight times over because the pages agree to render
 * exactly these: a skeleton shaped like the content with one polite announcement, a
 * failure that keeps its retry, and an empty state that says what the page is for and
 * offers one real next step.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Empty, ErrorBox, Loading, StatusBadge, candidateName, fieldLabel } from './Feedback';
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

/**
 * The daemon's vocabularies on a badge.
 *
 * A researcher reads `High-risk scientific claims`, never `high_risk`, and — where the
 * word is one they have to tell apart from a neighbouring one — the meaning is on the page
 * rather than in a `title` nobody can reach.
 */
describe('a status badge', () => {
  it('says the vocabulary’s word, never the daemon’s identifier', () => {
    render(<StatusBadge status="high_risk" vocabulary="reviewCategory" />);

    expect(screen.getByText('High-risk scientific claims')).toBeInTheDocument();
    expect(screen.queryByText('high_risk')).not.toBeInTheDocument();
  });

  it('humanises a word no vocabulary was named for', () => {
    render(<StatusBadge status="partially_supported" />);
    expect(screen.getByText('Partially supported')).toBeInTheDocument();
  });

  it('keeps the scientific status family for an authority word', () => {
    const { container } = render(<StatusBadge status="contested" vocabulary="claimStatus" />);

    expect(container.querySelector('[data-authority="contested"]')).toBeInTheDocument();
    expect(screen.getByText('Contested')).toBeInTheDocument();
  });

  it('makes the meaning reachable from the keyboard, with no title attribute', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <StatusBadge status="partially_supported" vocabulary="verdict" describe />,
    );

    const badge = container.querySelector('.rh-badge')!;
    expect(badge).not.toHaveAttribute('title');
    const describedBy = badge.getAttribute('aria-describedby');
    expect(container.querySelector(`#${describedBy}`)).toHaveTextContent(/confirmed part of it/);

    expect(container.querySelector('.rh-authority-badge__hint')).toBeNull();
    await user.tab();
    expect(container.querySelector('.rh-authority-badge__hint')).toHaveTextContent(
      /confirmed part of it/,
    );
  });

  it('stays out of the tab order when it is not describing itself', () => {
    const { container } = render(<StatusBadge status="routine" vocabulary="reviewCategory" />);
    expect(container.querySelector('.rh-badge')).not.toHaveAttribute('tabindex');
  });

  it('has no automatically detectable accessibility violation while describing itself', async () => {
    const { container } = render(
      <StatusBadge status="high_risk" vocabulary="reviewCategory" describe />,
    );
    await expectNoAxeViolations(container);
  });
});

describe('what a staged candidate is called', () => {
  it('is the field’s word beside the work it was read from', () => {
    expect(fieldLabel('metric_result')).toBe('Metric result');
    expect(candidateName('metric_result', 'W0001')).toBe('Metric result · W0001');
  });

  it('humanises a field a project’s own schema declared', () => {
    expect(fieldLabel('traffic_representation_family')).toBe('Traffic representation family');
  });
});
