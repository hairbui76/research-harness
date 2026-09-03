"""The `graph.*` read capabilities: resolve, complete, traverse, filter, trace, and status.

Six reads over the ResearchGraph projection (plan §0.4, graph spec §6). Every one of them
changes nothing — the graph is a disposable index, and rebuilding it is `state.rebuild`'s
job — so they are all `Permission.READ` and a host may call any of them.

Two things every response carries on purpose:

* **`authority` and `visibility` on every node and edge.** A client renders an accepted
  Claim differently from a staged candidate and a private message differently from a
  project-visible one, and it must not have to recompute either from an id prefix. The
  labels come off the projected row, which read them off canonical state.
* **Enough provenance to check the answer.** A neighbour names the edge that reached it
  and how many hops away it is; a provenance path names every identity on it and the
  anchor metadata of its last step.

`graph.resolve` is the one that does not answer from the index: an `rh://` link or an `@`
reference is validated against the canonical object (or, for a session, its durable
record), because a projected row can be behind and must never be the thing that decides
whether a target exists or what authority it carries (graph spec §5, ADR-001).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import CapabilityRequest
from research_harness.capabilities.permissions import Permission
from research_harness.capabilities.registry import CapabilitySpec
from research_harness.domain.graph import (
    DeepLink,
    DeepLinkKind,
    EdgeKind,
    EdgeOrigin,
    GraphAuthority,
    GraphMetadata,
    GraphVisibility,
    NodeKind,
    StableReference,
)
from research_harness.graph.projectors import manuscript_file_identity
from research_harness.graph.queries import (
    DEFAULT_LIMIT,
    Direction,
    EdgeRecord,
    GraphFilter,
    Neighbour,
    NodeRecord,
    ProvenancePath,
)
from research_harness.graph.rebuild import REBUILD_SUFFIX
from research_harness.graph.resolver import ResolvedTarget
from research_harness.graph.service import ResearchGraph
from research_harness.graph.sessions import resolve_session_link

__all__ = [
    "GRAPH_CAPABILITIES",
    "GRAPH_CAPABILITY_HANDLERS",
    "AutocompleteRequest",
    "AutocompleteResult",
    "GraphEdgeView",
    "GraphNodeView",
    "GraphQueryRequest",
    "GraphQueryResult",
    "GraphStatusRequest",
    "GraphStatusView",
    "NeighborsRequest",
    "NeighbourView",
    "NeighbourhoodView",
    "ProvenanceRequest",
    "ProvenanceStepView",
    "ProvenanceView",
    "ResolveRequest",
    "ResolvedView",
    "graph_autocomplete",
    "graph_neighbors",
    "graph_provenance",
    "graph_query",
    "graph_resolve",
    "graph_specs",
    "graph_status",
]

GRAPH_CAPABILITIES: tuple[str, ...] = (
    "graph.resolve",
    "graph.autocomplete",
    "graph.neighbors",
    "graph.query",
    "graph.provenance",
    "graph.status",
)

MAX_AUTOCOMPLETE = 50
"""Composer completion is an interactive list, not a query surface."""


# -- views -------------------------------------------------------------------


class _View(BaseModel):
    """Frozen, closed read model; every transport sees the same JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class GraphNodeView(_View):
    """One projected node, with the labels a client renders it by."""

    id: str
    kind: NodeKind
    authority: GraphAuthority
    visibility: GraphVisibility
    label: str = ""
    text: str = ""
    source: str | None = None
    fingerprint: str | None = None
    metadata: GraphMetadata = Field(default_factory=dict)

    @classmethod
    def of(cls, record: NodeRecord) -> GraphNodeView:
        """Render a projected node row."""
        return cls(
            id=record.identity,
            kind=record.kind,
            authority=record.authority,
            visibility=record.visibility,
            label=record.label,
            text=record.text,
            source=record.source,
            fingerprint=record.fingerprint,
            metadata=dict(record.metadata),
        )


