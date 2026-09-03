/**
 * The manuscript source editor.
 *
 * LaTeX spec §4 is the rule this component is built around: files under `manuscript/` are
 * ordinary user-owned project files, and the interface reads and writes them only after an
 * explicit action. So this editor is *controlled* — it never invents a save, and `Mod-s`
 * calls `onSave` rather than writing anything itself — and it reports the cursor as a
 * 1-based line so a SyncTeX forward lookup can be asked for exactly where the researcher
 * is (§6). `goTo` is the other direction: a compiler diagnostic or a SyncTeX inverse hit
 * puts the cursor on a line.
 *
 * Reconciling an external value is deliberate rather than naive. When the incoming `value`
 * already matches the document, nothing is dispatched, so a keystroke round-tripping
 * through the parent's state never moves the cursor or clears the selection; when it
 * differs (a file reloaded from disk, a candidate diff applied), the document is replaced
 * and the cursor is clamped into it.
 *
 * Colour comes only from `--rh-*` tokens through `EditorView.theme`, so the editor follows
 * `data-theme` with the rest of the cockpit. Syntax *colour* is deliberately restrained:
 * `@lezer/highlight` — the package that names the tags a `HighlightStyle` needs — is not a
 * dependency of this client, so the LaTeX structure is marked by a small decorator below
 * and distinguished by weight and ink rather than by hue.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { Compartment, EditorState, Prec } from '@codemirror/state';
import type { Extension } from '@codemirror/state';
import {
  Decoration,
  EditorView,
  MatchDecorator,
  ViewPlugin,
  drawSelection,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
  rectangularSelection,
} from '@codemirror/view';
import type { DecorationSet, ViewUpdate } from '@codemirror/view';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { highlightSelectionMatches, search, searchKeymap } from '@codemirror/search';
import { StreamLanguage, bracketMatching, indentUnit } from '@codemirror/language';
import { stex } from '@codemirror/legacy-modes/mode/stex';
import './editor.css';

/** 1-based, as LaTeX logs, SyncTeX, and every compiler diagnostic count. */
export interface CursorPosition {
  line: number;
  column: number;
}

export type EditorLanguage = 'latex' | 'bibtex' | 'plain';

export interface LatexEditorHandle {
  /** Put the cursor on a line (1-based) and scroll it into view. */
  goTo(line: number, column?: number): void;
  focus(): void;
  getValue(): string;
  getCursor(): CursorPosition;
  /**
   * The CodeMirror view, or null before it is mounted.
   *
   * The escape hatch for the extensions this component has no opinion about — compiler
   * diagnostics in the gutter, a candidate diff drawn over the source, scroll sync with
   * the preview. Everything the editor itself owns is a prop.
   */
  getView(): EditorView | null;
}

export interface LatexEditorProps {
  /** The source. Controlled: the editor shows what it is given. */
  value: string;
  /** Every edit, as the whole document. The parent owns the buffer. */
  onChange?: (value: string) => void;
  /** `Mod-s`. Saving a file is the caller's explicit action, never the editor's. */
  onSave?: (value: string) => void;
  /** Where the cursor is now, for a SyncTeX forward lookup. */
  onCursorChange?: (position: CursorPosition) => void;
  /** The file being edited; `.tex`/`.sty`/`.cls`/`.ltx` and `.bib` pick the mode. */
  fileName?: string;
  /** Overrides the mode `fileName` implies. */
  language?: EditorLanguage;
  readOnly?: boolean;
  /** Why it is read-only — shown, because a disabled surface must say what disabled it. */
  readOnlyReason?: string;
  /** Accessible name for the text area. */
  label?: string;
  className?: string;
}

