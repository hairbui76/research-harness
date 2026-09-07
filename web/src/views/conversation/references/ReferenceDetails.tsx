/**
 * What the graph says about the object the inspector is following.
 *
 * Three answers, in the order a researcher asks them:
 *
 * 1. **Does this reference still hold?** `graph.resolve` against canonical state, with the
 *    daemon's own sentence when it does not.
 * 2. **Where did it come from?** `graph.provenance` — Claim → Evidence → the exact Artifact
 *    anchor — drawn as a `ProvenancePath` whose last step opens the page and block.
 * 3. **What is around it?** `graph.neighbors`, one hop, both directions, grouped by
 *    relation, with the *edge's* authority beside every row.
 *
 * That third point is the one worth being careful about. A `supports` edge a model proposed
 * is a **candidate** until a review says otherwise (ADR-003, graph spec §3), and the edge
 * carries its own authority which is not the node's: accepted Evidence can be joined to a
 * Claim by an unreviewed proposal. Every row therefore shows the relation's authority in
 * words, and a candidate relation says "candidate" and is never drawn as an accepted one.
 *
 * And nothing is filtered here. The neighbourhood is asked for under the session's egress
 * class and rendered exactly as it comes back — a private prior-session message absent from
 * a project-visible object's neighbourhood is absent because the daemon pruned the walk,
 * not because this component decided it should be (graph spec §8).
 */
import { useMemo } from 'react';
import {
  AsyncState,
  AuthorityBadge,
  Badge,
  EntityRef,
  ErrorNotice,
  ProvenancePath,
  SourceAnchor,
} from '@research-harness/design';
import type { EntityRefModel, SourceAnchorModel } from '@research-harness/design';
import type { HarnessClient } from '../../../api/client';
import type { SessionVisibility } from '../../../api/dto';
import { headingFor } from './mappers';
import type { NeighbourGroup, NeighbourModel } from './mappers';
import { traversalVisibility, useNeighbourhood } from './useNeighbourhood';
import { useProvenance } from './useProvenance';
import { useResolveReferences } from './useResolveReferences';

export interface ReferenceDetailsProps {
  client: HarnessClient;
  /** The object being followed. Named `entity` because `ref` is React's. */
  entity: EntityRefModel;
  /** The session the inspector is reading in; decides the traversal's egress class. */
  session: string | null;
  visibility: SessionVisibility | null;
  /** Open a neighbour or a provenance step in the inspector. */
  onOpen: (entity: EntityRefModel) => void;
  /** Open the exact page and block a provenance path ended at. */
  onOpenAnchor?: (anchor: SourceAnchorModel) => void;
  /** False while this tab is not the one on screen: nothing is read. */
  enabled?: boolean;
}

export function ReferenceDetails({
  client,
  entity,
  session,
  visibility,
  onOpen,
  onOpenAnchor,
  enabled = true,
}: ReferenceDetailsProps) {
  const tokens = useMemo(() => [entity], [entity]);
  const resolved = useResolveReferences(client, tokens, { session, enabled });
  const answer = resolved.of(entity.id);

  const egress = useMemo(() => traversalVisibility(visibility), [visibility]);
  const neighbourhood = useNeighbourhood(client, entity.id, {
    visibility: egress,
    session,
    enabled,
  });
  const provenance = useProvenance(client, entity.id, {
    visibility: egress,
    session,
    enabled,
  });

  return (
    <div className="rh-web-stack rh-web-stack--tight rh-web-graph">
      <Resolution entity={resolved.tokens[0] ?? entity} problems={answer?.problems ?? []} />

      <section className="rh-web-stack rh-web-stack--tight">
        <h3 className="rh-text-h4">Provenance</h3>
        {provenance.loading ? (
          <AsyncState kind="loading" compact title="Tracing this back to its source" />
        ) : provenance.error ? (
          <Failed error={provenance.error} retry={provenance.reload} />
        ) : provenance.path === null ? (
          <AsyncState
            kind="empty"
            compact
            hideKind
            title="No path to a source artifact"
            description="Nothing accepted joins this object to an artifact the project holds."
          />
        ) : (
          <>
            <ProvenancePath
              path={provenance.path}
              orientation="vertical"
              onOpen={onOpen}
              label={`Provenance of ${entity.id}`}
            />
            {provenance.anchor ? (
              <SourceAnchor
                variant="block"
                anchor={provenance.anchor}
                {...(onOpenAnchor ? { onOpen: onOpenAnchor } : {})}
              />
            ) : null}
          </>
        )}
      </section>

      <section className="rh-web-stack rh-web-stack--tight">
        <h3 className="rh-text-h4">In the graph</h3>
        {neighbourhood.loading ? (
          <AsyncState kind="loading" compact title="Reading the neighbourhood" />
        ) : neighbourhood.error ? (
          <Failed error={neighbourhood.error} retry={neighbourhood.reload} />
        ) : neighbourhood.empty ? (
          <AsyncState
            kind="empty"
            compact
            hideKind
            title="Nothing is linked to this yet"
            description="The graph holds no relation into or out of this object."
          />
        ) : (
          neighbourhood.groups.map((group) => (
            <Group key={group.key} group={group} onOpen={onOpen} />
          ))
        )}
      </section>
    </div>
  );
}

