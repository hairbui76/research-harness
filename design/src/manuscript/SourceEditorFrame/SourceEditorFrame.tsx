import { forwardRef, useEffect, useState } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { useId } from '../../hooks/useId';
import { Button } from '../../primitives/Button';
import { Icon } from '../../primitives/Icon';
import { AsyncState } from '../../states/AsyncState';
import type { EditorFrameState } from '../models';

export interface SourceEditorFrameProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onSelect'> {
  state: EditorFrameState;
  /** Save the buffer to disk. Documented on the button as Ctrl/Cmd+S. */
  onSave?: () => void;
  onCompile?: () => void;
  /** Jump from the cursor to the matching place in the PDF. */
  onSyncForward?: () => void;
  /** Disables jump-to-PDF and explains why. */
  synctex?: 'available' | 'unavailable';
  synctexReason?: string;
  /** Conflict resolution. Presentation only: the frame does nothing to the file. */
  onReloadFromDisk?: () => void;
  onKeepMine?: () => void;
  saving?: boolean;
  compiling?: boolean;
  /** The editor engine — CodeMirror in the Web client. */
  children?: ReactNode;
  /** Accessible name of the frame. */
  label?: string;
  /** Shown when `state.path` is absent. */
  emptyLabel?: string;
}

interface StatusChip {
  key: string;
  icon: 'pen-line' | 'alert-triangle' | 'lock' | 'circle-check';
  text: string;
  tone: 'dirty' | 'conflict' | 'read-only' | 'saved';
  detail?: string;
}

/**
 * Why Save cannot be pressed, named by the chip that already says it.
 *
 * Save used to be offered on a buffer whose own chip read "Saved" — an act with nothing to
 * act on (design critique, minor). Disabling it raises the question the critique asks of
 * every disabled control: *why*. The answer is on screen already, one row up, so the button
 * points at that chip rather than growing a second sentence beside it. Read-only outranks
 * "nothing to save": a host that may not write cannot save a dirty buffer either.
 */
function saveBlockedBy(state: EditorFrameState): StatusChip['key'] | null {
  if (state.readOnly) return 'read-only';
  return state.dirty ? null : 'saved';
}

function chipsFor(state: EditorFrameState): StatusChip[] {
  const chips: StatusChip[] = [];
  if (state.conflict) {
    chips.push({ key: 'conflict', icon: 'alert-triangle', text: 'Changed on disk', tone: 'conflict' });
  }
  chips.push(
    state.dirty
      ? { key: 'dirty', icon: 'pen-line', text: 'Unsaved changes', tone: 'dirty' }
      : { key: 'saved', icon: 'circle-check', text: 'Saved', tone: 'saved' },
  );
  if (state.readOnly) {
    chips.push({
      key: 'read-only',
      icon: 'lock',
      text: 'Read-only',
      tone: 'read-only',
      ...(state.readOnlyReason === undefined ? {} : { detail: state.readOnlyReason }),
    });
  }
  return chips;
}

/**
 * The frame around whichever editor engine the application supplies.
 *
 * It owns the toolbar, the file's state in words, the conflict banner and the cursor
 * readout; the buffer, the syntax mode and the undo stack belong to the engine passed as
 * `children`. Nothing here writes a file: Save, Compile, jump-to-PDF and both conflict
 * answers are callbacks.
 */
