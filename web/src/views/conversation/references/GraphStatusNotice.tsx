/**
 * "The graph is not answering completion" — said once, where it matters.
 *
 * Graph spec §8 is explicit that *direct canonical reads remain possible if the graph is
 * unavailable or rebuilding*, and the cockpit does exactly that: `@` completion silently
 * falls back to `state.index` and `evidence.list`. Silently is the problem. A researcher
 * whose picker has quietly stopped offering sessions, messages and manuscript files should
 * be told why, once, beside the composer they are typing in — not left to wonder whether a
 * missing reference means the object is gone.
 *
 * All three degradations speak the Design System's one vocabulary for the index, so the
 * graph pane, the composer and the search surface describe the same fact in the same
 * words. What they must not share is the *kind*: a state that is not in progress may not
 * look like one. Only a rebuild that is actually running is `index-rebuilding`, with its
 * spinner and its "Index rebuild" bar; an index that was never built is `index-absent`,
 * and one that cannot be read is `index-unreadable` — both `partial`, because completion
 * *is* answering, from a narrower source, and no bar is ever going to fill.
 */
import { ResearchState } from '@research-harness/design';
import type { ResearchStateCase } from '@research-harness/design';
import type { GraphDegradation } from './graphReferenceProvider';

export interface GraphStatusNoticeProps {
  /** Null when the graph is answering; then nothing is rendered. */
  degradation: GraphDegradation | null;
  /** Which index is answering completion instead. */
  answering: string;
  /** Ask `graph.status` again. A rebuild finishes and the picker should notice. */
  onRecheck?: () => void;
}

/** What each degradation is, and what it means for the picker, in the researcher's terms. */
const WORDING: Record<
  GraphDegradation,
  { state: ResearchStateCase; title: string; description: string }
> = {
  rebuilding: {
    state: { case: 'index-rebuilding' },
    title: 'Rebuilding the research index',
    description:
      'Reference completion is answering from the project listings until the rebuild ' +
      'finishes, so sessions, messages and manuscript files are not offered yet. Typing a ' +
      'reference in full still works, and every reference is resolved against the ' +
      'canonical files when you send.',
  },
  absent: {
    state: { case: 'index-absent' },
    title: 'The research index has not been built yet',
    description:
      'Reference completion is answering from the project listings. Run a rebuild to ' +
      'complete over sessions, messages, attachments and manuscript files as well.',
  },
  unreadable: {
    state: { case: 'index-unreadable' },
    title: 'The research index is not answering',
    description:
      'Reference completion is answering from the project listings instead. Nothing is ' +
      'lost: the index is derived from the durable files and can be rebuilt.',
  },
};

export function GraphStatusNotice({
  degradation,
  answering,
  onRecheck,
}: GraphStatusNoticeProps) {
  if (degradation === null) return null;
  const wording = WORDING[degradation];
  return (
    <ResearchState
      state={wording.state}
      compact
      title={wording.title}
      description={`${wording.description} (Completing from ${answering}.)`}
      {...(onRecheck
        ? { actions: [{ label: 'Check again', onClick: onRecheck, iconStart: 'refresh-cw' }] }
        : {})}
    />
  );
}
