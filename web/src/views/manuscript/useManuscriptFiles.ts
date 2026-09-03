/**
 * The manuscript's files, and the buffers a researcher is editing.
 *
 * LaTeX spec §4 is the whole design: files under `manuscript/` are ordinary user-owned
 * project files, so this hook reads one only when a file is opened and writes one only when
 * a save is asked for. Nothing here autosaves, and nothing here merges.
 *
 * A buffer is kept per path rather than per editor, so switching files does not throw away
 * an unsaved edit and the tree can mark every dirty file rather than only the open one.
 * `saved` is the text as the daemon last reported it, `hash` is the `content_hash` the next
 * save must present, and `text` is what the researcher has typed.
 *
 * A conflict — the bytes on disk are not the ones this buffer was read from — is a refusal,
 * never a merge. The daemon's message names both hashes; this client does not parse them
 * out of prose, it re-reads the file, which is the only way to learn the authoritative hash.
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import { CapabilityError } from '../../api/client';
import type { HarnessClient } from '../../api/client';
import type { FileSnapshot, ManuscriptFileKind, ManuscriptTree } from '../../api/dto';
import { useAsync } from '../../app/useAsync';
import type { FileMarkers } from './mappers';

/** One open file: what is on disk, what the researcher typed, and the hash between them. */
export interface SourceBuffer {
  path: string;
  kind: ManuscriptFileKind;
  /** The text the researcher is editing. */
  text: string;
  /** The text the daemon last reported for this path. */
  saved: string;
  /** `content_hash` of `saved`; the next `manuscript.write_file` presents it. */
  hash: string;
  /** The daemon's refusal, when the file changed on disk under this buffer. */
  conflict: string | null;
}

export interface ManuscriptFilesState {
  tree: ManuscriptTree | null;
  treeLoading: boolean;
  treeError: string | null;
  reloadTree: () => void;
  /** The path shown in the editor, or null when nothing is open. */
  activePath: string | null;
  active: SourceBuffer | null;
  /** Dirty and conflicted state per path, for the tree's written markers. */
  markers: Record<string, FileMarkers>;
  opening: boolean;
  openError: string | null;
  saving: boolean;
  saveError: string | null;
  open: (path: string) => Promise<void>;
  change: (text: string) => void;
  /** Saves the active buffer. Answers false when the daemon refused it. */
  save: () => Promise<boolean>;
  /** Re-read from disk and discard the local text. */
  reloadFromDisk: () => Promise<void>;
  /** Re-read only to learn the new hash; the local text stays and the next save uses it. */
  keepMine: () => Promise<void>;
  /** Adopt a snapshot the daemon just wrote for us — an applied candidate, say. */
  adopt: (snapshot: FileSnapshot) => void;
}

/**
 * Whether a refusal is the conflict `manuscript.write_file` raises.
 *
 * `ErrorBody` carries a stable `code` and a message and no structured hashes, so a conflict
 * is recognised by the daemon's own sentence (and by a dedicated code, if one is ever
 * added). The hashes inside the message are deliberately *not* parsed: the answer to a
 * conflict is to re-read the file.
 */
export function isWriteConflict(error: unknown): error is CapabilityError {
  return (
    error instanceof CapabilityError &&
    (error.code === 'conflict' || /changed outside the harness/i.test(error.message))
  );
}

function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

function bufferFrom(snapshot: FileSnapshot, text?: string): SourceBuffer {
  return {
    path: snapshot.path,
    kind: snapshot.kind,
    text: text ?? snapshot.content,
    saved: snapshot.content,
    hash: snapshot.content_hash,
    conflict: null,
  };
}

