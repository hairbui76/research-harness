import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Tag } from './Tag';

describe('Tag', () => {
  it('renders as plain text when it is neither selectable nor removable', () => {
    render(<Tag icon="tag">traffic</Tag>);
    expect(screen.getByText('traffic')).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('reports its pressed state when selectable', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <Tag selected={false} onSelect={onSelect}>
        traffic
      </Tag>,
    );
    const toggle = screen.getByRole('button', { name: 'traffic' });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await user.click(toggle);
    expect(onSelect).toHaveBeenCalledWith(true);
  });

  it('keeps its own state when uncontrolled', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Tag onSelect={onSelect}>traffic</Tag>);
    const toggle = screen.getByRole('button');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(onSelect).toHaveBeenCalledWith(true);
  });

  it('starts from defaultSelected', () => {
    render(
      <Tag defaultSelected onSelect={() => undefined}>
        traffic
      </Tag>,
    );
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true');
  });

  it('follows a controlled parent that stores what it is told', async () => {
    const user = userEvent.setup();
    function Controlled() {
      const [selected, setSelected] = useState(false);
      return (
        <Tag selected={selected} onSelect={setSelected}>
          traffic
        </Tag>
      );
    }
    render(<Controlled />);
    const toggle = screen.getByRole('button');
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
  });

  it('stays put when the parent holds the state and ignores the change', async () => {
    const user = userEvent.setup();
    render(
      <Tag selected={false} onSelect={() => undefined}>
        traffic
      </Tag>,
    );
    await user.click(screen.getByRole('button'));
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'false');
  });

  it('exposes a labelled remove control', async () => {
    const user = userEvent.setup();
    const onRemove = vi.fn();
    render(<Tag onRemove={onRemove}>W0017</Tag>);
    await user.click(screen.getByRole('button', { name: 'Remove W0017' }));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it('reaches both controls by keyboard', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onRemove = vi.fn();
    render(
      <Tag onSelect={onSelect} onRemove={onRemove}>
        E0482
      </Tag>,
    );
    await user.tab();
    expect(screen.getByRole('button', { name: 'E0482' })).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith(true);
    await user.tab();
    expect(screen.getByRole('button', { name: 'Remove E0482' })).toHaveFocus();
    await user.keyboard(' ');
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it('disables both controls together', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onRemove = vi.fn();
    render(
      <Tag disabled onSelect={onSelect} onRemove={onRemove}>
        C0041
      </Tag>,
    );
    for (const button of screen.getAllByRole('button')) {
      expect(button).toBeDisabled();
      await user.click(button);
    }
    expect(onSelect).not.toHaveBeenCalled();
    expect(onRemove).not.toHaveBeenCalled();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        <Tag icon="at-sign">W0017</Tag>
        <Tag selected onSelect={() => undefined}>
          selected
        </Tag>
        <Tag onRemove={() => undefined}>removable</Tag>
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('Tag', () => (
  <div>
    <Tag icon="at-sign">W0017</Tag>
    <Tag selected onSelect={() => undefined}>
      traffic
    </Tag>
    <Tag onSelect={() => undefined} onRemove={() => undefined}>
      E0482
    </Tag>
    <Tag disabled onRemove={() => undefined} size="sm">
      locked
    </Tag>
  </div>
));
