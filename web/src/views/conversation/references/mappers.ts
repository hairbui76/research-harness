/**
 * `graph.*` responses → Design System view models.
 *
 * The same rule as `views/conversation/mappers.ts`, and it matters more here: nothing in
 * this file decides anything. Authority, visibility, edge origin, existence and anchor
 * freshness all arrive from the daemon on every row, and they are carried through
 * unchanged. A projection that is a *disposable index* (ADR-006) becomes dangerous the
 * moment a client starts inferring standing from it — a candidate edge drawn as accepted
 * is the "index becomes the knowledge model" failure PRODUCT §43 names, one mapper wide.
 *
 * Two presentational judgements *are* made here, and both are stated where they are made:
 *
 * - which of the Design System's five `ResolutionState` words a `ResolvedView` is shown
 *   as (`resolutionOf`), and
 * - which `EntityKind` a graph node kind is drawn as, for the six structural kinds the
 *   Design System groups under `block` (`entityKindOfNodeKind`).
 *
 * Neither one changes what the daemon said; they choose the word for it.
 */
import type {
  AuthorityLabel,
  EntityKind,
  EntityRefModel,
  ProvenancePathModel,
  ProvenanceStep,
  ResolutionState,
  SourceAnchorModel,
} from '@research-harness/design';
import type {
  GraphEdgeView,
  GraphMetadata,
  GraphNeighbourView,
  GraphNeighbourhoodView,
  GraphNodeKind,
  GraphNodeView,
  GraphProvenanceView,
  GraphResolvedView,
} from '../../../api/dto';
import { SCIENTIFIC_EDGE_KINDS } from '../../../api/dto';
import { entityKindOf, entityRefFor } from '../mappers';
import type { PathHref } from '../mappers';

/* ------------------------------------------------------------------------- */
/* nodes                                                                      */
/* ------------------------------------------------------------------------- */

/**
 * Graph node kind → the kind the Design System draws.
 *
 * The graph projects twenty-one namespaces; `ENTITY_KINDS` names fourteen. The six
 * document-structure kinds and `citation` are all "a piece of a source document", which is
 * exactly what the Design System's `block` means, so they are drawn as blocks rather than
 * mislabelled as something they are not. `project` has no chip at all and returns null —
 * the caller falls back to the id's own prefix.
 */
const ENTITY_KIND_BY_NODE_KIND: Partial<Record<GraphNodeKind, EntityKind>> = {
  session: 'session',
  message: 'message',
  attachment: 'attachment',
  work: 'work',
  version: 'version',
  artifact: 'artifact',
  section: 'block',
  paragraph: 'block',
  table: 'block',
  figure: 'block',
  equation: 'block',
  reference: 'block',
  citation: 'block',
  evidence: 'evidence',
  claim: 'claim',
  question: 'question',
  decision: 'decision',
  synthesis: 'synthesis',
  manuscript_file: 'manuscript_file',
  manuscript_anchor: 'manuscript_anchor',
};

/** The `EntityKind` a projected node is drawn as, or null when the graph names no chip. */
export function entityKindOfNodeKind(kind: GraphNodeKind): EntityKind | null {
  return ENTITY_KIND_BY_NODE_KIND[kind] ?? null;
}

export interface NodeRefOptions {
  /** What the resolver said. Defaults to `resolved`: the row came out of the index. */
  resolution?: ResolutionState;
  /** The session a message or attachment id is read in, so its route can be built. */
  session?: string | null;
  /**
   * Rewrites the chip's `href` for the project tree it is rendered in
   * (`app/projectPaths.tsx`). Absent is the legacy host, where a workspace path is the URL.
   */
  href?: PathHref;
}

/**
 * One projected node as a reference chip.
 *
 * `authority` and `label` are the row's own. `resolution` defaults to `resolved` because a
 * node the graph returned exists in the graph — a caller that has asked `graph.resolve`
 * passes what *that* said instead, which is the only answer that checked canonical state.
 */
export function refFromNode(node: GraphNodeView, options: NodeRefOptions = {}): EntityRefModel {
  const kind = entityKindOfNodeKind(node.kind) ?? entityKindOf(node.id);
  const ref = entityRefFor(node.id, {
    label: node.label || null,
    authority: node.authority,
    ...(options.resolution ? { resolution: options.resolution } : {}),
    session: options.session ?? sessionOf(node.metadata),
    ...(options.href ? { href: options.href } : {}),
  });
  // `entityRefFor` reads the kind off the id's prefix; the graph knows better for the
  // identities that carry no prefix at all (`file:main.tex`, `anchor:…`, a block id).
  return kind === null ? ref : { ...ref, kind };
}

