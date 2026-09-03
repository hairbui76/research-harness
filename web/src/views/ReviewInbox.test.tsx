/**
 * Task 11.2: the inbox groups by the reason the daemon gave, in the daemon's order.
 *
 * The fixture is a real `review.inbox` response. What is asserted is that the view keeps
 * Product 24.2's order, shows the reason each item is waiting, and reports no confidence
 * number anywhere — the queue is about attention, not about how sure a model was (§43).
 */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import type { ReviewItem } from '../api/dto';
import { CATEGORY_ORDER, ReviewInboxPage, groupByCategory } from './ReviewInbox';
import { FIXTURES, expectNoAxeViolations, fakeDaemon, renderView } from '../test/harness';

const QUEUE = FIXTURES.reviewInbox as unknown as { items: ReviewItem[]; count: number };

describe('grouping', () => {
  it('keeps the queue order of Product 24.2 and drops the empty groups', () => {
    const grouped = groupByCategory(QUEUE.items);

    expect(grouped.map(([category]) => category)).toEqual(['high_risk', 'ambiguous', 'routine']);
    const order = grouped.map(([category]) => CATEGORY_ORDER.indexOf(category as never));
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });

  it('never reorders within a group: the server already ranked them', () => {
    const items = QUEUE.items.map((item) => ({ ...item, category: 'routine' as const }));
    const grouped = groupByCategory(items);
    const group = grouped[0]![1];
    expect(group.map((item) => item.candidate_id)).toEqual(items.map((item) => item.candidate_id));
  });
});

describe('the review inbox view', () => {
  it('renders each group with its count, the reasons, and the quoted span', async () => {
    const daemon = fakeDaemon({ capabilities: { 'review.inbox': QUEUE } });

    renderView(<ReviewInboxPage />, { daemon, route: '/review', path: '/review' });

    await waitFor(() => expect(screen.getByText(/3 waiting/)).toBeInTheDocument());
    expect(screen.getByText('High-risk scientific claims (1)')).toBeInTheDocument();
    expect(screen.getByText('Ambiguous extractions (1)')).toBeInTheDocument();
    expect(screen.getByText('Routine verified candidates (1)')).toBeInTheDocument();
    expect(screen.getByText('metric_result')).toBeInTheDocument();
    expect(screen.getByText('94.32')).toBeInTheDocument();
  });

  it('links every item to its own source-beside-decision screen', async () => {
    const daemon = fakeDaemon({ capabilities: { 'review.inbox': QUEUE } });

    renderView(<ReviewInboxPage />, { daemon, route: '/review', path: '/review' });

    await waitFor(() => expect(screen.getByText('metric_result')).toBeInTheDocument());
    const first = QUEUE.items[0]!;
    const link = screen.getByText(first.field).closest('a');
    expect(link).toHaveAttribute('href', `/review/${first.candidate_id}`);
  });

  it('shows no model-confidence number, because the daemon reports none', async () => {
    const daemon = fakeDaemon({ capabilities: { 'review.inbox': QUEUE } });

    const { container } = renderView(<ReviewInboxPage />, {
      daemon,
      route: '/review',
      path: '/review',
    });

    await waitFor(() => expect(screen.getByText('metric_result')).toBeInTheDocument());
    expect(container.textContent?.toLowerCase()).not.toContain('confidence');
  });

  it('says the queue is empty rather than rendering an empty table', async () => {
    const daemon = fakeDaemon({
      capabilities: { 'review.inbox': { count: 0, counts: {}, items: [] } },
    });

    renderView(<ReviewInboxPage />, { daemon, route: '/review', path: '/review' });

    await waitFor(() =>
      expect(screen.getByText('Nothing is waiting for review.')).toBeInTheDocument(),
    );
  });

  it('has no automatically detectable accessibility violation', async () => {
    const daemon = fakeDaemon({ capabilities: { 'review.inbox': QUEUE } });

    const { container } = renderView(<ReviewInboxPage />, {
      daemon,
      route: '/review',
      path: '/review',
    });

    await waitFor(() => expect(screen.getByText('metric_result')).toBeInTheDocument());
    await expectNoAxeViolations(container);
  });
});
