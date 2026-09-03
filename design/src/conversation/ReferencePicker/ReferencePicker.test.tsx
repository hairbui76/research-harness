import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import type { EntityRefModel } from '../../research/models';
import { SAMPLE_EVIDENCE_REF, SAMPLE_STALE_REF } from '../../research/samples';
import { SAMPLE_REFERENCE_RESULTS } from '../samples';
import { ReferencePicker } from './ReferencePicker';

/** The host owns matching, exactly as the component expects. */
function Example({ onSelect = () => undefined }: { onSelect?: (entity: EntityRefModel) => void }) {
  const [query, setQuery] = useState('');
  const results = SAMPLE_REFERENCE_RESULTS.filter((entity) =>
    `${entity.id} ${entity.label ?? ''}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <ReferencePicker
      results={results}
      query={query}
      onQueryChange={setQuery}
      onSelect={onSelect}
      defaultOpen
    />
  );
}

describe('ReferencePicker', () => {
  it('groups the matches by kind', async () => {
    const user = userEvent.setup();
    render(<Example />);
    await user.click(screen.getByRole('combobox'));
    expect(screen.getByRole('group', { name: 'Works' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Evidence' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Claims' })).toBeInTheDocument();
  });

  it('shows the id, the authority and the resolution state on every row', () => {
    const { container } = render(<Example />);
    const stale = container.querySelector('[data-resolution="stale"]');
    expect(stale).toHaveTextContent('A0017-3');
    expect(stale).toHaveTextContent('Stale');
    expect(container.querySelector('[data-resolution="private"]')).toHaveTextContent('Private');
  });

  it('keeps an unresolved reference selectable, marked rather than removed', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Example onSelect={onSelect} />);
    const option = screen.getByRole('option', { name: /A0017-3/ });
    expect(option).not.toHaveAttribute('aria-disabled');
    await user.click(option);
    expect(onSelect).toHaveBeenCalledWith(SAMPLE_STALE_REF);
  });

  it('is fully operable from the keyboard', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<Example onSelect={onSelect} />);
    const input = screen.getByRole('combobox');
    await user.click(input);
    await user.keyboard('E0482');
    await user.keyboard('{ArrowDown}{Enter}');
    expect(onSelect).toHaveBeenCalledWith(SAMPLE_EVIDENCE_REF);
  });

  it('reports typing so the host can search', async () => {
    const user = userEvent.setup();
    const onQueryChange = vi.fn();
    render(
      <ReferencePicker
        results={SAMPLE_REFERENCE_RESULTS}
        query=""
        onQueryChange={onQueryChange}
        onSelect={() => undefined}
      />,
    );
    await user.type(screen.getByRole('combobox'), 'W');
    expect(onQueryChange).toHaveBeenCalledWith('W');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<Example />);
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('ReferencePicker', () => (
  <ReferencePicker
    results={SAMPLE_REFERENCE_RESULTS}
    query=""
    onQueryChange={() => undefined}
    onSelect={() => undefined}
    defaultOpen
  />
));
