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
}

/** What each degradation is, in one sentence, with the icon that is not a spinner. */
const WORDING: Record<GraphDegradation, { icon: IconName; line: string }> = {
  rebuilding: {
    icon: 'refresh-cw',
    line: 'Rebuilding the research index; completing from the project listings.',
  },
  absent: {
    icon: 'hard-drive',
    line: 'The research index is not built yet; completing from the project listings.',
  },
  unreadable: {
    icon: 'hard-drive',
    line: 'The research index is not answering; completing from the project listings.',
  },
};

export function GraphStatusNote({
  degradation,
  answering,
  onRecheck,
  onRebuild,
  rebuilding = false,
  rebuildError = null,
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
      role="status"
      {...(degradation === 'rebuilding' ? { 'aria-busy': true } : {})}
    >
      <Icon name={wording.icon} size={14} />
      <span className="rh-web-graph-note__line">{wording.line}</span>
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
