/**
 * "The graph is not answering completion" — said once, quietly, beside the destination.
 *
 * Graph spec §8 is explicit that *direct canonical reads remain possible if the graph is
 * unavailable or rebuilding*, and the cockpit does exactly that: `@` completion silently
 * falls back to `state.index` and `evidence.list`. Silently is the problem. A researcher
 * whose picker has quietly stopped offering sessions, messages and manuscript files should
 * be told why, once, in the composer they are typing in — not left to wonder whether a
 * missing reference means the object is gone.
 *
 * It is a **capability note, not an error**. An index that has never been built is the
 * ordinary state of a project on its first day, and it used to arrive as a 220px framed
 * notice with a kind label, a three-line description, a lock-iconed safety statement and
 * two buttons — the loudest object on an empty conversation. One line, beside the line that
 * says where the message goes, is the whole of what it has to say.
 *
 * What that line still has to carry, because wave one put it there and it is product
 * behaviour rather than presentation:
 *
 * - **The state the daemon actually reported.** A rebuild that is running, an index that
 *   was never built and one that cannot be read are three different facts and read as
 *   three different sentences. Only the running one is `aria-busy`; the other two are not
 *   in progress and must never look as though they are.
 * - **The action its own wording asks for.** `state.rebuild` is the cockpit's
 *   `research rebuild`. It is admin and human-only, so a window that may not write is
 *   offered `Check again` alone, a rebuild already in flight is not started twice, and a
 *   refusal is printed in the daemon's own words with the note left standing, because
 *   nothing was built.
 *
 * The index that is answering instead is on the element as `data-answering` rather than in
 * the sentence: `state.index` is a capability name, and the researcher's word for what it
 * holds is "the project listings" (2E).
 */
import { useEffect, useState } from 'react';
import { Button, Icon } from '@research-harness/design';
import type { IconName } from '@research-harness/design';
import type { GraphDegradation } from './graphReferenceProvider';

export interface GraphStatusNoteProps {
  /** Null when the graph is answering; then nothing is rendered. */
  degradation: GraphDegradation | null;
  /** Which index is answering completion instead. */
  answering: string;
  /** Ask `graph.status` again. A rebuild finishes and the picker should notice. */
  onRecheck?: () => void;
  /**
   * Run `state.rebuild`, then read the status again.
   *
   * Omitted when the window may not write, which is what leaves a read-only cockpit with
   * `Check again` alone rather than with a button the daemon would only refuse.
   */
  onRebuild?: () => void;
  /** True while that rebuild is out. The action is disabled, not withdrawn. */
  rebuilding?: boolean;
  /** The daemon's own sentence about a rebuild it refused or could not finish. */
  rebuildError?: string | null;
  /**
   * Whether this state has already been read once in this project.
   *
   * A folded note says the same thing in its shortest true form and keeps the same action,
   * so that it can share the composer's footer line with the keyboard hint instead of
   * taking a row of its own. Nothing is hidden by folding: the state is still named and
   * the rebuild is still one press away.
   */
  folded?: boolean;
}

/**
 * What each degradation is, with the icon that is not a spinner.
 *
 * `line` is what it says the first time, which is the sentence that has to teach: the
 * state, and what is answering instead of the index. `short` is what it says afterwards —
 * the same state, without the clause the researcher has already read — so that a standing
 * fact costs the composer half a row rather than a whole one.
 */
const WORDING: Record<GraphDegradation, { icon: IconName; line: string; short: string }> = {
  rebuilding: {
    icon: 'refresh-cw',
    line: 'Rebuilding the research index; completing from the project listings.',
    short: 'Rebuilding the research index',
  },
  absent: {
    icon: 'hard-drive',
    line: 'The research index is not built yet; completing from the project listings.',
    short: 'Research index not built',
  },
  unreadable: {
    icon: 'hard-drive',
    line: 'The research index is not answering; completing from the project listings.',
    short: 'Research index not answering',
  },
};

/** Where this browser remembers that a project has been told about its index once. */
const READ_PREFIX = 'rh.index-note-read.';

/**
 * Whether this project has already been shown this index state, in full.
 *
 * The same shape as the composer's egress disclosure: a convenience in `localStorage`, and
 * a storage that throws simply means the long form is shown again — which is the safe way
 * for this to fail, because the long form is the one that teaches. A *different*
 * degradation is news again and gets its own long showing; nothing folds a state the
 * researcher has never seen.
 */
export function useIndexNoteRead(
  project: string | null,
  degradation: GraphDegradation | null,
): boolean {
  const key = degradation === null ? null : `${READ_PREFIX}${project ?? ''}.${degradation}`;
  const [read, setRead] = useState(false);
  useEffect(() => {
    if (key === null) {
      setRead(false);
      return;
    }
    try {
      setRead(window.localStorage.getItem(key) !== null);
      window.localStorage.setItem(key, 'read');
    } catch {
      setRead(false);
    }
  }, [key]);
  return read;
}

export function GraphStatusNote({
  degradation,
  answering,
  onRecheck,
  onRebuild,
  rebuilding = false,
  rebuildError = null,
  folded = false,
}: GraphStatusNoteProps) {
  if (degradation === null) return null;
  const wording = WORDING[degradation];
  // A rebuild that is already running is not started again from here.
  const offerRebuild = onRebuild !== undefined && degradation !== 'rebuilding';
  return (
    <span
      className="rh-web-graph-note"
      data-degradation={degradation}
      data-answering={answering}
      data-folded={folded || undefined}
      role="status"
      {...(degradation === 'rebuilding' ? { 'aria-busy': true } : {})}
    >
      <Icon name={wording.icon} size={14} />
      <span className="rh-web-graph-note__line">{folded ? wording.short : wording.line}</span>
      {offerRebuild ? (
        <Button
          size="sm"
          variant="ghost"
          iconStart="hard-drive"
          disabled={rebuilding}
          onClick={onRebuild}
        >
          Rebuild the index
        </Button>
      ) : onRecheck ? (
        <Button size="sm" variant="ghost" iconStart="refresh-cw" onClick={onRecheck}>
          Check again
        </Button>
      ) : null}
      {/* The daemon's sentence, verbatim: why a rebuild was refused is its answer to give. */}
      {rebuildError !== null ? (
        <span className="rh-web-graph-note__refusal">{rebuildError}</span>
      ) : null}
    </span>
  );
}