export const LatexEditor = forwardRef<LatexEditorHandle, LatexEditorProps>(function LatexEditor(
  {
    value,
    onChange,
    onSave,
    onCursorChange,
    fileName,
    language,
    readOnly = false,
    readOnlyReason,
    label,
    className,
  },
  ref,
) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<EditorView | null>(null);

  // The document as both sides last agreed it was. It is what stops the controlled value
  // and the editor's own updates from echoing each other.
  const valueRef = useRef(value);
  const cursorRef = useRef<CursorPosition>({ line: 1, column: 1 });
  const handlers = useRef({ onChange, onSave, onCursorChange });
  handlers.current = { onChange, onSave, onCursorChange };

  const languageSlot = useRef(new Compartment()).current;
  const readOnlySlot = useRef(new Compartment()).current;
  const labelSlot = useRef(new Compartment()).current;

  const mode = language ?? languageOf(fileName);

  useEffect(() => {
    const parent = hostRef.current;
    if (!parent) return;

    const view = new EditorView({
      parent,
      state: EditorState.create({
        doc: valueRef.current,
        extensions: [
          lineNumbers(),
          highlightActiveLineGutter(),
          highlightActiveLine(),
          highlightSpecialChars(),
          drawSelection(),
          rectangularSelection(),
          bracketMatching(),
          history(),
          search({ top: true }),
          highlightSelectionMatches(),
          EditorView.lineWrapping,
          indentUnit.of('  '),
          // Save wins over anything else bound to the same chord.
          Prec.highest(
            keymap.of([
              {
                key: 'Mod-s',
                preventDefault: true,
                run: (target) => {
                  handlers.current.onSave?.(target.state.doc.toString());
                  return true;
                },
              },
            ]),
          ),
          keymap.of([...defaultKeymap, ...historyKeymap, ...searchKeymap, indentWithTab]),
          languageSlot.of([]),
          readOnlySlot.of([]),
          labelSlot.of([]),
          rhTheme,
          EditorView.updateListener.of(report),
        ],
      }),
    });
    viewRef.current = view;

    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // Built once, on purpose: every prop reconfigures a compartment or dispatches a
    // transaction instead of tearing the view down and losing the undo history with it.
  }, [languageSlot, readOnlySlot, labelSlot]);

  // The controlled value. An unchanged document is left alone — replacing it would drop
  // the cursor and the selection on every keystroke the parent echoed back.
  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current === value) return;
    valueRef.current = value;
    const { anchor, head } = view.state.selection.main;
    view.dispatch({
      changes: { from: 0, to: current.length, insert: value },
      selection: { anchor: Math.min(anchor, value.length), head: Math.min(head, value.length) },
    });
  }, [value]);

  useEffect(() => {
    viewRef.current?.dispatch({ effects: languageSlot.reconfigure(extensionsFor(mode)) });
  }, [mode, languageSlot]);

  useEffect(() => {
    viewRef.current?.dispatch({
      effects: readOnlySlot.reconfigure([
        EditorState.readOnly.of(readOnly),
        EditorView.editable.of(!readOnly),
      ]),
    });
  }, [readOnly, readOnlySlot]);

  useEffect(() => {
    const name = label ?? (fileName ? `${fileName} source` : 'manuscript source');
    viewRef.current?.dispatch({
      effects: labelSlot.reconfigure(
        EditorView.contentAttributes.of({
          'aria-label': name,
          ...(readOnly ? { 'aria-readonly': 'true' } : {}),
        }),
      ),
    });
  }, [label, fileName, readOnly, labelSlot]);

  useImperativeHandle(
    ref,
    (): LatexEditorHandle => ({
      goTo(line, column) {
        const view = viewRef.current;
        if (!view) return;
        const target = view.state.doc.line(
          Math.min(Math.max(1, Math.floor(line)), view.state.doc.lines),
        );
        const at = Math.min(target.from + Math.max(0, Math.floor(column ?? 1) - 1), target.to);
        view.dispatch({ selection: { anchor: at }, scrollIntoView: true });
        view.focus();
      },
      focus() {
        viewRef.current?.focus();
      },
      getValue() {
        return viewRef.current?.state.doc.toString() ?? valueRef.current;
      },
      getCursor() {
        return cursorRef.current;
      },
      getView() {
        return viewRef.current;
      },
    }),
    [],
  );

  function report(update: ViewUpdate) {
    if (update.docChanged) {
      const text = update.state.doc.toString();
      if (text !== valueRef.current) {
        valueRef.current = text;
        handlers.current.onChange?.(text);
      }
    }
    if (update.selectionSet || update.docChanged) {
      const head = update.state.selection.main.head;
      const line = update.state.doc.lineAt(head);
      const position = { line: line.number, column: head - line.from + 1 };
      if (position.line !== cursorRef.current.line || position.column !== cursorRef.current.column) {
        cursorRef.current = position;
        handlers.current.onCursorChange?.(position);
      }
    }
  }

  return (
    <div
      className={className ? `rh-editor ${className}` : 'rh-editor'}
      data-language={mode}
      data-read-only={readOnly ? 'true' : undefined}
    >
      {readOnly && readOnlyReason ? (
        <p className="rh-editor__notice" role="status">
          {readOnlyReason}
        </p>
      ) : null}
      <div ref={hostRef} className="rh-editor__host" data-testid="latex-editor-host" />
    </div>
  );
});

/** `.tex` and its friends are LaTeX; `.bib` is BibTeX; anything else is plain text. */
function languageOf(fileName?: string): EditorLanguage {
  const extension = (fileName ?? '').toLowerCase().split('.').pop() ?? '';
  if (['tex', 'ltx', 'sty', 'cls', 'bbl', 'dtx'].includes(extension)) return 'latex';
  if (extension === 'bib') return 'bibtex';
  return 'plain';
}

/**
 * Marking LaTeX and BibTeX structure.
 *
 * `stex` is the parser (it gives bracket matching and indentation something to work with),
 * but a `HighlightStyle` needs style tags from `@lezer/highlight`, which this package does
 * not depend on. These decorators mark the three things a researcher actually scans for —
 * a comment, a command, a maths delimiter — and the theme below inks them from tokens.
 */
const latexMarks = new MatchDecorator({
  regexp: /%.*|\\(?:[a-zA-Z@]+\*?|[^a-zA-Z\s])|\$\$?/g,
  decorate(add, from, to, match) {
    const text = match[0];
    const style = text.startsWith('%')
      ? 'rh-tex-comment'
      : text.startsWith('$')
        ? 'rh-tex-math'
        : 'rh-tex-command';
    add(from, to, Decoration.mark({ class: style }));
  },
});

