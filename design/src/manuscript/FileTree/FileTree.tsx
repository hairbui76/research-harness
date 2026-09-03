import { forwardRef, useCallback, useMemo, useRef, useState } from 'react';
import type { HTMLAttributes, KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { useControllable } from '../../utils/useControllable';
import { useId } from '../../hooks/useId';
import { Icon } from '../../primitives/Icon';
import { Menu } from '../../primitives/Menu';
import { AsyncState } from '../../states/AsyncState';
import { FILE_KIND_LABELS, fileKindIcon, flattenFileTree } from '../models';
import type { FileNode, FlatFileRow } from '../models';

const TYPEAHEAD_RESET_MS = 500;

export interface FileTreeProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onSelect'> {
  /** The project's manuscript files. Directories carry `children`. */
  nodes: readonly FileNode[];
  /** Accessible name of the tree. */
  label?: string;
  /** Controlled selection, by path. */
  selectedPath?: string;
  onSelect?: (path: string) => void;
  /** Controlled set of expanded directory paths. */
  expanded?: readonly string[];
  defaultExpanded?: readonly string[];
  onExpandedChange?: (paths: string[]) => void;
  /** Context-menu actions. Each one is omitted from the menu when its callback is absent. */
  onRename?: (path: string) => void;
  onDelete?: (path: string) => void;
  /** Called with the directory the new file belongs in ('' for the project root). */
  onNewFile?: (parentPath: string) => void;
  /** Shown instead of the tree when `nodes` is empty. */
  emptyLabel?: string;
  emptyDescription?: ReactNode;
}

interface RowMarker {
  text: string;
  tone: 'dirty' | 'conflict';
}

function markersFor(node: FileNode): RowMarker[] {
  const markers: RowMarker[] = [];
  // Text, not colour: the state survives greyscale and a colour-blind reader.
  if (node.conflict) markers.push({ text: 'Changed on disk', tone: 'conflict' });
  if (node.dirty) markers.push({ text: 'Unsaved', tone: 'dirty' });
  return markers;
}

function parentOf(path: string): string {
  const cut = path.lastIndexOf('/');
  return cut <= 0 ? '' : path.slice(0, cut);
}

/**
 * The manuscript file tree.
 *
 * Rows are flattened into one `tree` with explicit `aria-level` / `aria-posinset` /
 * `aria-setsize`, which keeps every row's accessible name to its own text rather than its
 * whole subtree, and keeps the keyboard model in one place: one tab stop for the tree,
 * arrows to move, Left/Right to collapse and expand, Home/End to the ends, printable
 * characters to jump. Selection is a callback — the tree never opens or writes a file.
 */
