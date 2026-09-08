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
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DESCRIBED_TERM_HOVER_MS, DESCRIBED_TERM_PRESS_MS } from '@research-harness/design';
import {
  DataTable,
  Empty,
  ErrorBox,
  Field,
  Fields,
  Loading,
  StatusBadge,
  TONES,
  candidateName,
  clockTime,
  fieldLabel,
} from './Feedback';
import { expectNoAxeViolations } from '../test/harness';

/**
 * A pointer that rests on a word, and a finger that holds it.
 *
 * React derives `pointerenter` from `pointerover`, and jsdom has no `PointerEvent` to
 * carry `pointerType` — the property that tells a long press from a click — so the touch
 * events are built by hand. The clock is the test's, because what is asserted is a delay.
 */
function pointerRestsOn(element: Element, ms: number) {
  fireEvent.pointerOver(element, { pointerType: 'mouse' });
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

function pointerLeaves(element: Element) {
  act(() => {
    fireEvent.pointerOut(element, { pointerType: 'mouse' });
  });
}

function fingerHolds(element: Element, ms: number) {
  const down = new Event('pointerdown', { bubbles: true, cancelable: true });
  Object.defineProperty(down, 'pointerType', { value: 'touch' });
  fireEvent(element, down);
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

afterEach(() => {
  vi.useRealTimers();
});

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
    // A pointer only passing over the badge leaves the row where it was: the sentence
    // waits for a pointer that stays, so one crossing the row on its way to a link opens
    // nothing.
    await user.hover(badge);
    expect(container.querySelector('.rh-authority-badge__hint')).toBeNull();

    await user.tab();
    expect(container.querySelector('.rh-authority-badge__hint')).toHaveTextContent(
      /confirmed part of it/,
    );
  });

  it('makes the meaning reachable to a pointer that rests on the badge', () => {
    vi.useFakeTimers();
    const { container } = render(
      <StatusBadge status="partially_supported" vocabulary="verdict" describe />,
    );
    const badge = container.querySelector('.rh-badge')!;

    // One rest, watched across the moment it becomes a rest: a pointer crossing the row
    // is gone before this, and a pointer asking the question is still here after it.
    pointerRestsOn(badge, DESCRIBED_TERM_HOVER_MS - 1);
    expect(container.querySelector('.rh-authority-badge__hint')).toBeNull();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(container.querySelector('.rh-authority-badge__hint')).toHaveTextContent(
      /confirmed part of it/,
    );

    pointerLeaves(badge);
    expect(container.querySelector('.rh-authority-badge__hint')).toBeNull();
  });

  it('answers a long press, which is the only gesture a finger has', () => {
    vi.useFakeTimers();
    const { container } = render(
      <StatusBadge status="partially_supported" vocabulary="verdict" describe />,
    );
    const badge = container.querySelector('.rh-badge')!;

    fingerHolds(badge, DESCRIBED_TERM_PRESS_MS);
    // The press focuses the badge, so a finger and a Tab key leave one state behind them.
    expect(badge).toHaveFocus();
    expect(container.querySelector('.rh-authority-badge__hint')).toHaveTextContent(
      /confirmed part of it/,
    );
  });

  it('stays out of the tab order when it is not describing itself', () => {
    const { container } = render(<StatusBadge status="routine" vocabulary="reviewCategory" />);
    expect(container.querySelector('.rh-badge')).not.toHaveAttribute('tabindex');
  });

  /*
   * The slot, asserted as the rule it is.
   *
   * jsdom lays nothing out, so the browser suite is where the row is measured holding
   * still (`browser-tests/vocabulary.spec.ts`). What can be asserted here is the rule that
   * makes it hold: in a queue row and in a table cell, the sentence is not a box inside the
   * row — the wrapper disappears, and the sentence takes a full line that contributes
   * nothing to what the row or the column asks for.
   */
  it('gives a row’s sentence a line of its own, and no width of its own', () => {
    const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'styles.css'), 'utf8');
    const wrapper =
      /\.rh-web-row \.rh-authority-badge__described,\s*\.rh-web-row \.rh-described-term \{([^}]*)\}/.exec(
        css,
      )?.[1] ?? '';
    const hint =
      /\.rh-web-row \.rh-authority-badge__hint,\s*\.rh-web-row \.rh-described-term__hint \{([^}]*)\}/.exec(
        css,
      )?.[1] ?? '';

    // The sentence is a member of the row, not of a box inside it that would widen.
    expect(wrapper, 'the row keeps the sentence inside a box').toContain('display: contents');
    // It is laid out after every word, because in the source it stands between its own
    // badge and the next one, and a line breaking there would push that one down.
    expect(hint, 'the sentence breaks the line where it stands').toContain('order: 1');
    // A definite width contributes exactly that much to intrinsic sizing, so the sentence
    // widens neither the row nor a table column every other row shares…
    expect(hint, 'the sentence sets a width of its own').toContain('inline-size: 0');
    // …and the percentage minimum is what gives it the whole line to be read on.
    expect(hint, 'the sentence is denied its own line').toContain('min-inline-size: 100%');
  });

  it('has no automatically detectable accessibility violation while describing itself', async () => {
    const { container } = render(
      <StatusBadge status="high_risk" vocabulary="reviewCategory" describe />,
    );
    await expectNoAxeViolations(container);
  });
});

