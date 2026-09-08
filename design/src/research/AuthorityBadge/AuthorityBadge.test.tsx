import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { STATUS_META } from '../../primitives/Badge';
import { DESCRIBED_TERM_HOVER_MS, DESCRIBED_TERM_PRESS_MS } from '../DescribedTerm';
import { AUTHORITY_LABELS } from '../models';
import { AuthorityBadge } from './AuthorityBadge';

/**
 * The pointer gestures, dispatched rather than driven by `userEvent`.
 *
 * React derives `pointerenter` and `pointerleave` from `pointerover` and `pointerout`, so
 * those are what a test has to send; and the clock is this test's, because what is asserted
 * is a delay — a pointer passing over the badge opens nothing, one resting on it does.
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

describe('AuthorityBadge', () => {
  it.each(AUTHORITY_LABELS)('states %s with a word and a glyph', (authority) => {
    const { container } = render(<AuthorityBadge authority={authority} />);
    const badge = container.querySelector('.rh-authority-badge');
    expect(badge).toHaveAttribute('data-authority', authority);
    expect(badge).toHaveTextContent(STATUS_META[authority].label);
    expect(badge?.querySelector('svg')).toHaveAttribute('data-icon', STATUS_META[authority].icon);
  });

  it('lets a surface override the wording without losing the state', () => {
    const { container } = render(
      <AuthorityBadge authority="qualified" label="Accepted for 3D cultures" />,
    );
    expect(screen.getByText('Accepted for 3D cultures')).toBeInTheDocument();
    expect(container.querySelector('.rh-authority-badge')).toHaveAttribute(
      'data-authority',
      'qualified',
    );
  });

  it('is not focusable unless it describes itself', () => {
    const { container } = render(<AuthorityBadge authority="accepted" />);
    expect(container.querySelector('.rh-authority-badge')).not.toHaveAttribute('tabindex');
  });

  it('names the badge by its own sentence, so the meaning is read out with it', () => {
    const { container } = render(<AuthorityBadge authority="contested" describe />);

    const badge = container.querySelector('.rh-authority-badge');
    const describedBy = badge?.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    expect(container.querySelector(`#${describedBy}`)).toHaveTextContent(
      STATUS_META.contested.description,
    );
    expect(badge).not.toHaveAttribute('title');
  });

  it('prints the sentence under the badge while it is being asked about', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <AuthorityBadge authority="contested" describe reason="Two accepted claims disagree." />,
    );

    const hint = (): Element | null => container.querySelector('.rh-authority-badge__hint');
    expect(hint()).toBeNull();

    await user.tab();
    expect(hint()).toHaveTextContent(STATUS_META.contested.description);
    expect(hint()).toHaveTextContent('Two accepted claims disagree.');
    // The visible half and the described half are the same sentence, so only one of them
    // may reach a screen reader.
    expect(hint()).toHaveAttribute('aria-hidden', 'true');

    await user.tab();
    expect(hint()).toBeNull();
  });

  it('does not move the page under a pointer that is only passing over it', () => {
    vi.useFakeTimers();
    const { container } = render(<AuthorityBadge authority="contested" describe />);
    const badge = container.querySelector('.rh-authority-badge')!;

    // A badge sits beside the links of its own row. A sentence that opened the instant a
    // pointer crossed it would push those links out from under the pointer aiming at them,
    // so the sentence waits for a pointer that stays.
    pointerRestsOn(badge, DESCRIBED_TERM_HOVER_MS - 1);
    expect(container.querySelector('.rh-authority-badge__hint')).toBeNull();
    pointerLeaves(badge);
    act(() => {
      vi.advanceTimersByTime(DESCRIBED_TERM_HOVER_MS * 2);
    });
    expect(container.querySelector('.rh-authority-badge__hint')).toBeNull();
  });

  it('prints the sentence for a pointer that rests on the badge', () => {
    vi.useFakeTimers();
    const { container } = render(<AuthorityBadge authority="contested" describe />);
    const badge = container.querySelector('.rh-authority-badge')!;

    pointerRestsOn(badge, DESCRIBED_TERM_HOVER_MS);
    expect(container.querySelector('.rh-authority-badge__hint')).toHaveTextContent(
      STATUS_META.contested.description,
    );

    pointerLeaves(badge);
    expect(container.querySelector('.rh-authority-badge__hint')).toBeNull();
  });

  it('answers a long press by focusing the badge, which is what a finger has', () => {
    vi.useFakeTimers();
    const { container } = render(<AuthorityBadge authority="contested" describe />);
    const badge = container.querySelector('.rh-authority-badge')!;

    fingerEvent(badge, 'pointerdown');
    act(() => {
      vi.advanceTimersByTime(DESCRIBED_TERM_PRESS_MS);
    });

    expect(badge).toHaveFocus();
    expect(container.querySelector('.rh-authority-badge__hint')).toHaveTextContent(
      STATUS_META.contested.description,
    );
  });

  it('says to a pointer that there is something to ask', () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const css = readFileSync(join(here, '..', '..', 'primitives', 'Badge', 'Badge.css'), 'utf8');
    const cursor = /\.rh-badge\[tabindex\] \{([^}]*)\}/.exec(css)?.[1] ?? '';
    const underline = /\.rh-badge\[tabindex\] \.rh-badge__label \{([^}]*)\}/.exec(css)?.[1] ?? '';

    expect(cursor).toContain('cursor: help');
    expect(underline).toContain('underline');
    expect(underline).toContain('dotted');
    // The badge's own ink: the affordance never introduces a colour of its own.
    expect(underline).toContain('currentColor');
  });

  it('reaches for no tooltip: the meaning is on the page or nowhere', () => {
    render(<AuthorityBadge authority="qualified" describe />);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('forwards a ref', () => {
    const ref = createRef<HTMLSpanElement>();
    render(<AuthorityBadge ref={ref} authority="accepted" />);
    expect(ref.current).toHaveClass('rh-authority-badge');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        {AUTHORITY_LABELS.map((authority) => (
          <AuthorityBadge key={authority} authority={authority} />
        ))}
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('AuthorityBadge', () => (
  <div>
    {AUTHORITY_LABELS.map((authority) => (
      <AuthorityBadge key={authority} authority={authority} />
    ))}
  </div>
));