class GraphEdgeView(_View):
    """One projected edge, with the origin and authority that keep a proposal a proposal."""

    from_id: str
    to_id: str
    kind: EdgeKind
    origin: EdgeOrigin
    authority: GraphAuthority
    status: str = ""
    source: str | None = None
    metadata: GraphMetadata = Field(default_factory=dict)

    @property
    def is_candidate(self) -> bool:
        """True when this edge is an unreviewed proposal (ADR-003)."""
        return self.authority is GraphAuthority.CANDIDATE

    @classmethod
    def of(cls, record: EdgeRecord) -> GraphEdgeView:
        """Render a projected edge row."""
        return cls(
            from_id=record.from_id,
            to_id=record.to_id,
            kind=record.kind,
            origin=record.origin,
            authority=record.authority,
            status=record.status,
            source=record.source,
            metadata=dict(record.metadata),
        )


class NeighbourView(_View):
    """A node reached from another, with the edge and direction that reached it."""

    node: GraphNodeView
    edge: GraphEdgeView
    direction: Direction
    hops: int

    @classmethod
    def of(cls, neighbour: Neighbour) -> NeighbourView:
        """Render one traversal result."""
        return cls(
            node=GraphNodeView.of(neighbour.node),
            edge=GraphEdgeView.of(neighbour.edge),
            direction=neighbour.direction,
            hops=neighbour.hops,
        )


class ProvenanceStepView(_View):
    """One hop of a provenance path."""

    edge: GraphEdgeView
    node: GraphNodeView
    direction: Direction


# -- requests and responses --------------------------------------------------


class ResolveRequest(CapabilityRequest):
    """`graph.resolve`: an `@` reference, a bare identity, or an `rh://` deep link."""

    reference: str


class ResolvedView(_View):
    """What a reference resolves to, and every reason it may not be followed.

    `exists`, `authority`, and `fresh` are decided against the canonical or durable record,
    never against the projected row; `node` is the row, offered so a client can show a
    label without a second call.
    """

    reference: str
    project: str
    exists: bool
    authority: GraphAuthority
    visibility: GraphVisibility
    fresh: bool
    link: str | None = None
    node: GraphNodeView | None = None
    problems: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """True when the target exists, its anchor holds, and nothing else objects."""
        return self.exists and self.fresh and not self.problems


class AutocompleteRequest(CapabilityRequest):
    """`graph.autocomplete`: complete a partially typed `@` reference or name."""

    prefix: str
    kinds: tuple[NodeKind, ...] = ()
    visibility: tuple[GraphVisibility, ...] = ()
    """Restrict to an egress class; empty completes over everything on this machine."""

    limit: int = Field(default=10, ge=1, le=MAX_AUTOCOMPLETE)


class AutocompleteResult(_View):
    """Completion candidates, identity matches first."""

    prefix: str
    matches: tuple[GraphNodeView, ...] = ()


class NeighborsRequest(CapabilityRequest):
    """`graph.neighbors`: the one- or two-hop neighbourhood of one node."""

    id: str
    hops: int = Field(default=1, ge=1, le=2)
    direction: Direction = Direction.BOTH
    edge_kinds: tuple[EdgeKind, ...] = ()
    origins: tuple[EdgeOrigin, ...] = ()
    kinds: tuple[NodeKind, ...] = ()
    authority: tuple[GraphAuthority, ...] = ()
    visibility: tuple[GraphVisibility, ...] = ()
    """Egress classes the walk may enter; an excluded node is never traversed through."""

    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=500)


class NeighbourhoodView(_View):
    """One node and what the graph says is around it."""

    origin: GraphNodeView | None = None
    neighbours: tuple[NeighbourView, ...] = ()