/**
 * A definition row whose value is one word of a vocabulary.
 *
 * The review screen prints most of its vocabulary as `<dd>`s rather than badges — the
 * absence state, the metadata facts — and a `<dd>` had no way to say what its word meant.
 * `Field` gets the mechanism the badge already has, in the same shape, so a reader learns
 * one gesture rather than two.
 */
describe('a definition row that carries a vocabulary word', () => {
  it('prints the vocabulary’s word for the daemon’s value', () => {
    render(
      <Fields>
        <Field label="State" vocabulary="negativeState" value="not_reported" />
      </Fields>,
    );

    expect(screen.getByText('Not reported')).toBeInTheDocument();
    expect(screen.queryByText('not_reported')).not.toBeInTheDocument();
  });

  it('leaves a row that was given children exactly as it was', () => {
    const { container } = render(
      <Fields>
        <Field label="Verifier">scripted/scripted-1</Field>
      </Fields>,
    );

    expect(screen.getByText('scripted/scripted-1')).toBeInTheDocument();
    expect(container.querySelector('.rh-described-term')).toBeNull();
    expect(container.querySelector('dd')).not.toHaveAttribute('tabindex');
  });

  it('makes the meaning reachable from the keyboard, with no title attribute', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <Fields>
        <Field label="State" vocabulary="negativeState" value="absent" describe />
      </Fields>,
    );

    const word = container.querySelector('.rh-described-term__word')!;
    expect(word).not.toHaveAttribute('title');
    const describedBy = word.getAttribute('aria-describedby');
    expect(container.querySelector(`#${describedBy}`)).toHaveTextContent(/audited conclusion/);

    expect(container.querySelector('.rh-described-term__hint')).toBeNull();
    // A pointer only passing over the word leaves the panel where it was: the sentence
    // waits for a pointer that stays.
    await user.hover(word);
    expect(container.querySelector('.rh-described-term__hint')).toBeNull();

    await user.tab();
    expect(container.querySelector('.rh-described-term__hint')).toHaveTextContent(
      /audited conclusion/,
    );
  });

  it('falls back to what the product states about the vocabulary itself', () => {
    const { container } = render(
      <Fields>
        <Field label="Strength" vocabulary="evidenceStrength" value="direct" describe />
      </Fields>,
    );

    const word = container.querySelector('.rh-described-term__word')!;
    expect(word).toHaveTextContent('Direct');
    expect(
      container.querySelector(`#${word.getAttribute('aria-describedby')}`),
    ).toHaveTextContent('How directly the source supports the evidence.');
  });

  it('stays plain text for a word the product says nothing about', () => {
    const { container } = render(
      <Fields>
        <Field label="Type" vocabulary="claimType" value="descriptive" describe />
      </Fields>,
    );

    expect(screen.getByText('Descriptive')).toBeInTheDocument();
    expect(container.querySelector('.rh-described-term')).toBeNull();
  });

  it('has no automatically detectable accessibility violation while describing itself', async () => {
    const { container } = render(
      <Fields>
        <Field label="State" vocabulary="negativeState" value="absent" describe />
      </Fields>,
    );
    await expectNoAxeViolations(container);
  });
});

/**
 * Which colour system a word may speak.
 *
 * DESIGN.md states the rule twice over — no scientific status colour on something that is
 * not a scientific state, no feedback tone on something that is — and in a badge those are
 * one rule, because `success`, `error` and `info` resolve to the accepted, contested and
 * candidate families themselves. So the test is a list: every word this module tones, and
 * what it is. A word that is a scientific state has no business here at all.
 */
