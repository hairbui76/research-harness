import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { formatAnchorTarget } from '../models';
import { SAMPLE_ANCHOR, SAMPLE_STALE_ANCHOR } from '../samples';
import { SourceAnchor } from './SourceAnchor';

describe('SourceAnchor', () => {
  it('prints the whole target: artifact, page, block and span', () => {
    render(<SourceAnchor anchor={SAMPLE_ANCHOR} />);
    expect(screen.getByText(formatAnchorTarget(SAMPLE_ANCHOR))).toBeInTheDocument();
    expect(formatAnchorTarget(SAMPLE_ANCHOR)).toContain('A0017-3');
    expect(formatAnchorTarget(SAMPLE_ANCHOR)).toContain('p.6');
    expect(formatAnchorTarget(SAMPLE_ANCHOR)).toContain('B0081');
  });

  it('shows the quote in the block variant only', () => {
    const { container: inline } = render(<SourceAnchor anchor={SAMPLE_ANCHOR} />);
    expect(inline.querySelector('blockquote')).toBeNull();

    const { container: block } = render(<SourceAnchor anchor={SAMPLE_ANCHOR} variant="block" />);
    expect(block.querySelector('blockquote')).toHaveTextContent('Storage modulus rose');
  });

  it('marks a stale anchor in words', () => {
    const { container } = render(<SourceAnchor anchor={SAMPLE_STALE_ANCHOR} />);
    expect(container.querySelector('.rh-source-anchor')).toHaveAttribute('data-stale', '');
    expect(screen.getByText('Stale')).toBeInTheDocument();
  });

  it('opens the source from the keyboard without navigating the link', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<SourceAnchor anchor={SAMPLE_ANCHOR} onOpen={onOpen} />);
    await user.tab();
    await user.keyboard('{Enter}');
    expect(onOpen).toHaveBeenCalledWith(SAMPLE_ANCHOR);
  });

  it('is static when there is nothing to open', () => {
    const { container } = render(
      <SourceAnchor anchor={{ artifactId: 'A0001-1', page: 2 }} />,
    );
    expect(container.querySelector('a')).toBeNull();
    expect(container.querySelector('button')).toBeNull();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        <SourceAnchor anchor={SAMPLE_ANCHOR} onOpen={() => undefined} variant="block" />
        <SourceAnchor anchor={SAMPLE_STALE_ANCHOR} />
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('SourceAnchor', () => (
  <div>
    <SourceAnchor anchor={SAMPLE_ANCHOR} variant="block" />
    <SourceAnchor anchor={SAMPLE_STALE_ANCHOR} />
  </div>
));
