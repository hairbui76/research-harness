import { render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Badge } from '../Badge';
import { Card } from './Card';

describe('Card', () => {
  it('renders a div with a body by default', () => {
    const { container } = render(<Card>Evidence E0482</Card>);
    const card = container.firstElementChild;
    expect(card?.tagName.toLowerCase()).toBe('div');
    expect(card).toHaveClass('rh-card', 'rh-card--raised', 'rh-card--pad-md');
    expect(screen.getByText('Evidence E0482')).toBeInTheDocument();
  });

  it('renders the requested element', () => {
    const { container } = render(<Card as="section">Corpus</Card>);
    expect(container.firstElementChild?.tagName.toLowerCase()).toBe('section');
  });

  it('renders header and footer slots only when given', () => {
    const { container, rerender } = render(<Card>body</Card>);
    expect(container.querySelector('.rh-card__header')).toBeNull();
    expect(container.querySelector('.rh-card__footer')).toBeNull();

    rerender(
      <Card header={<span>Claim C0041</span>} footer={<span>updated today</span>}>
        body
      </Card>,
    );
    expect(container.querySelector('.rh-card__header')).toHaveTextContent('Claim C0041');
    expect(container.querySelector('.rh-card__footer')).toHaveTextContent('updated today');
  });

  it('brings its own ink on the paper reading surface', () => {
    const { container } = render(<Card surface="paper">Page 6</Card>);
    expect(container.firstElementChild).toHaveClass('rh-card--paper', 'rh-surface-paper');
  });

  it('forwards refs, className and style', () => {
    const ref = createRef<HTMLElement>();
    render(
      <Card ref={ref} className="pinned" style={{ width: '200px' }}>
        body
      </Card>,
    );
    expect(ref.current).toHaveClass('rh-card', 'pinned');
    expect(ref.current).toHaveStyle({ width: '200px' });
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <Card as="article" header={<Badge status="accepted" />} footer={<span>E0482</span>}>
        <p>Structured traffic increases detection recall.</p>
      </Card>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('Card', () => (
  <div>
    <Card header={<Badge status="candidate" />} footer={<span>C0041</span>}>
      A claim awaiting review.
    </Card>
    <Card surface="pane" padding="sm" hoverable>
      A pane card.
    </Card>
    <Card surface="paper" padding="lg">
      A page of a source.
    </Card>
  </div>
));
