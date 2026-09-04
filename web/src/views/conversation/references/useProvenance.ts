/**
 * The path from the selected object to the exact source it rests on.
 *
 * `graph.provenance` walks the shortest path from a node to a node of the requested kind —
 * `artifact` by default, which is what "show me where this actually came from" means — and
 * returns every identity on the way plus the anchor metadata the last hop recorded: page,
 * block, character span. That is a `ProvenancePath` and a `SourceAnchor`, drawn from the
 * daemon's own steps rather than assembled by walking neighbours here.
 *
 * `found: false` is a real answer and is rendered as one. A Claim with no accepted evidence
 * behind it has no path to an artifact, and saying "no path" is the honest report; guessing
 * one out of candidate edges would be the projection quietly granting authority.
 *
 * The visibility filter is the same one the neighbourhood uses, for the same reason: a path
 * may not be routed *through* a node the caller may not enter (graph spec §8).
 */
import { useMemo } from 'react';
import type { ProvenancePathModel, SourceAnchorModel } from '@research-harness/design';
import type { HarnessClient } from '../../../api/client';
import type { GraphNodeKind, GraphProvenanceView, GraphVisibilityName } from '../../../api/dto';
import { useProjectPaths } from '../../../app/projectPaths';
import { useAsync } from '../../../app/useAsync';
import { anchorFrom, provenancePathFrom } from './mappers';

export interface ProvenanceApi {
  view: GraphProvenanceView | null;
  /** The path as the Design System draws it, or null when there is none. */
  path: ProvenancePathModel | null;
  /** The exact place the path ended, or null when it ended nowhere anchorable. */
  anchor: SourceAnchorModel | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export interface ProvenanceOptions {
  /** What the path is looking for. The daemon defaults to `artifact`. */
  toKind?: GraphNodeKind;
  visibility?: readonly GraphVisibilityName[];
  session?: string | null;
  enabled?: boolean;
}

/** `graph.provenance` for one identity, as a path and an anchor. */
export function useProvenance(
  client: HarnessClient,
  id: string | null,
  options: ProvenanceOptions = {},
): ProvenanceApi {
  const { toKind = 'artifact', session = null, enabled = true } = options;
  const visibility = (options.visibility ?? []).join(',');
  const { href } = useProjectPaths();

  const state = useAsync<GraphProvenanceView | null>(async () => {
    if (!id || !enabled) return null;
    return client.graphProvenance({
      id,
      to_kind: toKind,
      ...(visibility ? { visibility: visibility.split(',') as GraphVisibilityName[] } : {}),
    });
  }, [client, enabled, id, toKind, visibility]);

  const path = useMemo(
    () => (state.data ? provenancePathFrom(state.data, { session, href }) : null),
    [href, session, state.data],
  );
  const anchor = useMemo(() => (state.data ? anchorFrom(state.data) : null), [state.data]);

  return {
    view: state.data,
    path,
    anchor,
    loading: state.loading && id !== null && enabled,
    error: state.error,
    reload: state.reload,
  };
}