/** What the resolver said, and — when it objected — exactly what it said. */
function Resolution({
  entity,
  problems,
}: {
  entity: EntityRefModel;
  problems: readonly string[];
}) {
  return (
    <section className="rh-web-stack rh-web-stack--tight">
      <div className="rh-web-row">
        <EntityRef entity={entity} size="sm" describe={false} />
      </div>
      {problems.length === 0 ? null : (
        <ul className="rh-web-list rh-web-list--tight rh-web-graph__problems">
          {problems.map((problem) => (
            <li key={problem} className="rh-text-secondary">
              {problem}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** One relation, in one direction, with its rows. */
function Group({
  group,
  onOpen,
}: {
  group: NeighbourGroup;
  onOpen: (entity: EntityRefModel) => void;
}) {
  return (
    <section className="rh-web-stack rh-web-stack--tight">
      <h4 className="rh-text-body-sm rh-web-graph__relation">
        {headingFor(group)}
        <code>{group.relation}</code>
      </h4>
      <ul className="rh-web-list rh-web-list--tight">
        {group.neighbours.map((neighbour) => (
          <li key={`${neighbour.ref.id}:${neighbour.direction}`} className="rh-web-row">
            <EntityRef entity={neighbour.ref} size="sm" onOpen={onOpen} describe={false} />
            <RelationLabel neighbour={neighbour} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The authority of the *relation*, in words.
 *
 * A scientific relation always says what standing it has, because "E0555 contradicts C0001"
 * is a different statement depending on whether a researcher accepted it or a model
 * proposed it. The row therefore carries two badges, and they are about different things:
 * the chip's is the *object's* authority — accepted Evidence stays accepted — and this one
 * is the *relation's*. "this relation is" in front of it is what keeps them apart, so
 * "E0555 · Accepted · this relation is Candidate" cannot be read as one claim about one
 * thing. A model's proposal says so as well, and never appears as an accepted relation.
 */
function RelationLabel({ neighbour }: { neighbour: NeighbourModel }) {
  if (!neighbour.scientific && !neighbour.candidate) return null;
  return (
    <span className="rh-web-row rh-web-graph__authority">
      <span className="rh-text-secondary">this relation is</span>
      <AuthorityBadge authority={neighbour.edgeAuthority} size="sm" />
      {neighbour.origin === 'model_proposed' ? (
        <Badge tone="neutral" size="sm" icon="sparkles">
          proposed by a model, not reviewed
        </Badge>
      ) : null}
    </span>
  );
}

function Failed({ error, retry }: { error: string; retry: () => void }) {
  return (
    <ErrorNotice
      kind="retryable"
      title="The graph could not answer"
      description={error}
      safety={{ draft: 'safe', source: 'safe' }}
      actions={[{ label: 'Try again', onClick: retry, iconStart: 'refresh-cw' }]}
    />
  );
}
