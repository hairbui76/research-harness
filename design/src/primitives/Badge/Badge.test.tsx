import { render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Badge } from './Badge';
import { STATUS_META, STATUS_NAMES } from './status';

describe('Badge', () => {
  it('renders a neutral badge with its children', () => {
    render(<Badge>42 works</Badge>);
    expect(screen.getByText('42 works')).toBeInTheDocument();
  });

  it.each(STATUS_NAMES)('states %s with an icon and a label, not colour alone', (status) => {
    const { container } = render(<Badge status={status} />);
    const badge = container.querySelector('.rh-badge');
    expect(badge).toHaveAttribute('data-status', status);
    expect(badge).toHaveTextContent(STATUS_META[status].label);
    expect(badge?.querySelector('svg')).toHaveAttribute('data-icon', STATUS_META[status].icon);
  });

  it('keeps every scientific status visually distinct from the others', () => {
    const classes = STATUS_NAMES.map((status) => `rh-badge--status-${status}`);
    expect(new Set(classes).size).toBe(STATUS_NAMES.length);
  });

  it('lets a caller override the label and the glyph', () => {
    const { container } = render(
      <Badge status="accepted" icon="quote">
        Accepted by review
      </Badge>,
    );
    expect(screen.getByText('Accepted by review')).toBeInTheDocument();
    expect(container.querySelector('svg')).toHaveAttribute('data-icon', 'quote');
  });

  it('draws text only when the icon is suppressed', () => {
    const { container } = render(<Badge icon={null}>Draft</Badge>);
    expect(container.querySelector('svg')).toBeNull();
  });

  it.each(['neutral', 'success', 'error', 'warning', 'info', 'accent'] as const)(
    'renders the %s feedback tone',
    (tone) => {
      const { container } = render(<Badge tone={tone}>Tone</Badge>);
      expect(container.querySelector('.rh-badge')).toHaveAttribute('data-tone', tone);
    },
  );

  it('forwards refs and classes', () => {
    const ref = createRef<HTMLSpanElement>();
    render(
      <Badge ref={ref} className="pinned">
        Pinned
      </Badge>,
    );
    expect(ref.current).toHaveClass('rh-badge', 'pinned');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        {STATUS_NAMES.map((status) => (
          <Badge key={status} status={status} />
        ))}
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('Badge', () => (
  <div>
    {STATUS_NAMES.map((status) => (
      <Badge key={status} status={status} />
    ))}
    <Badge tone="accent" icon="sparkles">
      Model proposed
    </Badge>
    <Badge tone="warning" size="sm">
      Rebuilding
    </Badge>
  </div>
));
