import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Progress } from './Progress';

describe('Progress', () => {
  it('reports a determinate value with a text alternative', () => {
    render(<Progress label="Compiling manuscript" value={30} showValue />);
    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAccessibleName('Compiling manuscript');
    expect(bar).toHaveAttribute('aria-valuenow', '30');
    expect(bar).toHaveAttribute('aria-valuemin', '0');
    expect(bar).toHaveAttribute('aria-valuemax', '100');
    expect(bar).toHaveAttribute('aria-valuetext', '30%');
    expect(screen.getByText('30%')).toBeInTheDocument();
  });

  it('scales against a custom max and clamps out-of-range values', () => {
    const { rerender } = render(<Progress label="Pages" value={3} max={12} />);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '3');
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuemax', '12');

    rerender(<Progress label="Pages" value={99} max={12} />);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '12');
  });

  it('omits the value when indeterminate', () => {
    render(<Progress label="Rebuilding index" indeterminate showValue />);
    const bar = screen.getByRole('progressbar');
    expect(bar).not.toHaveAttribute('aria-valuenow');
    expect(bar).toHaveAttribute('data-state', 'indeterminate');
    expect(screen.getByText('Working…')).toBeInTheDocument();
  });

  it('accepts a spoken value that is not a percentage', () => {
    render(<Progress label="Pages" value={3} max={12} valueText="3 of 12 pages" />);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuetext', '3 of 12 pages');
  });

  it('has no axe violations', async () => {
    const { container } = render(<Progress label="Compiling manuscript" value={30} />);
    await expectNoAxeViolations(container);
  });

  describeThemeDensitySnapshots('Progress', () => (
    <Progress label="Compiling manuscript" value={30} showValue />
  ));
});