describe('the colour a state is allowed to wear', () => {
  /** Every toned word, and the application condition it reports. */
  const FEEDBACK: Record<string, string> = {
    conflict: 'a review queue category: why the queue is holding this',
    high_risk: 'a review queue category',
    ambiguous: 'a review queue category',
    routine: 'a review queue category',
    contradicted: 'a verifier’s verdict: what an independent read said',
    partially_supported: 'a verifier’s verdict',
    missing: 'an anchor’s replay result',
    relocated: 'an anchor’s replay result',
    error: 'the kind of a notice',
    warning: 'the kind of a notice',
    info: 'the kind of a notice',
    unsupported:
      'a claim’s scientific state, kept on the contested red the row’s own marker already ' +
      'wears; moving it into that family would be the product classifying it, which is the ' +
      'researcher’s to do',
  };

  it('tones nothing but application feedback', () => {
    for (const value of Object.keys(TONES)) {
      expect(FEEDBACK[value], `"${value}" wears a tone with no reason on record`).toBeTruthy();
    }
  });

  it('spends the accepted green on accepted state and nowhere else', () => {
    // A verified extraction, a supported claim, a valid anchor and an included work are
    // all things a machine established. Only a persisted human decision creates authority,
    // and green is what says so.
    expect(Object.entries(TONES).filter(([, tone]) => tone === 'success')).toEqual([]);
    for (const value of ['verified', 'supported', 'valid', 'included']) {
      expect(TONES[value], `"${value}" is green again`).toBeUndefined();
    }
  });

  it('keeps the feedback amber off a candidate that simply has no verdict yet', () => {
    const { container } = render(
      <StatusBadge status="unverified" vocabulary="verdict">
        Unverified
      </StatusBadge>,
    );

    // It sits beside the scientific blue of `Candidate` on the same row, and an absent
    // verdict is not a warning: it is the resting state of every candidate ever staged.
    expect(container.querySelector('.rh-badge')).toHaveAttribute('data-tone', 'neutral');
    expect(container.querySelector('[data-icon]')).toHaveAttribute('data-icon', 'circle-dashed');
  });

  /**
   * Screening is a pipeline, not an authority: a discovery result, a screened candidate, a
   * corpus member, a rejection. `Included` used to wear the accepted green one column from
   * a count of accepted evidence, so a thousand-row corpus said "accepted" about
   * membership. All four are neutral now, and the glyph is what tells them apart — which
   * is the channel that survives greyscale anyway.
   */
  it.each([
    ['discovered', 'search'],
    ['screened', 'filter'],
    ['included', 'library'],
    ['excluded', 'circle-x'],
  ])('draws screening state %s neutral, told apart by its own glyph', (state, glyph) => {
    const { container } = render(<StatusBadge status={state} vocabulary="screeningState" />);

    expect(container.querySelector('.rh-badge')).toHaveAttribute('data-tone', 'neutral');
    expect(container.querySelector('[data-icon]')).toHaveAttribute('data-icon', glyph);
    expect(container.querySelector('.rh-badge')).not.toHaveAttribute('data-status');
  });

  it('still sends a scientific authority to its own family', () => {
    const { container } = render(<StatusBadge status="accepted" vocabulary="evidenceStatus" />);

    expect(container.querySelector('.rh-badge')).toHaveAttribute('data-status', 'accepted');
    expect(container.querySelector('.rh-badge')).not.toHaveAttribute('data-tone');
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

/**
 * One clock for the whole cockpit.
 *
 * The daemon composes every change stamp server-side on a twenty-four-hour clock
 * (`server/app.py::_human_moment` — "9 September, 01:50"), and the Overview prints those
 * a few hundred pixels under a header that read "Read at 01:50 AM" on an en-US machine.
 * One page, one minute, two clocks. The hour cycle is pinned so the two can never disagree
 * again, wherever the reader's locale would have put the meridiem.
 */
describe('the clock a sentence about age reads', () => {
  it('reads twenty-four hours, whatever the locale would have done', () => {
    expect(clockTime('2026-09-09T01:50:00Z')).toMatch(/^\d{2}:\d{2}$/);
    expect(clockTime('2026-09-09T13:50:00Z')).toMatch(/^\d{2}:\d{2}$/);
    expect(clockTime('2026-09-09T01:50:00Z')).not.toMatch(/[AP]M/i);
  });

  it('prints an instant it cannot parse as it came', () => {
    expect(clockTime('not an instant')).toBe('not an instant');
  });
});