class GraphQueryRequest(CapabilityRequest):
    """`graph.query`: the structured filter of `graph.queries.GraphFilter`."""

    kinds: tuple[NodeKind, ...] = ()
    authorities: tuple[GraphAuthority, ...] = ()
    visibility: tuple[GraphVisibility, ...] = ()
    edge_kinds: tuple[EdgeKind, ...] = ()
    origins: tuple[EdgeOrigin, ...] = ()
    linked_to: str | None = None
    direction: Direction = Direction.BOTH
    text: str | None = None
    identities: tuple[str, ...] = ()
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=500)

    def as_filter(self) -> GraphFilter:
        """The query-layer filter this request describes."""
        return GraphFilter(
            kinds=self.kinds,
            authorities=self.authorities,
            visibility=self.visibility,
            edge_kinds=self.edge_kinds,
            origins=self.origins,
            linked_to=self.linked_to,
            direction=self.direction,
            text=self.text,
            limit=self.limit,
            identities=self.identities,
        )


class GraphQueryResult(_View):
    """Nodes matching a structured filter, ordered by identity."""

    nodes: tuple[GraphNodeView, ...] = ()


class ProvenanceRequest(CapabilityRequest):
    """`graph.provenance`: the shortest path from a node to its source of that kind."""

    id: str
    to_kind: NodeKind = NodeKind.ARTIFACT
    visibility: tuple[GraphVisibility, ...] = ()


class ProvenanceView(_View):
    """Claim → Evidence → the exact Artifact anchor, or the reason there is no path."""

    found: bool
    origin: GraphNodeView | None = None
    target: GraphNodeView | None = None
    steps: tuple[ProvenanceStepView, ...] = ()
    identities: tuple[str, ...] = ()
    anchor: GraphMetadata = Field(default_factory=dict)
    """The exact source location the last hop recorded: page, block, char span."""


class GraphStatusRequest(CapabilityRequest):
    """`graph.status`: is the index there, how big is it, and when was it built?"""


class GraphStatusView(_View):
    """What the graph database says about itself."""

    available: bool
    """True when a database exists and was built by the schema version this build reads."""

    exists: bool
    database: Path
    schema_version: int | None = None
    built_at: str | None = None
    canonical_digest: str | None = None
    event_cursor: str | None = None
    nodes: int = 0
    edges: int = 0
    sources: int = 0
    rebuilding: bool = False
    """A rebuild is writing its replacement database beside this one right now."""


# -- handlers ----------------------------------------------------------------


@contextmanager
def _graph(ctx: CapabilityContext) -> Iterator[ResearchGraph]:
    """Open the projection for one call and release the handle afterwards."""
    graph = ResearchGraph(ctx.repo)
    try:
        yield graph
    finally:
        graph.close()


def graph_resolve(ctx: CapabilityContext, request: ResolveRequest) -> ResolvedView:
    """Resolve `@E0482`, `E0482`, or `rh://artifact/A0017-3?page=6&block=B0081`."""
    text = request.reference.strip()
    link = _link_for(text)
    with _graph(ctx) as graph:
        record = graph.resolve(text if link is None else _identity_of(link))
        if link is None:
            return _from_node(text, ctx.repo.config.name, record)
        target = (
            resolve_session_link(ctx.repo, link)
            if link.kind in {DeepLinkKind.SESSION, DeepLinkKind.ATTACHMENT}
            else graph.resolve_deep_link(link)
        )
        return _from_target(text, target, record)


def graph_autocomplete(ctx: CapabilityContext, request: AutocompleteRequest) -> AutocompleteResult:
    """Complete a partially typed reference; identity matches come before text matches."""
    with _graph(ctx) as graph:
        matches = graph.autocomplete(
            request.prefix,
            kinds=request.kinds or None,
            visibility=request.visibility or None,
            limit=request.limit,
        )
    return AutocompleteResult(
        prefix=request.prefix, matches=tuple(GraphNodeView.of(record) for record in matches)
    )


