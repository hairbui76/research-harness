/**
 * A word that is not a badge still says what it means, and says it the same way.
 *
 * The properties asserted are the ones the craft floor fixes: the meaning is named for a
 * screen reader, printed for the eye on focus, absent from the page until it is asked
 * for, never in a `title`, and never opened by a pointer merely passing over the word.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { DescribedTerm } from './DescribedTerm';

const SENTENCE = 'How directly the source supports the evidence.';

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

  it('does not move the page under a pointer that is only passing over it', async () => {
    const user = userEvent.setup();
    const { container } = render(<DescribedTerm description={SENTENCE}>Direct</DescribedTerm>);

    await user.hover(container.querySelector('.rh-described-term__word')!);
    expect(container.querySelector('.rh-described-term__hint')).toBeNull();
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
