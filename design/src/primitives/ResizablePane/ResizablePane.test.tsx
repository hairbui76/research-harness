import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Pane, PaneGroup, PaneHandle, resizeAt } from './ResizablePane';

function Workspace({
  onLayoutChange,
  collapsible = false,
}: {
  onLayoutChange?: (sizes: number[]) => void;
  collapsible?: boolean;
}) {
  return (
    <PaneGroup onLayoutChange={onLayoutChange} defaultSizes={[30, 70]} aria-label="Workspace">
      <Pane minSize={15} collapsible={collapsible} collapsedSize={0}>
        Sessions
      </Pane>
      <PaneHandle label="Resize the session list" />
      <Pane minSize={20}>Conversation</Pane>
    </PaneGroup>
  );
}

function sizeOf(text: string): number {
  const pane = screen.getByText(text);
  return Number.parseFloat(pane.style.flexBasis);
}

describe('ResizablePane', () => {
  it('lays panes out from defaultSizes and exposes a separator', () => {
    render(<Workspace />);
    const separator = screen.getByRole('separator', { name: 'Resize the session list' });
    expect(separator).toHaveAttribute('aria-orientation', 'vertical');
    expect(separator).toHaveAttribute('aria-valuenow', '30');
    expect(separator).toHaveAttribute('aria-valuemin', '15');
    expect(separator).toHaveAttribute('aria-valuemax', '100');
    expect(separator).toHaveAttribute('tabindex', '0');
    expect(sizeOf('Sessions')).toBeCloseTo(30);
    expect(sizeOf('Conversation')).toBeCloseTo(70);
  });

  it('resizes with the arrow keys and reports the layout', async () => {
    const user = userEvent.setup();
    const onLayoutChange = vi.fn();
    render(<Workspace onLayoutChange={onLayoutChange} />);

    await user.tab();
    expect(screen.getByRole('separator')).toHaveFocus();

    await user.keyboard('{ArrowRight}');
    expect(sizeOf('Sessions')).toBeCloseTo(32);
    expect(sizeOf('Conversation')).toBeCloseTo(68);
    expect(onLayoutChange).toHaveBeenLastCalledWith([32, 68]);

    await user.keyboard('{ArrowLeft}{ArrowLeft}');
    expect(sizeOf('Sessions')).toBeCloseTo(28);

    // Shift takes the larger step.
    await user.keyboard('{Shift>}{ArrowRight}{/Shift}');
    expect(sizeOf('Sessions')).toBeCloseTo(38);
  });

  it('stops at min and max with Home and End and respects the neighbour minimum', async () => {
    const user = userEvent.setup();
    render(<Workspace />);
    const separator = screen.getByRole('separator');
    separator.focus();

    await user.keyboard('{Home}');
    expect(sizeOf('Sessions')).toBeCloseTo(15);

    await user.keyboard('{End}');
    // The second pane keeps its 20% minimum.
    expect(sizeOf('Sessions')).toBeCloseTo(80);
    expect(sizeOf('Conversation')).toBeCloseTo(20);
  });

  it('collapses and restores with Enter when the pane is collapsible', async () => {
    const user = userEvent.setup();
    render(<Workspace collapsible />);
    const separator = screen.getByRole('separator');
    separator.focus();

    await user.keyboard('{Enter}');
    expect(sizeOf('Sessions')).toBeCloseTo(0);
    expect(screen.getByText('Sessions')).toHaveAttribute('data-collapsed', '');
    expect(separator).toHaveAttribute('aria-valuenow', '0');
    expect(separator).toHaveAttribute('aria-valuemin', '0');

    await user.keyboard('{Enter}');
    expect(sizeOf('Sessions')).toBeCloseTo(30);
    expect(screen.getByText('Sessions')).not.toHaveAttribute('data-collapsed');
  });

  it('reports collapse through onCollapsedChange', async () => {
    const user = userEvent.setup();
    const onCollapsedChange = vi.fn();
    render(
      <PaneGroup defaultSizes={[30, 70]}>
        <Pane minSize={15} collapsible onCollapsedChange={onCollapsedChange}>
          Sessions
        </Pane>
        <PaneHandle label="Resize" />
        <Pane>Conversation</Pane>
      </PaneGroup>,
    );
    screen.getByRole('separator').focus();
    await user.keyboard('{Enter}');
    expect(onCollapsedChange).toHaveBeenLastCalledWith(true);
    await user.keyboard('{Enter}');
    expect(onCollapsedChange).toHaveBeenLastCalledWith(false);
  });

  it('drags with the mouse against the measured group size', () => {
    const { container } = render(<Workspace />);
    const group = container.querySelector('.rh-pane-group') as HTMLElement;
    vi.spyOn(group, 'getBoundingClientRect').mockReturnValue({
      width: 1000,
      height: 500,
      top: 0,
      left: 0,
      right: 1000,
      bottom: 500,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    const separator = screen.getByRole('separator');
    fireEvent.mouseDown(separator, { clientX: 300, clientY: 0 });
    fireEvent.mouseMove(document, { clientX: 400, clientY: 0 });
    expect(sizeOf('Sessions')).toBeCloseTo(40);
    fireEvent.mouseUp(document);

    // Movement after the release is ignored.
    fireEvent.mouseMove(document, { clientX: 900, clientY: 0 });
    expect(sizeOf('Sessions')).toBeCloseTo(40);
  });

  it('supports controlled sizes', async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [sizes, setSizes] = useState([50, 50]);
      return (
        <>
          <span data-testid="sizes">{sizes.map((size) => Math.round(size)).join(',')}</span>
          <PaneGroup sizes={sizes} onLayoutChange={setSizes}>
            <Pane>Left</Pane>
            <PaneHandle label="Resize" />
            <Pane>Right</Pane>
          </PaneGroup>
        </>
      );
    }
    render(<Controlled />);
    screen.getByRole('separator').focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByTestId('sizes')).toHaveTextContent('52,48');
  });

  it('uses the vertical axis when the group is vertical', async () => {
    const user = userEvent.setup();
    render(
      <PaneGroup direction="vertical" defaultSizes={[60, 40]}>
        <Pane>Editor</Pane>
        <PaneHandle label="Resize the preview" />
        <Pane>Preview</Pane>
      </PaneGroup>,
    );
    const separator = screen.getByRole('separator');
    expect(separator).toHaveAttribute('aria-orientation', 'horizontal');
    separator.focus();
    await user.keyboard('{ArrowDown}');
    expect(sizeOf('Editor')).toBeCloseTo(62);
  });

  it('resizeAt honours both neighbours and snaps a collapsible pane', () => {
    const constraints = [
      { min: 20, max: 100, collapsible: true, collapsedSize: 0 },
      { min: 30, max: 100, collapsible: false, collapsedSize: 0 },
    ];
    expect(resizeAt([50, 50], 0, -45, constraints)).toEqual([0, 100]);
    expect(resizeAt([50, 50], 0, -20, constraints)).toEqual([30, 70]);
    expect(resizeAt([50, 50], 0, 40, constraints)).toEqual([70, 30]);
  });

  it('has no axe violations', async () => {
    const { container } = render(<Workspace />);
    await expectNoAxeViolations(container);
  });

  describeThemeDensitySnapshots('ResizablePane', () => <Workspace />);
});