def graph_neighbors(ctx: CapabilityContext, request: NeighborsRequest) -> NeighbourhoodView:
    """One- or two-hop traversal in either direction, filtered as asked.

    A node the filters exclude is marked visited and never expanded, so a two-hop walk
    cannot reach anything *through* a node the caller may not see (graph spec §8).
    """
    with _graph(ctx) as graph:
        origin = graph.resolve(request.id)
        found = graph.neighbors(
            request.id,
            hops=request.hops,
            direction=request.direction,
            edge_kinds=request.edge_kinds or None,
            origins=request.origins or None,
            authority=request.authority or None,
            visibility=request.visibility or None,
            kinds=request.kinds or None,
            limit=request.limit,
        )
    return NeighbourhoodView(
        origin=None if origin is None else GraphNodeView.of(origin),
        neighbours=tuple(NeighbourView.of(item) for item in found),
    )


def graph_query(ctx: CapabilityContext, request: GraphQueryRequest) -> GraphQueryResult:
    """Nodes matching a structured filter: kind, authority, visibility, link, and text."""
    with _graph(ctx) as graph:
        nodes = graph.query(request.as_filter())
    return GraphQueryResult(nodes=tuple(GraphNodeView.of(record) for record in nodes))


def graph_provenance(ctx: CapabilityContext, request: ProvenanceRequest) -> ProvenanceView:
    """The shortest path from a node to a source of ``to_kind``, following edges either way."""
    with _graph(ctx) as graph:
        path = graph.provenance(
            request.id, to_kind=request.to_kind, visibility=request.visibility or None
        )
    return _provenance_view(path)


def graph_status(ctx: CapabilityContext, _request: GraphStatusRequest) -> GraphStatusView:
    """Whether the index is there, how big it is, and whether a rebuild is in flight."""
    with _graph(ctx) as graph:
        status = graph.status()
        database = graph.database
    return GraphStatusView(
        available=status.current,
        exists=status.exists,
        database=database,
        schema_version=status.schema_version,
        built_at=status.built_at,
        canonical_digest=status.canonical_digest,
        event_cursor=status.event_cursor,
        nodes=status.nodes,
        edges=status.edges,
        sources=status.sources,
        rebuilding=_rebuilding(database),
    )


# -- helpers -----------------------------------------------------------------

#: Reference prefixes that address a deep-linkable object. A prefix that is absent (a
#: Synthesis, a message, a block or anchor identity) resolves through the projected node
#: alone; there is no link grammar for it, and inventing one here would be a second
#: vocabulary for hosts to learn.
_LINK_KINDS: Mapping[str, DeepLinkKind] = {
    "W": DeepLinkKind.WORK,
    "V": DeepLinkKind.VERSION,
    "A": DeepLinkKind.ARTIFACT,
    "E": DeepLinkKind.EVIDENCE,
    "C": DeepLinkKind.CLAIM,
    "RQ": DeepLinkKind.QUESTION,
    "D": DeepLinkKind.DECISION,
    "CS": DeepLinkKind.SESSION,
    "SA": DeepLinkKind.ATTACHMENT,
}


def _link_for(text: str) -> DeepLink | None:
    """The deep link a reference addresses, or ``None`` when it addresses no link kind."""
    link = DeepLink.try_parse(text)
    if link is not None:
        return link
    reference = StableReference.try_parse(text)
    if reference is None:
        return None
    kind = _LINK_KINDS.get(reference.prefix)
    return None if kind is None else DeepLink(kind=kind, target=reference.identifier)


def _identity_of(link: DeepLink) -> str:
    """The graph identity a link addresses, so its projected node can be shown beside it."""
    if link.kind is DeepLinkKind.MANUSCRIPT:
        return manuscript_file_identity(link.target)
    return link.target


def _from_target(reference: str, target: ResolvedTarget, record: NodeRecord | None) -> ResolvedView:
    return ResolvedView(
        reference=reference,
        project=target.project,
        exists=target.exists,
        authority=target.authority,
        visibility=target.visibility,
        fresh=target.fresh,
        link=target.link.format(),
        node=None if record is None else GraphNodeView.of(record),
        problems=target.problems,
    )


