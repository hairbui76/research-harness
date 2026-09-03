import { forwardRef, useEffect, useState } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { useControllable } from '../../utils/useControllable';
import { IconButton } from '../../primitives/IconButton';
import { Pane, PaneGroup, PaneHandle } from '../../primitives/ResizablePane';
import { Tabs } from '../../primitives/Tabs';
import { mergePaneSizes, resolvePaneSizes } from '../models';
import type { PaneSizes } from '../models';

const FILES = 'files';
const EDITOR = 'editor';
const PREVIEW = 'preview';
const TOP = 'top';
const INSPECTOR = 'inspector';

const DEFAULT_COLUMN_SIZES: PaneSizes = { [FILES]: 20, [EDITOR]: 42, [PREVIEW]: 38 };
const DEFAULT_ROW_SIZES: PaneSizes = { [TOP]: 68, [INSPECTOR]: 32 };

export type ManuscriptView = 'editor' | 'preview';

export interface ManuscriptWorkspaceProps extends HTMLAttributes<HTMLDivElement> {
  /** `FileTree`, usually. */
  fileTree: ReactNode;
  /** `SourceEditorFrame` wrapped around the application's editor engine. */
  editor: ReactNode;
  /** `PdfPreview` wrapped around the application's pdf.js adapter. */
  preview: ReactNode;
  /** `DiagnosticsPanel`: compiler output and scientific audit, under separate headings. */
  inspector?: ReactNode;
  inspectorOpen?: boolean;
  defaultInspectorOpen?: boolean;
  onInspectorOpenChange?: (open: boolean) => void;
  /** Where the audit inspector sits on a wide screen. Default `bottom`. */
  inspectorPlacement?: 'bottom' | 'end';
  /** Which of editor/preview is on top in the narrow layout. */
  view?: ManuscriptView;
  defaultView?: ManuscriptView;
  onViewChange?: (view: ManuscriptView) => void;
  /** Force the narrow layout. Omit to track `(max-width: <breakpoint>px)`. */
  narrow?: boolean;
  breakpoint?: number;
  columnSizes?: PaneSizes;
  defaultColumnSizes?: PaneSizes;
  onColumnSizesChange?: (sizes: PaneSizes) => void;
  rowSizes?: PaneSizes;
  defaultRowSizes?: PaneSizes;
  onRowSizesChange?: (sizes: PaneSizes) => void;
  /** Compile controls and the like, in the workspace's own bar beside the inspector toggle. */
  toolbar?: ReactNode;
  filesLabel?: string;
  editorLabel?: string;
  previewLabel?: string;
  inspectorLabel?: string;
}

/** Same media-query model as `AppShell`: no `matchMedia` means "not narrow". */
function useNarrow(breakpoint: number, override?: boolean): boolean {
  const [narrow, setNarrow] = useState(false);

  useEffect(() => {
    if (override !== undefined) return;
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia(`(max-width: ${breakpoint}px)`);
    setNarrow(query.matches);
    const listener = (event: MediaQueryListEvent): void => setNarrow(event.matches);
    if (typeof query.addEventListener === 'function') {
      query.addEventListener('change', listener);
      return () => query.removeEventListener('change', listener);
    }
    query.addListener(listener);
    return () => query.removeListener(listener);
  }, [breakpoint, override]);

  return override ?? narrow;
}

/**
 * The LaTeX workspace: files, source, PDF, and a collapsible audit inspector.
 *
 * Below the width breakpoint the editor and the preview become tabs, and both panels stay
 * mounted — switching tabs must not throw away the cursor position or the page the
 * researcher was reading, and an unmounted CodeMirror or pdf.js instance would do exactly
 * that. Pane sizes are keyed by pane, so collapsing the inspector and reopening it comes
 * back to the same layout.
 */
