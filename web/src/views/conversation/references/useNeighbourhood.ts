/**
 * One hop around the selected object, both directions, grouped by relation.
 *
 * This is the inspector half of graph spec §11.2 — *traverse Claim → supporting /
 * contradicting Evidence → exact Artifact anchors in both directions* — and of the
 * conversation spec's two-way navigation (§2): a reference in a message opens its object,
 * and the object shows what the project says is around it, including the messages that
 * mentioned it.
 *
 * The privacy rule is the whole reason the visibility filter is a parameter rather than a
 * constant. Graph spec §8: *a graph traversal cannot bypass an egress restriction merely
 * because a neighbouring public node is allowed*. The daemon enforces that — an excluded
 * node is marked visited and never expanded — and this hook's job is to ask the question
 * with the right class and then render **exactly** what comes back. Nothing is filtered,
 * re-added or inferred on this side; if a private prior-session message is missing from a
 * project-visible object's neighbourhood, it is missing because the graph did not return
 * it.
 */
import { useMemo } from 'react';
import type { HarnessClient } from '../../../api/client';
import type {
  GraphNeighbourhoodView,
  GraphVisibilityName,
  SessionVisibility,
} from '../../../api/dto';
import { useProjectPaths } from '../../../app/projectPaths';
import { useAsync } from '../../../app/useAsync';
import type { Async } from '../../../app/useAsync';
import { neighbourGroups } from './mappers';
import type { NeighbourGroup } from './mappers';

/** How many neighbours one hop may return before the pane stops asking for more. */
const LIMIT = 60;

/**
 * The egress classes a traversal made *for this session* may enter.
 *
 * A `project` session asks for `project` nodes only, so what the inspector shows beside a
 * project-visible object is what could legitimately travel with it. A `private` session
 * asks for everything on this machine, which is what "private" means: it never leaves,
 * and inside it the researcher sees their own working context.
 *
 * An empty result means "no filter", which is what `graph.neighbors` takes for "everything".
 */
export function traversalVisibility(
  visibility: SessionVisibility | null | undefined,
): GraphVisibilityName[] {
  return visibility === 'project' ? ['project'] : [];
}

export interface NeighbourhoodApi extends Omit<Async<GraphNeighbourhoodView>, 'data'> {
  view: GraphNeighbourhoodView | null;
  /** The neighbours, grouped by relation and direction, in the order they came back. */
  groups: NeighbourGroup[];
  /** True when the graph answered and had nothing to say about this node. */
  empty: boolean;
}

export interface NeighbourhoodOptions {
  /** Egress classes the walk may enter; empty means everything on this machine. */
  visibility?: readonly GraphVisibilityName[];
  /** The session ids are read in, so a message neighbour gets a route back. */
  session?: string | null;
  /** False leaves the read unmade, for a tab that is not open. */
  enabled?: boolean;
  limit?: number;
}

/** `graph.neighbors` for one identity: one hop, both directions, grouped. */
export function useNeighbourhood(
  client: HarnessClient,
  id: string | null,
  options: NeighbourhoodOptions = {},
): NeighbourhoodApi {
  const { session = null, enabled = true, limit = LIMIT } = options;
  const visibility = (options.visibility ?? []).join(',');
  // Neighbour chips are real links, so they are built for the tree this pane is mounted in.
  const { href } = useProjectPaths();

  const state = useAsync<GraphNeighbourhoodView | null>(async () => {
    if (!id || !enabled) return null;
    return client.graphNeighbors({
      id,
      hops: 1,
      direction: 'both',
      limit,
      ...(visibility ? { visibility: visibility.split(',') as GraphVisibilityName[] } : {}),
    });
  }, [client, enabled, id, limit, visibility]);

  const groups = useMemo(
    () => (state.data ? neighbourGroups(state.data, { session, href }) : []),
    [href, session, state.data],
  );

  return {
    view: state.data,
    groups,
    empty: state.data !== null && state.data.neighbours.length === 0,
    error: state.error,
    loading: state.loading && id !== null && enabled,
    reload: state.reload,
  };
}
