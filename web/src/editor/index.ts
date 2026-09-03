/**
 * The CodeMirror adapter for manuscript source: `.tex` and `.bib` files, controlled from
 * outside, saved only when the researcher asks, and reporting the cursor in the 1-based
 * lines SyncTeX and every compiler diagnostic speak.
 */
export { LatexEditor } from './LatexEditor';
export type {
  CursorPosition,
  EditorLanguage,
  LatexEditorHandle,
  LatexEditorProps,
} from './LatexEditor';
