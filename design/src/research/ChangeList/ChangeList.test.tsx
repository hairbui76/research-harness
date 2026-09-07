import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { ChangeList } from './ChangeList';
import type { ChangeListEntry } from './ChangeList';

const ENTRIES: ChangeListEntry[] = [
  {
    id: 'decision.accepted:D0002',
    kind: 'decision',
    label: 'accepted D0002: count only held-out splits',
    at: '2026-09-06T14:03:00+00:00',
    when: '6 September, 14:03',
    href: '/claims/C0001',
  },
  {
    id: 'evidence.accepted:E0001',
    kind: 'evidence',
    label: 'accepted evidence E0001 anchored in A0001-1',
    at: '2026-09-06T11:20:00+00:00',
    when: '6 September, 11:20',
  },
];

describe('ChangeList', () => {
  it('reads each change as a sentence with the moment it happened', () => {
    render(<ChangeList entries={ENTRIES} />);

    expect(screen.getByText(ENTRIES[0]!.label)).toBeInTheDocument();
    const moment = screen.getByText('6 September, 14:03');
    expect(moment.tagName).toBe('TIME');
    expect(moment).toHaveAttribute('dateTime', '2026-09-06T14:03:00+00:00');
  });

  it('names the kind of each change in words, never by glyph alone', () => {
    render(<ChangeList entries={ENTRIES} />);

    expect(screen.getByText('Decision')).toBeInTheDocument();
    expect(screen.getByText('Evidence')).toBeInTheDocument();
  });

  it('links a change that has somewhere to lead, and leaves the rest as text', () => {
    render(<ChangeList entries={ENTRIES} />);

    expect(screen.getByRole('link', { name: ENTRIES[0]!.label })).toHaveAttribute(
      'href',
      '/claims/C0001',
    );
    expect(screen.getAllByRole('link')).toHaveLength(1);
  });

  it('hands a click to the host rather than reloading the page', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<ChangeList entries={ENTRIES} onOpen={onOpen} />);

    await user.click(screen.getByRole('link', { name: ENTRIES[0]!.label }));

    expect(onOpen).toHaveBeenCalledWith(ENTRIES[0]);
  });

  it('is an ordered list, because the order is the newest-first order it was given', () => {
    const { container } = render(<ChangeList entries={ENTRIES} label="What changed" />);

    const list = container.querySelector('ol');
    expect(list).not.toBeNull();
    expect(screen.getByRole('list', { name: 'What changed' })).toBe(list);
    expect(container.querySelectorAll('li')).toHaveLength(2);
  });

  it('reads a kind it has never heard of rather than dropping the change', () => {
    render(
      <ChangeList
        entries={[
          {
            id: 'x',
            kind: 'taxonomy_revision',
            label: 'revised the transport taxonomy',
            at: '2026-09-06T09:00:00+00:00',
            when: '6 September, 09:00',
          },
        ]}
      />,
    );

    expect(screen.getByText('Taxonomy revision')).toBeInTheDocument();
    expect(screen.getByText('revised the transport taxonomy')).toBeInTheDocument();
  });

  it('puts the researcher in front of her own change, in words rather than a colour', () => {
    render(
      <ChangeList
        entries={[{ ...ENTRIES[1]!, by: 'researcher' }]}
        label="What changed since your last session"
      />,
    );

    const sentence = screen.getByText(/accepted evidence E0001/).closest('p');
    expect(sentence).toHaveTextContent('You accepted evidence E0001 anchored in A0001-1');
  });

  it('names the daemon for the ones it recorded', () => {
    render(
      <ChangeList
        entries={[
          {
            id: 'conflict.opened',
            kind: 'conflict',
            by: 'daemon',
            label: 'opened a conflict: two readings of Table 1 disagree',
            at: '2026-09-06T16:41:00+00:00',
            when: '6 September, 16:41',
          },
        ]}
      />,
    );

    expect(screen.getByText(/opened a conflict/).closest('p')).toHaveTextContent(
      'The daemon opened a conflict: two readings of Table 1 disagree',
    );
  });

  it('leaves a change the record does not attribute unattributed', () => {
    const { container } = render(<ChangeList entries={ENTRIES} />);

    const sentences = Array.from(container.querySelectorAll('.rh-change-list__what')).map(
      (node) => node.textContent,
    );
    expect(sentences).toEqual(ENTRIES.map((entry) => entry.label));
    expect(container.querySelector('.rh-change-list__by')).toBeNull();
  });

  it('says who acted inside the sentence, never as a badge', () => {
    const { container } = render(
      <ChangeList entries={[{ ...ENTRIES[0]!, by: 'researcher' }]} />,
    );

    const subject = container.querySelector('.rh-change-list__by');
    expect(subject).not.toBeNull();
    expect(subject!.closest('.rh-change-list__what')).not.toBeNull();
    expect(container.querySelectorAll('.rh-badge')).toHaveLength(0);
    // The row states it for a host that wants to style or test one side of the record.
    expect(container.querySelector('.rh-change-list__entry')).toHaveAttribute('data-by', 'researcher');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<ChangeList entries={ENTRIES} onOpen={() => undefined} />);
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('ChangeList', () => <ChangeList entries={ENTRIES} />);

describeThemeDensitySnapshots('ChangeList attributed', () => (
  <ChangeList
    entries={[
      { ...ENTRIES[0]!, by: 'researcher' },
      {
        id: 'conflict.opened',
        kind: 'conflict',
        by: 'daemon',
        label: 'opened a conflict: two readings of Table 1 disagree',
        at: '2026-09-06T16:41:00+00:00',
        when: '6 September, 16:41',
      },
    ]}
  />
));
