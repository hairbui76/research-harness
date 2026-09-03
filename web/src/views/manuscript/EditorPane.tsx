/**
 * The source pane: the Design System's frame around this client's CodeMirror editor.
 *
 * The frame owns the toolbar, the file's state in words, the conflict banner and the cursor
 * readout; the buffer, the LaTeX mode and the undo stack belong to `LatexEditor`. Neither
 * of them writes a file — Save, Compile, jump-to-PDF and both conflict answers are
 * callbacks the workspace holds.
 *
 * `Mod-S` reaches `onSave` through the editor, and the frame's Save button reaches the same
 * function, so a save is one act with one path however it was asked for (LaTeX spec §4).
 */
import { forwardRef } from 'react';
import { SourceEditorFrame } from '@research-harness/design';
import type { EditorFrameState } from '@research-harness/design';
import { LatexEditor } from '../../editor';
import type { CursorPosition, LatexEditorHandle } from '../../editor';

export interface EditorPaneProps {
  state: EditorFrameState;
  /** The open buffer's text. Absent when no file is open. */
  value: string | null;
  fileName?: string;
  onChange: (value: string) => void;
  onSave?: () => void;
  onCompile?: () => void;
  onSyncForward?: () => void;
  onCursorChange?: (position: CursorPosition) => void;
  onReloadFromDisk?: () => void;
  onKeepMine?: () => void;
  synctex: 'available' | 'unavailable';
  synctexReason?: string;
  saving?: boolean;
  compiling?: boolean;
  /** Why the editor is read-only — an agent host, in practice. */
  readOnlyReason?: string;
  emptyLabel?: string;
}

export const EditorPane = forwardRef<LatexEditorHandle, EditorPaneProps>(function EditorPane(
  {
    state,
    value,
    fileName,
    onChange,
    onSave,
    onCompile,
    onSyncForward,
    onCursorChange,
    onReloadFromDisk,
    onKeepMine,
    synctex,
    synctexReason,
    saving = false,
    compiling = false,
    readOnlyReason,
    emptyLabel = 'Choose a file to open it',
  },
  ref,
) {
  return (
    <SourceEditorFrame
      state={state}
      synctex={synctex}
      {...(synctexReason === undefined ? {} : { synctexReason })}
      saving={saving}
      compiling={compiling}
      emptyLabel={emptyLabel}
      {...(onSave ? { onSave } : {})}
      {...(onCompile ? { onCompile } : {})}
      {...(onSyncForward ? { onSyncForward } : {})}
      {...(onReloadFromDisk ? { onReloadFromDisk } : {})}
      {...(onKeepMine ? { onKeepMine } : {})}
    >
      {value === null ? null : (
        <LatexEditor
          ref={ref}
          value={value}
          onChange={onChange}
          {...(onSave ? { onSave: () => onSave() } : {})}
          {...(onCursorChange ? { onCursorChange } : {})}
          {...(fileName ? { fileName } : {})}
          readOnly={state.readOnly ?? false}
          {...(readOnlyReason === undefined ? {} : { readOnlyReason })}
        />
      )}
    </SourceEditorFrame>
  );
});
