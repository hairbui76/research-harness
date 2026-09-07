import { forwardRef, useCallback, useEffect, useRef, useState } from 'react';
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

/**
 * Which of the workspace's views the narrow layout is showing.
 *
 * `inspector` exists only below the breakpoint. On a wide screen the audit panel is a pane
 * beside or under the document and is not something the document area switches to.
 */
export type ManuscriptView = 'editor' | 'preview' | 'inspector';

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
  /** Force the narrow layout. Omit to track this workspace's own measured inline size. */
  narrow?: boolean;
  /** The workspace width, in px, at or below which the narrow layout applies. */
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
  /**
   * The word on the narrow layout's own tab for the inspector.
   *
   * It defaults to `inspectorLabel`, and a host whose inspector carries a tab strip of its
   * own should pass the panel's role instead: two strips one under the other repeating the
   * same words read as a rendering fault rather than as a hierarchy.
   */
  inspectorTabLabel?: string;
}

/**
 * Whether *this workspace* — not the window — is too narrow to hold three columns.
 *
 * The manuscript is the route where a viewport query lies. On a 1024x768 laptop the shell
 * keeps its 16rem rail, so the workspace is handed about 768px; on a 768x1024 tablet the
 * rail is a drawer and the workspace is handed about 768px again. A media query calls the
 * first one wide and the second one narrow while the pane is the same size in both, and
 * the wide answer put three panes, a wrapping toolbar and a PDF into 768px.
 *
 * So the pane answers its own width, the way `rh-page` and `rh-inspector` already do. It
 * is measured in JavaScript rather than declared as a CSS container query because the
 * switch changes the tree — three panes become one column with a tab strip — and a
 * container query can only change the painting.
 *
 * A workspace that has not been measured yet is not narrow: zero is what an unlaid-out
 * element and a test renderer both report, and neither is evidence of a small screen.
 */
function useNarrow(
  breakpoint: number,
  override?: boolean,
): [boolean, (element: HTMLDivElement | null) => void] {
  const [narrow, setNarrow] = useState(false);
  const observer = useRef<ResizeObserver | null>(null);

  const measure = useCallback(
    (element: HTMLDivElement): void => {
      const width = element.getBoundingClientRect().width;
      if (width <= 0) return;
      setNarrow(width <= breakpoint);
    },
    [breakpoint],
  );

  const attach = useCallback(
    (element: HTMLDivElement | null): void => {
      observer.current?.disconnect();
      observer.current = null;
      if (element === null || override !== undefined) return;
      measure(element);
      if (typeof ResizeObserver !== 'function') return;
      const next = new ResizeObserver(() => measure(element));
      next.observe(element);
      observer.current = next;
    },
    [measure, override],
  );

  useEffect(() => () => observer.current?.disconnect(), []);

  return [override ?? narrow, attach];
}

