import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { FileTree } from './FileTree';
import type { FileNode } from '../models';

const nodes: FileNode[] = [
  {
    path: 'manuscript',
    name: 'manuscript',
    kind: 'dir',
    children: [
      { path: 'manuscript/main.tex', name: 'main.tex', kind: 'tex', dirty: true },
      { path: 'manuscript/refs.bib', name: 'refs.bib', kind: 'bib' },
      {
        path: 'manuscript/sections',
        name: 'sections',
        kind: 'dir',
        children: [
          { path: 'manuscript/sections/intro.tex', name: 'intro.tex', kind: 'tex', conflict: true },
        ],
      },
    ],
  },
  { path: 'notes.md', name: 'notes.md', kind: 'other' },
];

function rows(): HTMLElement[] {
  return screen.getAllByRole('treeitem');
}

describe('FileTree', () => {
  it('renders a tree with levels, positions and expansion state', () => {
    render(<FileTree nodes={nodes} defaultExpanded={['manuscript']} />);
    const tree = screen.getByRole('tree', { name: 'Manuscript files' });
    expect(tree).toBeInTheDocument();

    const visible = rows();
    expect(visible.map((row) => row.dataset.path)).toEqual([
      'manuscript',
      'manuscript/main.tex',
      'manuscript/refs.bib',
      'manuscript/sections',
      'notes.md',
    ]);

    expect(visible[0]).toHaveAttribute('aria-expanded', 'true');
    expect(visible[0]).toHaveAttribute('aria-level', '1');
    expect(visible[1]).toHaveAttribute('aria-level', '2');
    expect(visible[1]).toHaveAttribute('aria-posinset', '1');
    expect(visible[1]).toHaveAttribute('aria-setsize', '3');
    // A leaf is not expandable, so it carries no aria-expanded at all.
    expect(visible[1]).not.toHaveAttribute('aria-expanded');
  });

  it('states dirty and conflict in words, not only in colour', () => {
    render(<FileTree nodes={nodes} defaultExpanded={['manuscript', 'manuscript/sections']} />);
    expect(screen.getByText('Unsaved')).toBeInTheDocument();
    expect(screen.getByText('Changed on disk')).toBeInTheDocument();
  });

  it('moves with the arrow keys, expands, collapses and type-aheads', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<FileTree nodes={nodes} defaultExpanded={['manuscript']} onSelect={onSelect} />);

    await user.tab();
    expect(rows()[0]).toHaveFocus();

    await user.keyboard('{ArrowDown}');
    expect(screen.getByText('main.tex').closest('[role="treeitem"]')).toHaveFocus();

    await user.keyboard('{ArrowUp}{ArrowLeft}');
    // Left on an expanded folder collapses it rather than moving.
    expect(rows()).toHaveLength(2);
    expect(rows()[0]).toHaveAttribute('aria-expanded', 'false');

    await user.keyboard('{ArrowRight}');
    expect(rows()[0]).toHaveAttribute('aria-expanded', 'true');

    await user.keyboard('{End}');
    expect(screen.getByText('notes.md').closest('[role="treeitem"]')).toHaveFocus();
    await user.keyboard('{Home}');
    expect(rows()[0]).toHaveFocus();

    await user.keyboard('r');
    expect(screen.getByText('refs.bib').closest('[role="treeitem"]')).toHaveFocus();

    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledWith('manuscript/refs.bib');
  });

  it('reports the expanded set and honours a controlled one', async () => {
    const user = userEvent.setup();
    const onExpandedChange = vi.fn();
    const { rerender } = render(
      <FileTree nodes={nodes} expanded={[]} onExpandedChange={onExpandedChange} />,
    );
    expect(rows()).toHaveLength(2);

    await user.click(screen.getByText('manuscript'));
    expect(onExpandedChange).toHaveBeenCalledWith(['manuscript']);
    // Controlled: nothing moves until the caller says so.
    expect(rows()).toHaveLength(2);

    rerender(
      <FileTree nodes={nodes} expanded={['manuscript']} onExpandedChange={onExpandedChange} />,
    );
    expect(rows()).toHaveLength(5);
  });

  it('offers rename, delete and new file through a context menu', async () => {
    const user = userEvent.setup();
    const onRename = vi.fn();
    const onDelete = vi.fn();
    const onNewFile = vi.fn();
    render(
      <FileTree
        nodes={nodes}
        defaultExpanded={['manuscript']}
        onRename={onRename}
        onDelete={onDelete}
        onNewFile={onNewFile}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Actions for main.tex' }));
    const menu = screen.getByRole('menu', { name: 'Actions for main.tex' });
    await user.click(within(menu).getByRole('menuitem', { name: 'Rename' }));
    expect(onRename).toHaveBeenCalledWith('manuscript/main.tex');

    await user.click(screen.getByRole('button', { name: 'Actions for main.tex' }));
    await user.click(screen.getByRole('menuitem', { name: 'New file' }));
    // A file's "new file" belongs to the directory the file is in.
    expect(onNewFile).toHaveBeenCalledWith('manuscript');
  });

  it('shows an empty state rather than an empty tree', () => {
    render(<FileTree nodes={[]} />);
    expect(screen.queryByRole('tree')).not.toBeInTheDocument();
    expect(screen.getByText('No manuscript files yet')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <FileTree nodes={nodes} defaultExpanded={['manuscript']} selectedPath="manuscript/main.tex" onRename={vi.fn()} />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('FileTree', () => (
  <FileTree nodes={nodes} defaultExpanded={['manuscript']} selectedPath="manuscript/main.tex" />
));