export const SourceEditorFrame = forwardRef<HTMLDivElement, SourceEditorFrameProps>(
  function SourceEditorFrame(
    {
      state,
      onSave,
      onCompile,
      onSyncForward,
      synctex = 'available',
      synctexReason,
      onReloadFromDisk,
      onKeepMine,
      saving = false,
      compiling = false,
      children,
      label = 'Manuscript source',
      emptyLabel = 'No file open',
      className,
      id,
      ...rest
    },
    ref,
  ) {
    const baseId = useId(id, 'rh-editorframe');
    const syncReasonId = `${baseId}-sync-reason`;
    const syncBlocked = synctex !== 'available';
    const chips = chipsFor(state);
    const chipId = (key: string): string => `${baseId}-chip-${key}`;
    const saveBlocked = saveBlockedBy(state);

    /*
     * Why a jump did nothing, said when one is attempted and not before.
     *
     * "Source-to-PDF navigation is unavailable" held a row above the editor for the whole
     * session, whether or not anyone ever asked to jump — a permanent statement of an
     * absence that matters for one keystroke (design critique, minor). The control stays
     * pressable so it can answer, because a disabled button with no reason at it is the
     * defect this replaces rather than a fix for it, and the answer clears itself the moment
     * the build has a map.
     */
    const [syncNote, setSyncNote] = useState<string | null>(null);
    useEffect(() => {
      if (!syncBlocked) setSyncNote(null);
    }, [syncBlocked]);

    return (
      <section
        ref={ref}
        id={baseId}
        aria-label={state.path ? `${label}: ${state.path}` : label}
        className={cx('rh-source-editor', className)}
        data-dirty={state.dirty ? '' : undefined}
        data-conflict={state.conflict ? '' : undefined}
        data-read-only={state.readOnly ? '' : undefined}
        {...rest}
      >
        <div className="rh-source-editor__toolbar">
          <p className="rh-source-editor__path" title={state.path}>
            <Icon name="file-code" size={16} />
            <span className="rh-source-editor__path-text">{state.path ?? emptyLabel}</span>
          </p>

          <div className="rh-source-editor__chips">
            {chips.map((chip) => (
              <span
                key={chip.key}
                id={chipId(chip.key)}
                className="rh-source-editor__chip"
                data-tone={chip.tone}
              >
                <Icon name={chip.icon} size={14} />
                <span>{chip.detail ? `${chip.text}: ${chip.detail}` : chip.text}</span>
              </span>
            ))}
          </div>

          <div className="rh-source-editor__actions">
            <Button
              size="sm"
              variant="secondary"
              iconStart="save"
              loading={saving}
              disabled={!onSave || saveBlocked !== null}
              {...(saveBlocked === null ? {} : { 'aria-describedby': chipId(saveBlocked) })}
              aria-keyshortcuts="Control+S Meta+S"
              onClick={onSave}
            >
              Save
            </Button>
            <Button
              size="sm"
              variant="primary"
              iconStart="play"
              loading={compiling}
              disabled={!onCompile}
              onClick={onCompile}
            >
              Compile
            </Button>
            <Button
              size="sm"
              variant="ghost"
              iconStart="crosshair"
              disabled={!onSyncForward}
              aria-describedby={syncNote ? syncReasonId : undefined}
              onClick={() => {
                if (syncBlocked) {
                  setSyncNote(
                    `Jump to PDF has nothing to point at: ${
                      synctexReason ?? 'this build recorded no SyncTeX map'
                    }.`,
                  );
                  return;
                }
                onSyncForward?.();
              }}
            >
              Jump to PDF
            </Button>
          </div>

          {syncNote ? (
            <p id={syncReasonId} className="rh-source-editor__note" role="status">
              <Icon name="info" size={14} />
              <span>{syncNote}</span>
            </p>
          ) : null}
        </div>

        {state.conflict ? (
          <AsyncState
            className="rh-source-editor__conflict"
            kind="blocked"
            title={`${state.path ?? 'This file'} changed on disk`}
            description={state.conflict.message}
            safety={{ draft: 'at-risk', source: 'at-risk' }}
            actions={[
              ...(onReloadFromDisk
                ? [
                    {
                      label: 'Reload from disk',
                      onClick: onReloadFromDisk,
                      iconStart: 'refresh-cw' as const,
                    },
                  ]
                : []),
              ...(onKeepMine
                ? [{ label: 'Keep mine', onClick: onKeepMine, iconStart: 'pen-line' as const }]
                : []),
            ]}
          />
        ) : null}

        <div className="rh-source-editor__surface">
          {children ?? <AsyncState kind="empty" title={emptyLabel} compact />}
        </div>

        <div className="rh-source-editor__status">
          <span className="rh-source-editor__cursor">
            {state.cursor
              ? `Ln ${state.cursor.line}, Col ${state.cursor.column}`
              : 'No cursor position'}
          </span>
          <span className="rh-source-editor__hint">
            <kbd>Ctrl</kbd>/<kbd>Cmd</kbd>+<kbd>S</kbd> saves
          </span>
        </div>
      </section>
    );
  },
);