export const ManuscriptWorkspace = forwardRef<HTMLDivElement, ManuscriptWorkspaceProps>(
  function ManuscriptWorkspace(
    {
      fileTree,
      editor,
      preview,
      inspector,
      inspectorOpen,
      defaultInspectorOpen = true,
      onInspectorOpenChange,
      inspectorPlacement = 'bottom',
      view,
      defaultView = 'editor',
      onViewChange,
      narrow,
      breakpoint = 960,
      columnSizes,
      defaultColumnSizes,
      onColumnSizesChange,
      rowSizes,
      defaultRowSizes,
      onRowSizesChange,
      toolbar,
      filesLabel = 'Manuscript files',
      editorLabel = 'Source',
      previewLabel = 'PDF',
      inspectorLabel = 'Build and audit',
      className,
      ...rest
    },
    ref,
  ) {
    const isNarrow = useNarrow(breakpoint, narrow);
    const [open, setOpen] = useControllable<boolean>({
      value: inspectorOpen,
      defaultValue: defaultInspectorOpen,
      onChange: onInspectorOpenChange,
    });
    const [currentView, setView] = useControllable<ManuscriptView>({
      value: view,
      defaultValue: defaultView,
      onChange: onViewChange,
    });
    const [columns, setColumns] = useControllable<PaneSizes>({
      value: columnSizes,
      defaultValue: defaultColumnSizes ?? DEFAULT_COLUMN_SIZES,
      onChange: onColumnSizesChange,
    });
    const [rows, setRows] = useControllable<PaneSizes>({
      value: rowSizes,
      defaultValue: defaultRowSizes ?? DEFAULT_ROW_SIZES,
      onChange: onRowSizesChange,
    });

    const inspectorVisible = inspector !== undefined && open;

    const toggle =
      inspector === undefined ? null : (
        <IconButton
          className="rh-manuscript-workspace__inspector-toggle"
          icon={inspectorPlacement === 'bottom' ? 'panel-bottom' : 'panel-right'}
          size="sm"
          label={
            open
              ? `Collapse the ${inspectorLabel.toLowerCase()} panel`
              : `Expand the ${inspectorLabel.toLowerCase()} panel`
          }
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        />
      );

    const columnKeys = isNarrow ? [FILES, EDITOR] : [FILES, EDITOR, PREVIEW];
    const resolvedColumns = resolvePaneSizes(columns, columnKeys, DEFAULT_COLUMN_SIZES);

    const documentArea = isNarrow ? (
      <Tabs
        className="rh-manuscript-workspace__tabs"
        value={currentView}
        onValueChange={(next) => setView(next as ManuscriptView)}
        activation="manual"
        keepMounted
      >
        <Tabs.List aria-label="Manuscript view">
          <Tabs.Tab value="editor">{editorLabel}</Tabs.Tab>
          <Tabs.Tab value="preview">{previewLabel}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="editor" className="rh-manuscript-workspace__tab-panel">
          {editor}
        </Tabs.Panel>
        <Tabs.Panel value="preview" className="rh-manuscript-workspace__tab-panel">
          {preview}
        </Tabs.Panel>
      </Tabs>
    ) : null;

    const top = (
      <PaneGroup
        direction="horizontal"
        className="rh-manuscript-workspace__columns"
        sizes={resolvedColumns}
        onLayoutChange={(next) => setColumns(mergePaneSizes(columns, columnKeys, next))}
      >
        <Pane className="rh-manuscript-workspace__files" minSize={10} maxSize={40}>
          {fileTree}
        </Pane>
        <PaneHandle label={`Resize the ${filesLabel.toLowerCase()} pane`} />
        <Pane className="rh-manuscript-workspace__document" minSize={25}>
          {isNarrow ? documentArea : editor}
        </Pane>
        {isNarrow ? null : <PaneHandle label={`Resize the ${previewLabel} pane`} />}
        {isNarrow ? null : (
          <Pane className="rh-manuscript-workspace__preview" minSize={20}>
            {preview}
          </Pane>
        )}
      </PaneGroup>
    );

    const rowKeys = inspectorVisible ? [TOP, INSPECTOR] : [TOP];
    const resolvedRows = resolvePaneSizes(rows, rowKeys, DEFAULT_ROW_SIZES);
    const stacked = inspectorPlacement === 'bottom';

    return (
      <div
        ref={ref}
        className={cx('rh-manuscript-workspace', className)}
        data-narrow={isNarrow ? '' : undefined}
        data-inspector-open={open ? '' : undefined}
        data-inspector-placement={inspectorPlacement}
        {...rest}
      >
        {toolbar === undefined && toggle === null ? null : (
          <div className="rh-manuscript-workspace__bar">
            <div className="rh-manuscript-workspace__bar-slot">{toolbar}</div>
            {toggle}
          </div>
        )}

        {stacked ? (
          <PaneGroup
            direction="vertical"
            className="rh-manuscript-workspace__rows"
            sizes={resolvedRows}
            onLayoutChange={(next) => setRows(mergePaneSizes(rows, rowKeys, next))}
          >
            <Pane className="rh-manuscript-workspace__top" minSize={30}>
              {top}
            </Pane>
            {inspectorVisible ? (
              <PaneHandle label={`Resize the ${inspectorLabel.toLowerCase()} panel`} />
            ) : null}
            {inspectorVisible ? (
              <Pane className="rh-manuscript-workspace__inspector" minSize={12} maxSize={60}>
                <section aria-label={inspectorLabel} className="rh-manuscript-workspace__inspector-body">
                  {inspector}
                </section>
              </Pane>
            ) : null}
          </PaneGroup>
        ) : (
          <div className="rh-manuscript-workspace__side-layout">
            <div className="rh-manuscript-workspace__top">{top}</div>
            {inspectorVisible ? (
              <aside className="rh-manuscript-workspace__inspector" aria-label={inspectorLabel}>
                {inspector}
              </aside>
            ) : null}
          </div>
        )}
      </div>
    );
  },
);