/** The session a message or attachment node records, when its metadata names one. */
function sessionOf(metadata: GraphMetadata): string | null {
  const session = metadata.session;
  return typeof session === 'string' ? session : null;
}

/* ------------------------------------------------------------------------- */
/* resolution                                                                 */
/* ------------------------------------------------------------------------- */

/**
 * Which of the five resolution words a `graph.resolve` answer is shown as.
 *
 * The order is the order a researcher needs to hear it in, and each branch reports
 * something the daemon actually said:
 *
 * 1. **it is not there** — `exists: false`. A deep link named a target this project does
 *    not have, which is `broken` ("points outside this project"); a bare `@` reference
 *    that resolved to nothing is `unresolved`, because the index may simply be rebuilding
 *    and the daemon's own `problems` sentence says so.
 * 2. **it moved** — `fresh: false`, or the row is labelled `stale`. The object resolves and
 *    its anchor no longer holds.
 * 3. **it may not leave** — `visibility: 'private'`. It resolves and is readable here, and
 *    it will not go to an external provider.
 * 4. otherwise `resolved`.
 *
 * A token in any of states 1–3 is still sendable. Conversation spec §7 asks for it to be
 * *visibly marked* before sending, not for the researcher to be prevented from writing
 * about a reference they know is broken.
 */
export function resolutionOf(view: GraphResolvedView): ResolutionState {
  if (!view.exists) return isDeepLink(view.reference) ? 'broken' : 'unresolved';
  if (!view.fresh || view.authority === 'stale') return 'stale';
  if (view.visibility === 'private') return 'private';
  return 'resolved';
}

/** True for a reference written as an `rh://` deep link rather than as an `@` id. */
function isDeepLink(reference: string): boolean {
  return reference.trim().toLowerCase().startsWith('rh://');
}

/**
 * The reference chip for a resolved reference.
 *
 * When the graph could not name a node — an unresolved id, or a link into a project this
 * one is not — the chip is still drawn, from the reference text, so a dangling `@E9999`
 * appears where it was typed instead of vanishing.
 */
export function refFromResolved(
  view: GraphResolvedView,
  fallbackId: string,
  options: NodeRefOptions = {},
): EntityRefModel {
  const resolution = resolutionOf(view);
  if (view.node) return refFromNode(view.node, { ...options, resolution });
  return entityRefFor(fallbackId, {
    resolution,
    authority: view.authority,
    session: options.session ?? null,
    ...(options.href ? { href: options.href } : {}),
  });
}

/* ------------------------------------------------------------------------- */
/* neighbourhoods                                                             */
/* ------------------------------------------------------------------------- */

/** One neighbour, with everything the graph said about the edge that reached it. */
export interface NeighbourModel {
  ref: EntityRefModel;
  /** `supports`, `mentioned_in`, … exactly as the edge is labelled. */
  relation: GraphEdgeView['kind'];
  origin: GraphEdgeView['origin'];
  /** The *edge's* authority, which is not the node's. */
  edgeAuthority: AuthorityLabel;
  direction: GraphNeighbourView['direction'];
  hops: number;
  /**
   * True when this relation is an unreviewed proposal (ADR-003). It is rendered as the
   * word "candidate" beside the row and never as an accepted relation.
   */
  candidate: boolean;
  /** True for a relation that asserts something about the science rather than structure. */
  scientific: boolean;
  status: string;
  source: string | null;
}

/** One group of neighbours: the relation, the way it was followed, and its rows. */
export interface NeighbourGroup {
  key: string;
  relation: GraphEdgeView['kind'];
  direction: GraphNeighbourView['direction'];
  neighbours: NeighbourModel[];
}

/** How the group heading reads: `supports` in, out, or both. */
export const RELATION_HEADINGS: Record<GraphEdgeView['kind'], { in: string; out: string }> = {
  contains: { in: 'Contained by', out: 'Contains' },
  version_of: { in: 'Versions', out: 'Version of' },
  artifact_of: { in: 'Artifacts', out: 'Artifact of' },
  cites: { in: 'Cited by', out: 'Cites' },
  attached_to: { in: 'Attachments', out: 'Attached to' },
  anchored_at: { in: 'Anchored here', out: 'Anchored at' },
  mentioned_in: { in: 'Mentioned in messages', out: 'Mentions' },
  supports: { in: 'Supported by', out: 'Supports' },
  contradicts: { in: 'Contradicted by', out: 'Contradicts' },
  qualifies: { in: 'Qualified by', out: 'Qualifies' },
  derived_from: { in: 'Derived into', out: 'Derived from' },
  depends_on: { in: 'Depended on by', out: 'Depends on' },
};

