import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { ConversationWorkspace } from './ConversationWorkspace';
import type { PaneSizes } from '../models';

function Composer(): JSX.Element {
  const [draft, setDraft] = useState('');
  return (
    <label>
      Message
      <textarea value={draft} onChange={(event) => setDraft(event.target.value)} />
    </label>
  );
}

function Example({
  onPaneSizesChange,
}: {
  onPaneSizesChange?: (sizes: PaneSizes) => void;
}): JSX.Element {
  return (
    <ConversationWorkspace
      rail={<nav aria-label="Sessions">sessions</nav>}
      transcript={<ol><li>M0042</li></ol>}
      composer={<Composer />}
      inspector={<section aria-label="Inspector body">evidence</section>}
      onPaneSizesChange={onPaneSizesChange}
    />
  );
}

describe('ConversationWorkspace', () => {
  it('lays rail, transcript with composer, and inspector out as resizable panes', () => {
    render(<Example />);
    expect(screen.getByRole('navigation', { name: 'Sessions' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Conversation' })).toBeInTheDocument();
    expect(screen.getByLabelText('Message')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Inspector body' })).toBeInTheDocument();
    expect(screen.getAllByRole('separator')).toHaveLength(2);
  });

  it('collapses the inspector and keeps the toggle exactly where it was', async () => {
    const user = userEvent.setup();
    render(<Example />);
    const toggle = screen.getByRole('button', { name: 'Collapse the research inspector' });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    await user.click(toggle);
    expect(screen.queryByRole('region', { name: 'Inspector body' })).not.toBeInTheDocument();
    // The toggle is still in the DOM, still focused: focus never fell to the body.
    const expand = screen.getByRole('button', { name: 'Expand the research inspector' });
    expect(expand).toHaveFocus();
    expect(screen.getAllByRole('separator')).toHaveLength(1);

    await user.click(expand);
    expect(screen.getByRole('region', { name: 'Inspector body' })).toBeInTheDocument();
  });

  it('keeps the composer draft through an inspector collapse', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.type(screen.getByLabelText('Message'), 'half a thought');
    await user.click(screen.getByRole('button', { name: 'Collapse the research inspector' }));
    expect(screen.getByLabelText('Message')).toHaveValue('half a thought');
  });

  it('reports pane sizes keyed by pane so a collapse cannot shift them', async () => {
    const user = userEvent.setup();
    const onPaneSizesChange = vi.fn();
    render(<Example onPaneSizesChange={onPaneSizesChange} />);

    const [railHandle] = screen.getAllByRole('separator');
    railHandle?.focus();
    await user.keyboard('{ArrowRight}');

    expect(onPaneSizesChange).toHaveBeenCalled();
    const sizes = onPaneSizesChange.mock.calls.at(-1)?.[0] as PaneSizes;
    expect(Object.keys(sizes).sort()).toEqual(['centre', 'inspector', 'rail']);
    expect(sizes.rail).toBeGreaterThan(18);
  });

  it('resizes panes from the keyboard', async () => {
    const user = userEvent.setup();
    render(<Example />);
    const [railHandle] = screen.getAllByRole('separator');
    const before = Number(railHandle?.getAttribute('aria-valuenow'));
    railHandle?.focus();
    await user.keyboard('{ArrowRight}{ArrowRight}');
    expect(Number(railHandle?.getAttribute('aria-valuenow'))).toBeGreaterThan(before);
  });

  it('works without a rail, for a shell that already supplies one', () => {
    render(
      <ConversationWorkspace
        transcript={<p>transcript</p>}
        composer={<p>composer</p>}
        inspector={<section aria-label="Inspector body">evidence</section>}
      />,
    );
    expect(screen.getAllByRole('separator')).toHaveLength(1);
  });

  it('has no axe violations', async () => {
    const { container } = render(<Example />);
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('ConversationWorkspace', () => (
  <ConversationWorkspace
    rail={<nav aria-label="Sessions">sessions</nav>}
    transcript={<ol><li>M0042</li></ol>}
    composer={<p>composer</p>}
    inspector={<section aria-label="Inspector body">evidence</section>}
  />
));