const bibtexMarks = new MatchDecorator({
  regexp: /@[a-zA-Z]+|[a-zA-Z][a-zA-Z0-9_-]*(?=\s*=)/g,
  decorate(add, from, to, match) {
    const style = match[0].startsWith('@') ? 'rh-tex-command' : 'rh-tex-math';
    add(from, to, Decoration.mark({ class: style }));
  },
});

function markingPlugin(marks: MatchDecorator) {
  return ViewPlugin.fromClass(
    class {
      decorations: DecorationSet;
      constructor(view: EditorView) {
        this.decorations = marks.createDeco(view);
      }
      update(update: ViewUpdate) {
        this.decorations = marks.updateDeco(update, this.decorations);
      }
    },
    { decorations: (plugin) => plugin.decorations },
  );
}

const LATEX: Extension = [StreamLanguage.define(stex), markingPlugin(latexMarks)];
const BIBTEX: Extension = [markingPlugin(bibtexMarks)];

function extensionsFor(mode: EditorLanguage): Extension {
  if (mode === 'latex') return LATEX;
  if (mode === 'bibtex') return BIBTEX;
  return [];
}

/**
 * The editor's colours, all of them from semantic tokens.
 *
 * Nothing here is a literal, so the same theme is correct under `data-theme="dark"` and
 * `data-theme="light"`: the variables are resolved by the browser at paint time, and
 * switching the attribute re-inks the editor with everything else.
 */
const rhTheme = EditorView.theme({
  '&': {
    height: '100%',
    color: 'var(--rh-text-primary)',
    backgroundColor: 'var(--rh-surface-pane)',
    fontFamily: 'var(--rh-font-mono)',
    fontSize: 'calc(var(--rh-type-mono-size) * var(--rh-density-font-scale))',
  },
  '&.cm-focused': {
    outline: 'var(--rh-focus-ring-width) solid var(--rh-focus-ring)',
    outlineOffset: 'calc(-1 * var(--rh-focus-ring-width))',
  },
  '.cm-content': {
    caretColor: 'var(--rh-text-primary)',
    lineHeight: 'var(--rh-type-mono-lh)',
  },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--rh-text-primary)' },
  '.cm-selectionBackground, .cm-content ::selection': {
    backgroundColor: 'var(--rh-surface-selected)',
  },
  '&.cm-focused .cm-selectionBackground': { backgroundColor: 'var(--rh-surface-selected)' },
  '.cm-gutters': {
    backgroundColor: 'var(--rh-surface-subtle)',
    color: 'var(--rh-text-muted)',
    border: 'none',
    borderRight: 'var(--rh-border-width) solid var(--rh-border-subtle)',
  },
  '.cm-activeLine': { backgroundColor: 'var(--rh-surface-subtle)' },
  '.cm-activeLineGutter': {
    backgroundColor: 'var(--rh-surface-selected)',
    color: 'var(--rh-text-secondary)',
  },
  '.cm-matchingBracket, .cm-nonmatchingBracket': {
    backgroundColor: 'var(--rh-surface-selected)',
    outline: 'var(--rh-border-width) solid var(--rh-border-strong)',
  },
  '.cm-selectionMatch': { backgroundColor: 'var(--rh-surface-selected)' },
  '.cm-searchMatch': {
    backgroundColor: 'var(--rh-feedback-warning-bg)',
    outline: 'var(--rh-border-width) solid var(--rh-feedback-warning-border)',
  },
  '.cm-searchMatch.cm-searchMatch-selected': { backgroundColor: 'var(--rh-accent-subtle)' },
  '.cm-panels': {
    backgroundColor: 'var(--rh-surface-raised)',
    color: 'var(--rh-text-primary)',
    fontFamily: 'var(--rh-font-sans)',
    fontSize: 'calc(var(--rh-type-body-sm-size) * var(--rh-density-font-scale))',
  },
  '.cm-panels.cm-panels-top': {
    borderBottom: 'var(--rh-border-width) solid var(--rh-border-subtle)',
  },
  '.cm-panel input, .cm-panel button, .cm-panel select': {
    color: 'var(--rh-text-primary)',
    backgroundColor: 'var(--rh-surface-pane)',
    border: 'var(--rh-border-width) solid var(--rh-border-default)',
    borderRadius: 'var(--rh-radius-control)',
  },
  '.cm-tooltip': {
    backgroundColor: 'var(--rh-surface-raised)',
    color: 'var(--rh-text-primary)',
    border: 'var(--rh-border-width) solid var(--rh-border-default)',
  },
  // The LaTeX marks: ink and weight, never hue alone.
  '.rh-tex-comment': { color: 'var(--rh-text-muted)', fontStyle: 'italic' },
  '.rh-tex-command': { color: 'var(--rh-text-primary)', fontWeight: '600' },
  '.rh-tex-math': { color: 'var(--rh-text-secondary)', fontWeight: '600' },
});
