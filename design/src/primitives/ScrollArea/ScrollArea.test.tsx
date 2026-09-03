import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { ScrollArea } from './ScrollArea';

describe('ScrollArea', () => {
  it('stays out of the way when the content fits', () => {
    const { container } = render(
      <ScrollArea label="Transcript">
        <p>Short</p>
      </ScrollArea>,
    );
    const node = container.firstElementChild as HTMLElement;
    expect(node).not.toHaveAttribute('tabindex');
    expect(node).not.toHaveAttribute('role');
  });

  it('becomes a labelled tab stop once it scrolls', async () => {
    const user = userEvent.setup();
    render(
      <ScrollArea label="Transcript" scrollable maxHeight={200}>
        <p>Long transcript</p>
      </ScrollArea>,
    );
    const region = screen.getByRole('region', { name: 'Transcript' });
    expect(region).toHaveAttribute('tabindex', '0');
    await user.tab();
    expect(region).toHaveFocus();
  });

  it('keeps native scrolling and applies the requested axis', () => {
    render(
      <ScrollArea label="Table" orientation="horizontal" scrollable>
        <div>wide</div>
      </ScrollArea>,
    );
    const region = screen.getByRole('region', { name: 'Table' });
    expect(region).toHaveAttribute('data-orientation', 'horizontal');
    region.scrollLeft = 40;
    expect(region.scrollLeft).toBe(40);
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <ScrollArea label="Transcript" scrollable>
        <p>Long transcript</p>
      </ScrollArea>,
    );
    await expectNoAxeViolations(container);
  });

  describeThemeDensitySnapshots('ScrollArea', () => (
    <ScrollArea label="Transcript" scrollable maxHeight={200}>
      <p>Long transcript</p>
    </ScrollArea>
  ));
});
