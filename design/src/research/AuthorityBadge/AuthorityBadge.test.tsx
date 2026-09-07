import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createRef } from 'react';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { STATUS_META } from '../../primitives/Badge';
import { AUTHORITY_LABELS } from '../models';
import { AuthorityBadge } from './AuthorityBadge';

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

  it('prints the sentence under the badge on focus, not only on hover', async () => {
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

    await user.hover(container.querySelector('.rh-authority-badge')!);
    expect(hint()).toHaveTextContent(STATUS_META.contested.description);
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