export const FileTree = forwardRef<HTMLDivElement, FileTreeProps>(function FileTree(
  {
    nodes,
    label = 'Manuscript files',
    selectedPath,
    onSelect,
    expanded,
    defaultExpanded,
    onExpandedChange,
    onRename,
    onDelete,
    onNewFile,
    emptyLabel = 'No manuscript files yet',
    emptyDescription,
    className,
    onKeyDown,
    id,
    ...rest
  },
  ref,
) {
  const baseId = useId(id, 'rh-filetree');
  const [expandedPaths, setExpandedPaths] = useControllable<string[]>({
    value: expanded as string[] | undefined,
    defaultValue: defaultExpanded ? [...defaultExpanded] : [],
    onChange: onExpandedChange,
  });
  const expandedSet = useMemo(() => new Set(expandedPaths), [expandedPaths]);
  const rows = useMemo(() => flattenFileTree(nodes, expandedSet), [expandedSet, nodes]);

  const [activePath, setActivePath] = useState<string | undefined>(undefined);
  const treeRef = useRef<HTMLDivElement | null>(null);
  const typeahead = useRef({ text: '', at: 0 });

  // Exactly one row is the tree's tab stop. A remembered or selected path that is no
  // longer visible (its folder collapsed, the file was deleted) falls back to the first
  // row, so the tree is never unreachable from the keyboard.
  const visible = (path: string | undefined): boolean =>
    path !== undefined && rows.some((row) => row.node.path === path);
  const active = visible(activePath)
    ? activePath
    : visible(selectedPath)
      ? selectedPath
      : rows[0]?.node.path;

  const focusRow = useCallback((path: string): void => {
    setActivePath(path);
    const tree = treeRef.current;
    if (!tree) return;
    const target = Array.from(tree.querySelectorAll<HTMLElement>('[data-path]')).find(
      (candidate) => candidate.dataset.path === path,
    );
    target?.focus();
  }, []);

  const setExpansion = useCallback(
    (path: string, open: boolean): void => {
      const next = new Set(expandedPaths);
      if (open) next.add(path);
      else next.delete(path);
      setExpandedPaths([...next]);
    },
    [expandedPaths, setExpandedPaths],
  );

  const activate = useCallback(
    (row: FlatFileRow): void => {
      if (row.hasChildren) {
        setExpansion(row.node.path, !row.expanded);
        return;
      }
      onSelect?.(row.node.path);
    },
    [onSelect, setExpansion],
  );

  const moveBy = useCallback(
    (from: number, delta: number): void => {
      const next = rows[from + delta];
      if (next) focusRow(next.node.path);
    },
    [focusRow, rows],
  );

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>): void => {
    onKeyDown?.(event);
    if (event.defaultPrevented) return;
    const index = rows.findIndex((row) => row.node.path === active);
    const row = rows[index];
    if (!row) return;

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        moveBy(index, 1);
        return;
      case 'ArrowUp':
        event.preventDefault();
        moveBy(index, -1);
        return;
      case 'Home': {
        event.preventDefault();
        const first = rows[0];
        if (first) focusRow(first.node.path);
        return;
      }
      case 'End': {
        event.preventDefault();
        const last = rows[rows.length - 1];
        if (last) focusRow(last.node.path);
        return;
      }
      case 'ArrowRight':
        event.preventDefault();
        if (row.hasChildren && !row.expanded) setExpansion(row.node.path, true);
        else if (row.expanded) moveBy(index, 1);
        return;
      case 'ArrowLeft': {
        event.preventDefault();
        if (row.hasChildren && row.expanded) {
          setExpansion(row.node.path, false);
          return;
        }
        if (row.parentPath !== undefined) focusRow(row.parentPath);
        return;
      }
      case 'Enter':
      case ' ':
        event.preventDefault();
        activate(row);
        return;
      case '*': {
        // The tree pattern's "expand every sibling" shortcut.
        event.preventDefault();
        const siblings = rows
          .filter((candidate) => candidate.level === row.level && candidate.hasChildren)
          .map((candidate) => candidate.node.path);
        setExpandedPaths([...new Set([...expandedPaths, ...siblings])]);
        return;
      }
      default:
        break;
    }

    if (event.key.length !== 1 || event.metaKey || event.ctrlKey || event.altKey) return;
    const now = Date.now();
    typeahead.current.text =
      now - typeahead.current.at > TYPEAHEAD_RESET_MS ? event.key : typeahead.current.text + event.key;
    typeahead.current.at = now;
    const needle = typeahead.current.text.toLowerCase();
    const ordered = [...rows.slice(index + 1), ...rows.slice(0, index + 1)];
    const match = ordered.find((candidate) => candidate.node.name.toLowerCase().startsWith(needle));
    if (match) {
      event.preventDefault();
      focusRow(match.node.path);
    }
  };

  const hasMenu = Boolean(onRename ?? onDelete ?? onNewFile);

  if (rows.length === 0) {
    return (
      <div ref={ref} className={cx('rh-file-tree', className)} {...rest}>
        <AsyncState kind="empty" title={emptyLabel} description={emptyDescription} compact />
      </div>
    );
  }

  return (
    <div
      ref={(node) => {
        treeRef.current = node;
        if (typeof ref === 'function') ref(node);
        else if (ref) ref.current = node;
      }}
      role="tree"
      id={baseId}
      aria-label={label}
      aria-multiselectable={false}
      className={cx('rh-file-tree', className)}
      onKeyDown={handleKeyDown}
      {...rest}
    >
      {rows.map((row) => {
        const { node } = row;
        const selected = selectedPath === node.path;
        const markers = markersFor(node);
        return (
          <div
            key={node.path}
            role="treeitem"
            data-path={node.path}
            data-kind={node.kind}
            aria-level={row.level}
            aria-posinset={row.position}
            aria-setsize={row.setSize}
            aria-selected={selected}
            aria-expanded={row.hasChildren ? row.expanded : undefined}
            tabIndex={active === node.path ? 0 : -1}
            className={cx('rh-file-tree__row', selected && 'is-selected')}
            style={{ paddingInlineStart: `calc(var(--rh-space-2) + ${row.level - 1} * var(--rh-space-4))` }}
            onClick={() => {
              setActivePath(node.path);
              activate(row);
            }}
            onFocus={() => setActivePath(node.path)}
          >
            <span className="rh-file-tree__twisty" aria-hidden="true">
              {row.hasChildren ? (
                <Icon name={row.expanded ? 'chevron-down' : 'chevron-right'} size={14} />
              ) : null}
            </span>
            <Icon name={fileKindIcon(node.kind, row.expanded)} size={16} />
            <span className="rh-file-tree__name">{node.name}</span>
            <span className="rh-visually-hidden">{FILE_KIND_LABELS[node.kind]}</span>
            {markers.map((marker) => (
              <span
                key={marker.text}
                className="rh-file-tree__marker"
                data-tone={marker.tone}
              >
                <Icon name={marker.tone === 'conflict' ? 'alert-triangle' : 'pen-line'} size={14} />
                {marker.text}
              </span>
            ))}
            {hasMenu ? (
              <Menu placement="bottom" align="end">
                <Menu.Trigger
                  className="rh-file-tree__menu-trigger"
                  aria-label={`Actions for ${node.name}`}
                  tabIndex={-1}
                  onClick={(event) => event.stopPropagation()}
                >
                  <Icon name="more-horizontal" size={14} />
                </Menu.Trigger>
                <Menu.Content aria-label={`Actions for ${node.name}`}>
                  {onNewFile ? (
                    <Menu.Item
                      icon={<Icon name="file-plus" size={14} />}
                      onSelect={() => onNewFile(node.kind === 'dir' ? node.path : parentOf(node.path))}
                    >
                      New file
                    </Menu.Item>
                  ) : null}
                  {onRename ? (
                    <Menu.Item
                      icon={<Icon name="pen-line" size={14} />}
                      onSelect={() => onRename(node.path)}
                    >
                      Rename
                    </Menu.Item>
                  ) : null}
                  {onDelete ? (
                    <Menu.Item
                      icon={<Icon name="trash-2" size={14} />}
                      onSelect={() => onDelete(node.path)}
                    >
                      Delete
                    </Menu.Item>
                  ) : null}
                </Menu.Content>
              </Menu>
            ) : null}
          </div>
        );
      })}
    </div>
  );
});