/**
 * The LaTeX workspace: files, source, PDF, and a collapsible audit inspector.
 *
 * Below the width breakpoint — this workspace's own width, not the window's — the document
 * area becomes one tab strip: the editor, the preview and the audit inspector take turns
 * over the whole of it instead of dividing a width none of them can hold. Every panel stays
 * mounted, because switching tabs must not throw away the cursor position, the page the
 * researcher was reading, or a diagnostics read in flight, and an unmounted CodeMirror or
 * pdf.js instance would do exactly that. Pane sizes are keyed by pane, so collapsing the
 * inspector and reopening it comes back to the same layout.
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
      inspectorTabLabel,
      className,
      ...rest
    },
    ref,
  ) {
    const [isNarrow, measureRoot] = useNarrow(breakpoint, narrow);
    const setRoot = useCallback(
      (element: HTMLDivElement | null): void => {
        measureRoot(element);
        if (typeof ref === 'function') ref(element);
        else if (ref) ref.current = element;
      },
      [measureRoot, ref],
    );
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

    // Below the breakpoint the inspector is a view of the document area rather than a pane
    // under it, so there is nothing to collapse and the tab strip carries it instead.
    const hasInspector = inspector !== undefined;
    const inspectorVisible = hasInspector && open && !isNarrow;
    const currentTab = isNarrow && currentView === INSPECTOR && !hasInspector ? EDITOR : currentView;
    const showingInspector = isNarrow ? currentTab === INSPECTOR : open;

    /**
     * Show the inspector, at whichever width this is.
     *
     * Below the breakpoint the two states are one. `open` says whether a pane is expanded
     * under the document; `currentView` says which of the three views the document area is
     * showing. They were independent, so the bar could offer to collapse an inspector the
     * tab strip had not selected, or to expand one it had — two controls disagreeing about
     * one thing on screen. Choosing the inspector now sets both, from the tab strip and
     * from the bar alike, so widening the window keeps the choice the narrow layout made
     * rather than reverting to whatever `open` was left at.
     */
    const showInspector = (next: boolean): void => {
      if (isNarrow) setView(next ? INSPECTOR : EDITOR);
      setOpen(next);
    };

    /*
     * One control for the inspector at both widths — the only place the words "build and
     * audit" are pinned in the bar before the panel is opened — reporting its state in
     * whichever of the two ways is true of this width.
     *
     * Wide, it is a disclosure: a pane under the document expands and collapses, and the
     * name says which of those the press will do. Narrow, nothing collapses; the three
     * views take turns over one area and this selects one of them. That is a toggle, so
     * the name stays put and `aria-pressed` carries the state — a name that read "collapse
     * the panel" while the Inspector tab was selected described a disclosure that is not
     * what the press does.
     */
    const toggle = !hasInspector ? null : (
      <IconButton
        className="rh-manuscript-workspace__inspector-toggle"
        icon={inspectorPlacement === 'bottom' ? 'panel-bottom' : 'panel-right'}
        size="sm"
        label={
          isNarrow
            ? `Show the ${inspectorLabel.toLowerCase()} panel`
            : showingInspector
              ? `Collapse the ${inspectorLabel.toLowerCase()} panel`
              : `Expand the ${inspectorLabel.toLowerCase()} panel`
        }
        {...(isNarrow
          ? { 'aria-pressed': showingInspector }
          : { 'aria-expanded': showingInspector })}
        onClick={() => showInspector(!showingInspector)}
      />
    );

    const columnKeys = isNarrow ? [FILES, EDITOR] : [FILES, EDITOR, PREVIEW];
    const resolvedColumns = resolvePaneSizes(columns, columnKeys, DEFAULT_COLUMN_SIZES);

    const documentArea = isNarrow ? (
      <Tabs
        className="rh-manuscript-workspace__tabs"
        value={currentTab}
        onValueChange={(next) => {
          const view = next as ManuscriptView;
          setView(view);
          // The bar's control reads the inspector's state, so the tab strip writes it:
          // one thing on screen, one state, whichever of the two the researcher used.
          if (hasInspector) setOpen(view === INSPECTOR);
        }}
        activation="manual"
        keepMounted
      >
        <Tabs.List aria-label="Manuscript view">
          <Tabs.Tab value={EDITOR}>{editorLabel}</Tabs.Tab>
          <Tabs.Tab value={PREVIEW}>{previewLabel}</Tabs.Tab>
          {hasInspector ? (
            <Tabs.Tab value={INSPECTOR}>{inspectorTabLabel ?? inspectorLabel}</Tabs.Tab>
          ) : null}
        </Tabs.List>
        <Tabs.Panel value={EDITOR} className="rh-manuscript-workspace__tab-panel">
          {editor}
        </Tabs.Panel>
        <Tabs.Panel value={PREVIEW} className="rh-manuscript-workspace__tab-panel">
          {preview}
        </Tabs.Panel>
        {hasInspector ? (
          <Tabs.Panel value={INSPECTOR} className="rh-manuscript-workspace__tab-panel">
            {/* The same region, under the same name, as the pane the wide layout gives it. */}
            <section
              aria-label={inspectorLabel}
              className="rh-manuscript-workspace__inspector-body"
            >
              {inspector}
            </section>
          </Tabs.Panel>
        ) : null}
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
        ref={setRoot}
        className={cx('rh-manuscript-workspace', className)}
        data-narrow={isNarrow ? '' : undefined}
        data-inspector-open={showingInspector ? '' : undefined}
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
