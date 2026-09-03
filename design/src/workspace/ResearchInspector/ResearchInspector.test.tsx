import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { ResearchInspector } from './ResearchInspector';
import type { InspectorSelection } from '../models';

const selection: InspectorSelection = {
  kind: 'reference',
  label: 'E0482',
  detail: 'Cited in M0042',
  ref: { kind: 'evidence', id: 'E0482', href: 'rh://evidence/E0482' },
};

const panels = {
  context: <p>Context pack CP0007</p>,
  evidence: <p>Evidence E0482</p>,
};

describe('ResearchInspector', () => {
  it('offers the six tabs with their counts', () => {
    render(
      <ResearchInspector counts={{ review: 4, conflicts: 1 }} panels={panels} />,
    );
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
      'Context',
      'Evidence',
      'Claims',
      'Review inbox4 Review inbox items',
      'Conflicts1 Conflicts items',
      'Stale',
    ]);
  });

  it('says what it is following, in words', () => {
    render(<ResearchInspector selection={selection} panels={panels} />);
    expect(screen.getByText('Following reference')).toBeInTheDocument();
    expect(screen.getByText('E0482')).toBeInTheDocument();
    expect(screen.getByText('Cited in M0042')).toBeInTheDocument();
  });

  it('says so when nothing is selected', () => {
    render(<ResearchInspector panels={panels} />);
    expect(
      screen.getByText('Nothing selected. Choose a message, reference or attachment.'),
    ).toBeInTheDocument();
  });

  it('navigates to the followed object', async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    render(<ResearchInspector selection={selection} panels={panels} onNavigate={onNavigate} />);
    await user.click(screen.getByRole('button', { name: 'Open reference' }));
    expect(onNavigate).toHaveBeenCalledWith(selection.ref);
  });

  it('toggles following without losing the selection', async () => {
    const user = userEvent.setup();
    const onFollow = vi.fn();
    render(<ResearchInspector selection={selection} panels={panels} onFollow={onFollow} />);
    const toggle = screen.getByRole('button', { name: 'Stop following' });
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    await user.click(toggle);
    expect(onFollow).toHaveBeenCalledWith(false);
  });

  it('switches tabs with the arrow keys and reports the change', async () => {
    const user = userEvent.setup();
    const onTabChange = vi.fn();
    render(<ResearchInspector panels={panels} onTabChange={onTabChange} />);
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Context pack CP0007');

    await user.tab();
    expect(screen.getByRole('tab', { name: 'Context' })).toHaveFocus();
    // Manual activation: arrowing moves focus, Enter selects, so a fetching panel is
    // never triggered by passing through it.
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Evidence' })).toHaveFocus();
    expect(onTabChange).not.toHaveBeenCalled();

    await user.keyboard('{Enter}');
    expect(onTabChange).toHaveBeenCalledWith('evidence');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Evidence E0482');
  });

  it('renders an empty state for a tab with no content', async () => {
    const user = userEvent.setup();
    render(<ResearchInspector panels={panels} />);
    await user.click(screen.getByRole('tab', { name: 'Claims' }));
    expect(screen.getByText('No claims for this selection')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <ResearchInspector
        selection={selection}
        counts={{ review: 4 }}
        panels={panels}
        onNavigate={vi.fn()}
        onFollow={vi.fn()}
      />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('ResearchInspector', () => (
  <ResearchInspector
    selection={selection}
    counts={{ review: 4, conflicts: 1 }}
    panels={panels}
    onNavigate={() => undefined}
    onFollow={() => undefined}
  />
));