/** The heading for one group, in the researcher's words. */
export function headingFor(group: NeighbourGroup): string {
  const heading = RELATION_HEADINGS[group.relation];
  return group.direction === 'in' ? heading.in : heading.out;
}

/** One neighbour row, carrying the edge's own labels beside the node's. */
export function neighbourModel(
  neighbour: GraphNeighbourView,
  options: NodeRefOptions = {},
): NeighbourModel {
  const edge = neighbour.edge;
  return {
    ref: refFromNode(neighbour.node, options),
    relation: edge.kind,
    origin: edge.origin,
    edgeAuthority: edge.authority,
    direction: neighbour.direction,
    hops: neighbour.hops,
    candidate: edge.authority === 'candidate',
    scientific: SCIENTIFIC_EDGE_KINDS.includes(edge.kind),
    status: edge.status,
    source: edge.source ?? null,
  };
}

/**
 * The neighbourhood, grouped by relation and direction, in the order the graph returned it.
 *
 * Nothing is added, removed, deduplicated or re-ranked: a neighbour the daemon pruned for
 * privacy is simply not in the response, and a client that "helpfully" filled a gap back in
 * would be routing around exactly the restriction graph spec §8 exists to enforce.
 */
export function neighbourGroups(
  view: GraphNeighbourhoodView,
  options: NodeRefOptions = {},
): NeighbourGroup[] {
  const groups: NeighbourGroup[] = [];
  const byKey = new Map<string, NeighbourGroup>();
  for (const neighbour of view.neighbours) {
    const key = `${neighbour.edge.kind}:${neighbour.direction}`;
    let group = byKey.get(key);
    if (!group) {
      group = {
        key,
        relation: neighbour.edge.kind,
        direction: neighbour.direction,
        neighbours: [],
      };
      byKey.set(key, group);
      groups.push(group);
    }
    group.neighbours.push(neighbourModel(neighbour, options));
  }
  return groups;
}

/* ------------------------------------------------------------------------- */
/* provenance                                                                 */
/* ------------------------------------------------------------------------- */

/**
 * `graph.provenance` → the `ProvenancePath` view model.
 *
 * The origin is the first step and carries no relation, because nothing led to it; every
 * later step is labelled with the edge kind that reached it, so a chain reads
 * "C0001 → supports → E0482 → anchored_at → B0081 → contains → A0017-3" rather than
 * asking the reader to infer the relation from an arrow.
 */
export function provenancePathFrom(
  view: GraphProvenanceView,
  options: NodeRefOptions = {},
): ProvenancePathModel | null {
  if (!view.found || !view.origin) return null;
  const steps: ProvenanceStep[] = [{ ref: refFromNode(view.origin, options) }];
  for (const step of view.steps) {
    steps.push({ ref: refFromNode(step.node, options), relation: step.edge.kind });
  }
  return { steps };
}

/**
 * The exact source location the path ended at.
 *
 * `anchor` is the last hop's edge metadata — page, block, character span — and the target
 * is the artifact it points into. `stale` is the target row's own authority, never a
 * comparison made here.
 */
export function anchorFrom(view: GraphProvenanceView): SourceAnchorModel | null {
  if (!view.found || !view.target) return null;
  const anchor = view.anchor;
  const page = numberOf(anchor.page);
  const block = stringOf(anchor.block);
  const start = numberOf(anchor.char_start);
  const end = numberOf(anchor.char_end);
  return {
    artifactId: view.target.id,
    ...(page === null ? {} : { page }),
    ...(block === null ? {} : { block }),
    ...(start === null || end === null ? {} : { span: { start, end } }),
    ...(view.target.text ? { quote: view.target.text } : {}),
    ...(view.target.authority === 'stale' ? { stale: true } : {}),
  };
}

function numberOf(value: GraphMetadata[string] | undefined): number | null {
  return typeof value === 'number' ? value : null;
}

function stringOf(value: GraphMetadata[string] | undefined): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}
