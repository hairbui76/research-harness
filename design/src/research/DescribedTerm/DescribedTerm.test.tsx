/**
 * A word that is not a badge still says what it means, and says it the same way.
 *
 * The properties asserted are the ones the craft floor fixes: the meaning is named for a
 * screen reader, printed for the eye when it is asked for, absent from the page until
 * then, never in a `title`, and never opened by a pointer merely passing over the word.
 *
 * Three gestures ask for it — focus, a pointer that rests, a long press — and they open
 * one sentence. The delay is what keeps wave two's rule: a pointer crossing the row on
 * its way to a link opens nothing.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import {
  DESCRIBED_TERM_HOVER_MS,
  DESCRIBED_TERM_PRESS_MS,
  DescribedTerm,
} from './DescribedTerm';

const SENTENCE = 'How directly the source supports the evidence.';

/**
 * The pointer gestures, dispatched rather than driven by `userEvent`.
 *
 * React derives `pointerenter` and `pointerleave` from `pointerover` and `pointerout`, so
 * those are what a test has to send; and the clock is this test's, because what is being
 * asserted is a delay — that a pointer passing over opens nothing and a pointer resting
 * does.
 */
function pointerRestsOn(element: Element, ms: number) {
  fireEvent.pointerOver(element, { pointerType: 'mouse' });
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

function pointerLeaves(element: Element) {
  fireEvent.pointerOut(element, { pointerType: 'mouse' });
}

/**
 * A finger, which jsdom will not build on its own.
 *
 * `fireEvent.pointerDown` drops `pointerType` — jsdom has no `PointerEvent` — and
 * `pointerType` is exactly what tells a long press from a click, so the event is built by
 * hand and the property defined on it.
 */
function fingerEvent(element: Element, type: 'pointerdown' | 'pointerup') {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, 'pointerType', { value: 'touch' });
  fireEvent(element, event);
}

afterEach(() => {
  vi.useRealTimers();
});

describe('DescribedTerm', () => {
  it('names the word by its own sentence, so the meaning is read out with it', () => {
    const { container } = render(<DescribedTerm description={SENTENCE}>Direct</DescribedTerm>);

    const word = container.querySelector('.rh-described-term__word');
    expect(word).toHaveTextContent('Direct');
    const describedBy = word?.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(container.querySelector(`#${describedBy}`)).toHaveTextContent(SENTENCE);
    expect(word).not.toHaveAttribute('title');
  });

  it('takes a tab stop, and prints the sentence under the word while it has focus', async () => {
    const user = userEvent.setup();
    const { container } = render(<DescribedTerm description={SENTENCE}>Direct</DescribedTerm>);

    const hint = (): Element | null => container.querySelector('.rh-described-term__hint');
    expect(hint()).toBeNull();

    await user.tab();
    expect(container.querySelector('.rh-described-term__word')).toHaveFocus();
    expect(hint()).toHaveTextContent(SENTENCE);
    // The visible half and the named half are one sentence, so only one reaches a screen
    // reader.
    expect(hint()).toHaveAttribute('aria-hidden', 'true');

    await user.tab();
    expect(hint()).toBeNull();
  });

  it('does not move the page under a pointer that is only passing over it', () => {
    vi.useFakeTimers();
    const { container } = render(<DescribedTerm description={SENTENCE}>Direct</DescribedTerm>);
    const word = container.querySelector('.rh-described-term__word')!;

    // Wave two's rule, kept by the delay rather than by refusing the pointer: a pointer
    // crossing this word on its way to the link beside it opens nothing.
    pointerRestsOn(word, DESCRIBED_TERM_HOVER_MS - 1);
    expect(container.querySelector('.rh-described-term__hint')).toBeNull();
    pointerLeaves(word);
    act(() => {
      vi.advanceTimersByTime(DESCRIBED_TERM_HOVER_MS * 2);
    });
    expect(container.querySelector('.rh-described-term__hint')).toBeNull();
  });

  it('prints the sentence for a pointer that rests on the word', () => {
    vi.useFakeTimers();
    const { container } = render(<DescribedTerm description={SENTENCE}>Direct</DescribedTerm>);
    const word = container.querySelector('.rh-described-term__word')!;

    pointerRestsOn(word, DESCRIBED_TERM_HOVER_MS);
    const hint = container.querySelector('.rh-described-term__hint');
    expect(hint).toHaveTextContent(SENTENCE);
    // The same sentence the keyboard opens, and hidden from a screen reader for the same
    // reason: it is already named by `aria-describedby`.
    expect(hint).toHaveAttribute('aria-hidden', 'true');

    act(() => {
      pointerLeaves(word);
    });
    expect(container.querySelector('.rh-described-term__hint')).toBeNull();
  });

  it('answers a long press by focusing the word, so a finger and Tab leave one state', () => {
    vi.useFakeTimers();
    const { container } = render(<DescribedTerm description={SENTENCE}>Direct</DescribedTerm>);
    const word = container.querySelector('.rh-described-term__word')!;

    fingerEvent(word, 'pointerdown');
    expect(container.querySelector('.rh-described-term__hint')).toBeNull();
    act(() => {
      vi.advanceTimersByTime(DESCRIBED_TERM_PRESS_MS);
    });

    expect(word).toHaveFocus();
    expect(container.querySelector('.rh-described-term__hint')).toHaveTextContent(SENTENCE);
  });

  it('opens nothing for a tap that lifts before the press is a press', () => {
    vi.useFakeTimers();
    const { container } = render(<DescribedTerm description={SENTENCE}>Direct</DescribedTerm>);
    const word = container.querySelector('.rh-described-term__word')!;

    fingerEvent(word, 'pointerdown');
    fingerEvent(word, 'pointerup');
    act(() => {
      vi.advanceTimersByTime(DESCRIBED_TERM_PRESS_MS * 2);
    });

    expect(container.querySelector('.rh-described-term__hint')).toBeNull();
  });

  it('says to a pointer that there is something to ask: a dotted underline and a cursor', () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const css = readFileSync(join(here, 'DescribedTerm.css'), 'utf8');
    const rule = /\.rh-described-term__word\[tabindex\] \{([^}]*)\}/.exec(css)?.[1] ?? '';

    expect(rule).toContain('underline');
    expect(rule).toContain('dotted');
    // The word's own ink, so the affordance never introduces a colour of its own.
    expect(rule).toContain('currentColor');
  });

  it('reaches for no tooltip: the meaning is on the page or nowhere', async () => {
    const user = userEvent.setup();
    render(<DescribedTerm description={SENTENCE}>Direct</DescribedTerm>);

    await user.tab();
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <dl>
        <div>
          <dt>Strength</dt>
          <dd>
            <DescribedTerm description={SENTENCE}>Direct</DescribedTerm>
          </dd>
        </div>
      </dl>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('DescribedTerm', () => (
  <DescribedTerm description={SENTENCE}>Direct</DescribedTerm>
));
