/**
 * `@` completion over the ResearchGraph, with W1's index provider behind it.
 *
 * `useReferenceQuery`'s `ReferenceProvider` is a one-method seam, and this is its second
 * implementation: `graph.autocomplete` answers with real node kinds, the row's own
 * authority and its egress class, over every namespace the projection holds — sessions,
 * messages, attachments and manuscript files as well as the corpus and the scientific
 * state. `indexReferenceProvider` completes over `state.index` and `evidence.list`, which
 * is less, but which works with no projection at all.
 *
 * Which one answers is decided by the daemon, never guessed here (graph spec §8: *direct
 * canonical reads remain possible if the graph is unavailable or rebuilding*):
 *
 * - `graph.status` is read once per client, and only while the conversation is the screen
 *   on the researcher's cursor. `available: false` — no database, or one
 *   written by a schema version this build does not read — or `rebuilding: true` means the
 *   index cannot answer completely, so the fallback answers instead and the composer says
 *   so once, in the Design System's own state for what is actually true of the index —
 *   rebuilding, absent, or there but unreadable.
 * - A `graph.autocomplete` call that fails *after* that check falls back for that query and
 *   marks the status for re-reading, so a graph that dies mid-session degrades to the
 *   listings rather than to an empty picker.
 *
 * Nothing here filters, ranks or re-labels a match. The daemon applies the visibility
 * filter it was asked for and returns rows carrying their own authority; the picker draws
 * them.
 */
import { useCallback, useMemo, useState } from 'react';
import type { EntityRefModel } from '@research-harness/design';
import type { HarnessClient } from '../../../api/client';
import type { GraphNodeKind, GraphStatusView, GraphVisibilityName } from '../../../api/dto';
import { useProjectPaths } from '../../../app/projectPaths';
import { useAsync } from '../../../app/useAsync';
import type { ReferenceProvider } from '../useReferenceQuery';
import { refFromNode } from './mappers';
import type { PathHref } from '../mappers';

/** How many rows the picker is offered. Matches `useReferenceQuery`'s own limit. */
const LIMIT = 12;

export interface GraphReferenceOptions {
  /** Answers when the graph cannot. W1's `indexReferenceProvider`, in practice. */
  fallback: ReferenceProvider;
  /**
   * Egress classes to complete over. Empty completes over everything on this machine,
   * which is what a private session wants; a `project` session passes `['project']` so the
   * picker never offers a reference the assembler would then have to omit.
   */
  visibility?: readonly GraphVisibilityName[];
  /** Restrict completion to these node kinds. Empty completes over every namespace. */
  kinds?: readonly GraphNodeKind[];
  limit?: number;
  /**
   * False leaves `graph.status` unread and the fallback in place.
   *
   * The provider is mounted for the whole cockpit, because the session rail is; the picker
   * only exists on the conversation route. So a researcher reading a claim pays for one
   * `session.list` and nothing else, exactly as task W1 promised.
   */
  enabled?: boolean;
  /** Rewrites each row's `href` for the project tree the picker is open in. */
  href?: PathHref;
}

/**
 * The provider itself.
 *
 * `available` is a callback rather than a value so the hook below can flip it without
 * rebuilding the provider (and therefore without resetting `useReferenceQuery`'s state
 * under the researcher's cursor mid-word).
 */
export function graphReferenceProvider(
  client: HarnessClient,
  options: GraphReferenceOptions & { available: () => boolean; onFailure?: () => void },
): ReferenceProvider {
  const { fallback, available, onFailure } = options;
  return {
    id: 'graph.autocomplete',
    async search(query: string): Promise<EntityRefModel[]> {
      if (!available()) return fallback.search(query);
      try {
        const result = await client.autocompleteReferences({
          prefix: query,
          limit: options.limit ?? LIMIT,
          ...(options.visibility?.length ? { visibility: [...options.visibility] } : {}),
          ...(options.kinds?.length ? { kinds: [...options.kinds] } : {}),
        });
        // Every row came out of the index, so it is `resolved` *there*; whether the
        // canonical object still agrees is `graph.resolve`'s answer, asked at send time.
        return result.matches.map((node) =>
          refFromNode(node, options.href ? { href: options.href } : {}),
        );
      } catch {
        onFailure?.();
        return fallback.search(query);
      }
    },
  };
}

/** Why the graph is not answering completion, in the daemon's own terms. */
export type GraphDegradation = 'rebuilding' | 'absent' | 'unreadable';

export interface GraphReferencesApi {
  /** Hand this to `ConversationProvider`; it never changes identity while typing. */
  provider: ReferenceProvider;
  /** `graph.status`, or null while it is being read or after it failed. */
  status: GraphStatusView | null;
  /** Null while the graph is answering; otherwise why it is not. */
  degradation: GraphDegradation | null;
  /** Which index actually answers right now: `graph.autocomplete` or `state.index`. */
  answering: string;
  /** Ask `graph.status` again — a rebuild finishes, and the picker should notice. */
  recheck: () => void;
}

/**
 * The provider swap, as a hook.
 *
 * One `graph.status` read per client decides it, and the result is also what the composer
 * renders its notice from — the notice and the fallback are the same fact reported twice,
 * rather than two independent guesses that could disagree.
 */
export function useGraphReferences(
  client: HarnessClient,
  options: GraphReferenceOptions,
): GraphReferencesApi {
  const { fallback, visibility, kinds, limit, enabled = true } = options;
  const { href } = useProjectPaths();
  const status = useAsync<GraphStatusView | null>(
    async () => (enabled ? client.graphStatus() : null),
    [client, enabled],
  );
  const [failed, setFailed] = useState(false);

  const degradation = useMemo<GraphDegradation | null>(() => {
    // Nothing is claimed about an index nobody has asked about, and nothing is claimed
    // while the first read is in flight: the provider falls back for that moment, and the
    // composer shows no notice for a state that has not been reported.
    if (!enabled || status.loading) return null;
    if (failed) return 'unreadable';
    if (status.error !== null || status.data === null) return 'unreadable';
    if (status.data.rebuilding) return 'rebuilding';
    if (!status.data.available) return status.data.exists ? 'unreadable' : 'absent';
    return null;
  }, [enabled, failed, status.data, status.error, status.loading]);

  // Read through a ref-like closure: the provider must not be rebuilt when the status
  // arrives, or `useReferenceQuery` would re-run mid-word.
  const answerable = enabled && !status.loading && degradation === null;
  const available = useEvent(() => answerable);
  const onFailure = useEvent(() => setFailed(true));

  const provider = useMemo(
    () =>
      graphReferenceProvider(client, {
        fallback,
        available,
        onFailure,
        href,
        ...(visibility ? { visibility } : {}),
        ...(kinds ? { kinds } : {}),
        ...(limit === undefined ? {} : { limit }),
      }),
    [available, client, fallback, href, kinds, limit, onFailure, visibility],
  );

  const recheck = useCallback(() => {
    setFailed(false);
    status.reload();
  }, [status]);

  return {
    provider,
    status: status.data,
    degradation,
    answering: answerable ? provider.id : fallback.id,
    recheck,
  };
}

/**
 * A callback with a stable identity that always sees the latest render's values.
 *
 * React's `useEvent` in miniature, and the reason it is here: the provider is a dependency
 * of `useReferenceQuery`'s `search`, so rebuilding it while a researcher is typing would
 * cancel their in-flight query. The closure reads the current value instead.
 */
function useEvent<T>(read: () => T): () => T {
  const [box] = useState<{ read: () => T }>(() => ({ read }));
  box.read = read;
  return useMemo(() => () => box.read(), [box]);
}