def _from_node(reference: str, project: str, record: NodeRecord | None) -> ResolvedView:
    """A reference with no link grammar: the projected node is the whole answer."""
    if record is None:
        return ResolvedView(
            reference=reference,
            project=project,
            exists=False,
            authority=GraphAuthority.CANDIDATE,
            visibility=GraphVisibility.PRIVATE,
            fresh=False,
            problems=(
                f"nothing named {reference!r} is projected; the graph may be absent or "
                "rebuilding, in which case read the canonical file directly",
            ),
        )
    return ResolvedView(
        reference=reference,
        project=project,
        exists=True,
        authority=record.authority,
        visibility=record.visibility,
        fresh=record.authority is not GraphAuthority.STALE,
        node=GraphNodeView.of(record),
        problems=() if record.authority is not GraphAuthority.STALE else (f"{reference} is stale",),
    )


def _provenance_view(path: ProvenancePath | None) -> ProvenanceView:
    if path is None:
        return ProvenanceView(found=False)
    return ProvenanceView(
        found=True,
        origin=GraphNodeView.of(path.origin),
        target=GraphNodeView.of(path.target),
        steps=tuple(
            ProvenanceStepView(
                edge=GraphEdgeView.of(step.edge),
                node=GraphNodeView.of(step.node),
                direction=step.direction,
            )
            for step in path.steps
        ),
        identities=path.identities,
        anchor=dict(path.anchor),
    )


def _rebuilding(database: Path) -> bool:
    """True while a full rebuild is writing its replacement beside the live database."""
    parent = database.parent
    if not parent.is_dir():
        return False
    return any(parent.glob(f"{database.name}{REBUILD_SUFFIX}*"))


# -- specs -------------------------------------------------------------------


def _read(
    name: str,
    *,
    summary: str,
    request_model: type[BaseModel],
    response_model: type[BaseModel],
    handler: Any,
) -> CapabilitySpec:
    """One `graph.*` read. All of them change nothing, so the semantics line is shared."""
    return CapabilitySpec(
        name=name,
        summary=summary,
        permission=Permission.READ,
        scientific_semantics=(
            "reads a disposable projection; changes no canonical object and grants no "
            "authority of its own"
        ),
        request_model=request_model,
        response_model=response_model,
        handler=handler,
    )


def graph_specs() -> list[CapabilitySpec]:
    """The six `graph.*` reads of plan §0.4."""
    return [
        _read(
            "graph.resolve",
            summary="Resolve an `@` reference or `rh://` deep link against canonical state.",
            request_model=ResolveRequest,
            response_model=ResolvedView,
            handler=graph_resolve,
        ),
        _read(
            "graph.autocomplete",
            summary="Complete a partially typed reference for the composer.",
            request_model=AutocompleteRequest,
            response_model=AutocompleteResult,
            handler=graph_autocomplete,
        ),
        _read(
            "graph.neighbors",
            summary="One- or two-hop neighbourhood of a node, in either direction.",
            request_model=NeighborsRequest,
            response_model=NeighbourhoodView,
            handler=graph_neighbors,
        ),
        _read(
            "graph.query",
            summary="Nodes matching a structured kind/authority/visibility/link filter.",
            request_model=GraphQueryRequest,
            response_model=GraphQueryResult,
            handler=graph_query,
        ),
        _read(
            "graph.provenance",
            summary="Shortest path from a node to its source, e.g. Claim to Artifact anchor.",
            request_model=ProvenanceRequest,
            response_model=ProvenanceView,
            handler=graph_provenance,
        ),
        _read(
            "graph.status",
            summary="Whether the graph index exists, how big it is, and when it was built.",
            request_model=GraphStatusRequest,
            response_model=GraphStatusView,
            handler=graph_status,
        ),
    ]


#: The handler behind each name, so `capabilities.handlers.CAPABILITY_HANDLERS` resolves a
#: `graph.*` call the same way it resolves every other capability.
GRAPH_CAPABILITY_HANDLERS: dict[str, Any] = {
    "graph.resolve": graph_resolve,
    "graph.autocomplete": graph_autocomplete,
    "graph.neighbors": graph_neighbors,
    "graph.query": graph_query,
    "graph.provenance": graph_provenance,
    "graph.status": graph_status,
}