export function useManuscriptFiles(client: HarnessClient): ManuscriptFilesState {
  const tree = useAsync(() => client.manuscriptFiles(), [client]);
  const [buffers, setBuffers] = useState<Record<string, SourceBuffer>>({});
  const [activePath, setActivePath] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const [openError, setOpenError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // The callbacks below read the current buffers without depending on them, so that `open`
  // and `save` keep one identity across every keystroke.
  const latest = useRef({ buffers, activePath });
  latest.current = { buffers, activePath };

  const active = activePath === null ? null : (buffers[activePath] ?? null);

  const open = useCallback(
    async (path: string): Promise<void> => {
      setOpenError(null);
      setActivePath(path);
      // An already-open file keeps its buffer: opening a file the researcher has edited
      // must not silently discard what they typed.
      if (latest.current.buffers[path]) return;
      setOpening(true);
      try {
        const snapshot = await client.manuscriptReadFile(path);
        setBuffers((current) =>
          current[path] ? current : { ...current, [path]: bufferFrom(snapshot) },
        );
      } catch (cause) {
        setOpenError(messageOf(cause));
      } finally {
        setOpening(false);
      }
    },
    [client],
  );

  const change = useCallback((text: string): void => {
    const path = latest.current.activePath;
    if (path === null) return;
    setBuffers((current) => {
      const buffer = current[path];
      if (!buffer || buffer.text === text) return current;
      return { ...current, [path]: { ...buffer, text } };
    });
  }, []);

  const save = useCallback(async (): Promise<boolean> => {
    const path = latest.current.activePath;
    const buffer = path === null ? undefined : latest.current.buffers[path];
    if (!path || !buffer) return false;
    setSaving(true);
    setSaveError(null);
    try {
      const snapshot = await client.manuscriptWriteFile(path, buffer.text, buffer.hash);
      setBuffers((current) => ({ ...current, [path]: bufferFrom(snapshot, snapshot.content) }));
      return true;
    } catch (cause) {
      if (isWriteConflict(cause)) {
        setBuffers((current) => {
          const existing = current[path];
          return existing ? { ...current, [path]: { ...existing, conflict: cause.message } } : current;
        });
        return false;
      }
      setSaveError(messageOf(cause));
      return false;
    } finally {
      setSaving(false);
    }
  }, [client]);

  const reloadFromDisk = useCallback(async (): Promise<void> => {
    const path = latest.current.activePath;
    if (path === null) return;
    setSaveError(null);
    try {
      const snapshot = await client.manuscriptReadFile(path);
      setBuffers((current) => ({ ...current, [path]: bufferFrom(snapshot) }));
    } catch (cause) {
      setSaveError(messageOf(cause));
    }
  }, [client]);

  const keepMine = useCallback(async (): Promise<void> => {
    const path = latest.current.activePath;
    const buffer = path === null ? undefined : latest.current.buffers[path];
    if (!path || !buffer) return;
    setSaveError(null);
    try {
      // The re-read is for the hash, not the text: the researcher's words stay, and the
      // next save presents the hash of what is on disk now, so it is checked rather than
      // forced.
      const snapshot = await client.manuscriptReadFile(path);
      setBuffers((current) => {
        const existing = current[path];
        if (!existing) return current;
        return { ...current, [path]: bufferFrom(snapshot, existing.text) };
      });
    } catch (cause) {
      setSaveError(messageOf(cause));
    }
  }, [client]);

  const adopt = useCallback((snapshot: FileSnapshot): void => {
    setBuffers((current) => ({ ...current, [snapshot.path]: bufferFrom(snapshot) }));
  }, []);

  const markers = useMemo<Record<string, FileMarkers>>(() => {
    const result: Record<string, FileMarkers> = {};
    for (const buffer of Object.values(buffers)) {
      const dirty = buffer.text !== buffer.saved;
      const conflict = buffer.conflict !== null;
      if (dirty || conflict) result[buffer.path] = { dirty, conflict };
    }
    return result;
  }, [buffers]);

  return {
    tree: tree.data,
    treeLoading: tree.loading,
    treeError: tree.error,
    reloadTree: tree.reload,
    activePath,
    active,
    markers,
    opening,
    openError,
    saving,
    saveError,
    open,
    change,
    save,
    reloadFromDisk,
    keepMine,
    adopt,
  };
}
