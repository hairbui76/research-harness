"""The query modes of graph spec §6, over the node/edge/adjacency tables.

Everything here reads. Nothing resolves *authority* — that is the resolver's job against
canonical files — and nothing here treats a projected row as scientific truth: a query
answers "what does the index say is nearby", and the caller decides what to do with it.

Every result is deterministic. Ties break on stable identity rather than on SQLite's row
order, so two runs against the same database return the same list and a test can assert on
it.

`GraphFilter` already carries `visibility`, and every traversal takes the same filter, so
the privacy-filtered traversal of graph spec §8 is a value passed in rather than a second
code path: once session nodes are projected `private`, a caller that asks for
``visibility=(PROJECT,)`` cannot reach them, one hop or two.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import Select, and_, select, text
from sqlalchemy.engine import Engine

from research_harness.domain.graph import (
    EdgeKind,
    EdgeOrigin,
    GraphAuthority,
    GraphMetadata,
    GraphVisibility,
    NodeKind,
    StableReference,
)
from research_harness.graph.schema import EDGES, NODES, NODES_FTS

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_HOPS",
    "Direction",
    "EdgeRecord",
    "GraphFilter",
    "Neighbour",
    "NodeRecord",
    "ProvenancePath",
    "ProvenanceStep",
    "SearchHit",
    "autocomplete",
    "citations",
    "dependents",
    "edges_of",
    "neighbors",
    "node",
    "nodes",
    "provenance",
    "query",
    "resolve",
    "search",
]

DEFAULT_LIMIT = 50
MAX_HOPS = 2
"""One and two hops are the budgeted traversals (graph spec §6, §9)."""

_LIKE_ESCAPE = "\\"
_SNIPPET_TOKENS = 12
_FTS_SCAN = re.compile(r'"(?P<phrase>[^"]*)"|(?P<word>[^\s"]+)')
_FTS_OPERATORS = frozenset({"AND", "OR", "NOT"})


class Direction(StrEnum):
    """Which way a traversal follows an edge."""

    OUT = "out"
    IN = "in"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class NodeRecord:
    """One projected node, as the index holds it."""

    identity: str
    kind: NodeKind
    authority: GraphAuthority
    visibility: GraphVisibility
    label: str
    text: str
    source: str | None
    fingerprint: str | None
    metadata: GraphMetadata


@dataclass(frozen=True, slots=True)
class EdgeRecord:
    """One projected edge, as the index holds it."""

    from_id: str
    to_id: str
    kind: EdgeKind
    origin: EdgeOrigin
    authority: GraphAuthority
    status: str
    source: str | None
    metadata: GraphMetadata

    @property
    def is_candidate(self) -> bool:
        """True when this edge is an unreviewed proposal (ADR-003)."""
        return self.authority is GraphAuthority.CANDIDATE


@dataclass(frozen=True, slots=True)
class Neighbour:
    """A node reached from a starting node, with the edge and direction that reached it."""

    node: NodeRecord
    edge: EdgeRecord
    direction: Direction
    hops: int


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One lexical match inside the graph, optionally constrained to a neighbourhood."""

    node: NodeRecord
    snippet: str
    rank: float
    """SQLite ``bm25()``: lower is a better match; results come back ascending."""


@dataclass(frozen=True, slots=True)
class ProvenanceStep:
    """One hop of a provenance path."""

    edge: EdgeRecord
    node: NodeRecord
    direction: Direction


@dataclass(frozen=True, slots=True)
class ProvenancePath:
    """A shortest path from a starting node to a node of the requested kind."""

    origin: NodeRecord
    steps: tuple[ProvenanceStep, ...]

    @property
    def target(self) -> NodeRecord:
        """The node the path ends at (the origin when the path is empty)."""
        return self.steps[-1].node if self.steps else self.origin

    @property
    def identities(self) -> tuple[str, ...]:
        """Every identity on the path, starting with the origin."""
        return (self.origin.identity, *(step.node.identity for step in self.steps))

    @property
    def anchor(self) -> GraphMetadata:
        """The exact source location the last hop recorded: page, block, char span."""
        return dict(self.steps[-1].edge.metadata) if self.steps else {}


@dataclass(frozen=True, slots=True)
class GraphFilter:
    """Structured filters shared by :func:`query`, :func:`neighbors`, and :func:`search`."""

    kinds: tuple[NodeKind, ...] = ()
    authorities: tuple[GraphAuthority, ...] = ()
    visibility: tuple[GraphVisibility, ...] = ()
    edge_kinds: tuple[EdgeKind, ...] = ()
    origins: tuple[EdgeOrigin, ...] = ()
    linked_to: str | None = None
    """Restrict to nodes joined to this identity by an edge the other filters allow."""

    direction: Direction = Direction.BOTH
    text: str | None = None
    """Lexical constraint, applied through the FTS index over label and text."""

    limit: int = DEFAULT_LIMIT
    identities: tuple[str, ...] = ()
    """Restrict to these identities; the form a neighbourhood-constrained search uses."""

    def allows_node(self, record: NodeRecord) -> bool:
        """True when ``record`` passes the node-side filters."""
        if self.kinds and record.kind not in self.kinds:
            return False
        if self.authorities and record.authority not in self.authorities:
            return False
        if self.visibility and record.visibility not in self.visibility:
            return False
        return not (self.identities and record.identity not in self.identities)

    def allows_edge(self, record: EdgeRecord) -> bool:
        """True when ``record`` passes the edge-side filters."""
        if self.edge_kinds and record.kind not in self.edge_kinds:
            return False
        return not (self.origins and record.origin not in self.origins)


# --- row decoding -----------------------------------------------------------


def _metadata(value: object) -> GraphMetadata:
    if value in (None, ""):
        return {}
    try:
        decoded = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def _node(row: Any) -> NodeRecord:
    return NodeRecord(
        identity=str(row["identity"]),
        kind=NodeKind(str(row["kind"])),
        authority=GraphAuthority(str(row["authority"])),
        visibility=GraphVisibility(str(row["visibility"])),
        label=str(row["label"]),
        text=str(row["text"]),
        source=None if row["source"] is None else str(row["source"]),
        fingerprint=None if row["fingerprint"] is None else str(row["fingerprint"]),
        metadata=_metadata(row["meta"]),
    )


def _edge(row: Any) -> EdgeRecord:
    return EdgeRecord(
        from_id=str(row["from_id"]),
        to_id=str(row["to_id"]),
        kind=EdgeKind(str(row["kind"])),
        origin=EdgeOrigin(str(row["origin"])),
        authority=GraphAuthority(str(row["authority"])),
        status=str(row["status"]),
        source=None if row["source"] is None else str(row["source"]),
        metadata=_metadata(row["meta"]),
    )


# --- exact lookup -----------------------------------------------------------


def node(engine: Engine, identity: str) -> NodeRecord | None:
    """The node with this exact identity, or ``None``."""
    with engine.connect() as connection:
        row = (
            connection.execute(select(NODES).where(NODES.c.identity == str(identity)))
            .mappings()
            .first()
        )
    return None if row is None else _node(row)


def nodes(engine: Engine, identities: Collection[str]) -> dict[str, NodeRecord]:
    """Every named node that exists, keyed by identity."""
    wanted = sorted({str(value) for value in identities})
    if not wanted:
        return {}
    with engine.connect() as connection:
        rows = connection.execute(select(NODES).where(NODES.c.identity.in_(wanted))).mappings()
        return {str(row["identity"]): _node(row) for row in rows}


def resolve(engine: Engine, reference: str) -> NodeRecord | None:
    """Resolve ``@E0482``, ``E0482``, or any node identity to its projected node.

    A reference resolves through stable identity, never through a row id, so deleting and
    rebuilding `.research/` returns the same node (graph spec §5, §11.1).
    """
    text_value = str(reference).strip()
    parsed = StableReference.try_parse(text_value)
    return node(engine, parsed.identifier if parsed is not None else text_value)


def _like_escaped(value: str) -> str:
    escaped = value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
    for wildcard in ("%", "_"):
        escaped = escaped.replace(wildcard, f"{_LIKE_ESCAPE}{wildcard}")
    return escaped


def autocomplete(
    engine: Engine,
    prefix: str,
    *,
    kinds: Sequence[NodeKind] | None = None,
    limit: int = 10,
) -> list[NodeRecord]:
    """Nodes whose identity starts with ``prefix``, then nodes whose text matches it.

    The composer types `@E04`; identity matches come first because that is what the sigil
    means, and label matches fill the rest of the list so `@CICIDS` finds the work too.
    """
    needle = str(prefix).strip().lstrip("@")
    if not needle or limit <= 0:
        return []
    statement = select(NODES).where(
        NODES.c.identity.like(f"{_like_escaped(needle)}%", escape=_LIKE_ESCAPE)
    )
    if kinds:
        statement = statement.where(NODES.c.kind.in_([kind.value for kind in kinds]))
    with engine.connect() as connection:
        rows = connection.execute(statement.order_by(NODES.c.identity).limit(limit)).mappings()
        found = [_node(row) for row in rows]
        if len(found) >= limit:
            return found
        seen = {record.identity for record in found}
        for hit in _fts_hits(connection, needle, kinds=kinds, limit=limit, prefix=True):
            if hit.node.identity in seen:
                continue
            seen.add(hit.node.identity)
            found.append(hit.node)
            if len(found) >= limit:
                break
    return found


# --- structured query -------------------------------------------------------


def _node_conditions(filters: GraphFilter) -> list[Any]:
    conditions: list[Any] = []
    if filters.kinds:
        conditions.append(NODES.c.kind.in_([kind.value for kind in filters.kinds]))
    if filters.authorities:
        conditions.append(NODES.c.authority.in_([value.value for value in filters.authorities]))
    if filters.visibility:
        conditions.append(NODES.c.visibility.in_([value.value for value in filters.visibility]))
    if filters.identities:
        conditions.append(NODES.c.identity.in_(sorted(set(filters.identities))))
    return conditions


def query(engine: Engine, filters: GraphFilter) -> list[NodeRecord]:
    """Nodes matching a structured filter, ordered by identity.

    ``linked_to`` turns the filter into a one-hop join — "accepted Evidence that supports
    C0041" is one call — and ``text`` narrows it lexically through the FTS index.
    """
    if filters.limit <= 0:
        return []
    if filters.text:
        return [
            hit.node
            for hit in search(
                engine,
                filters.text,
                kinds=filters.kinds or None,
                neighbourhood=filters.linked_to,
                limit=filters.limit,
                filters=filters,
            )
        ]
    statement: Select[Any] = select(NODES)
    for condition in _node_conditions(filters):
        statement = statement.where(condition)
    if filters.linked_to is not None:
        statement = statement.where(NODES.c.identity.in_(_linked_identities(engine, filters)))
    with engine.connect() as connection:
        rows = connection.execute(
            statement.order_by(NODES.c.identity).limit(filters.limit)
        ).mappings()
        return [_node(row) for row in rows]


def _linked_identities(engine: Engine, filters: GraphFilter) -> list[str]:
    identity = str(filters.linked_to)
    found: set[str] = set()
    for neighbour in neighbors(
        engine,
        identity,
        hops=1,
        direction=filters.direction,
        edge_kinds=filters.edge_kinds or None,
        origins=filters.origins or None,
        limit=0,
    ):
        found.add(neighbour.node.identity)
    return sorted(found)


# --- traversal --------------------------------------------------------------


def edges_of(
    engine: Engine,
    identities: Collection[str],
    *,
    direction: Direction = Direction.BOTH,
    edge_kinds: Sequence[EdgeKind] | None = None,
    origins: Sequence[EdgeOrigin] | None = None,
) -> list[tuple[EdgeRecord, Direction]]:
    """Every edge touching ``identities``, each paired with the direction it was found in.

    One statement per direction, both served by an adjacency index, so a hop costs a
    lookup rather than a scan.
    """
    wanted = sorted({str(value) for value in identities})
    if not wanted:
        return []
    clauses: list[tuple[Any, Direction]] = []
    if direction in (Direction.OUT, Direction.BOTH):
        clauses.append((EDGES.c.from_id.in_(wanted), Direction.OUT))
    if direction in (Direction.IN, Direction.BOTH):
        clauses.append((EDGES.c.to_id.in_(wanted), Direction.IN))
    restrictions: list[Any] = []
    if edge_kinds:
        restrictions.append(EDGES.c.kind.in_([kind.value for kind in edge_kinds]))
    if origins:
        restrictions.append(EDGES.c.origin.in_([origin.value for origin in origins]))
    found: list[tuple[EdgeRecord, Direction]] = []
    with engine.connect() as connection:
        for clause, way in clauses:
            statement = (
                select(EDGES)
                .where(and_(clause, *restrictions))
                .order_by(EDGES.c.from_id, EDGES.c.to_id, EDGES.c.kind, EDGES.c.origin)
            )
            found.extend((_edge(row), way) for row in connection.execute(statement).mappings())
    return found


def neighbors(
    engine: Engine,
    identity: str,
    *,
    hops: int = 1,
    direction: Direction = Direction.BOTH,
    edge_kinds: Sequence[EdgeKind] | None = None,
    origins: Sequence[EdgeOrigin] | None = None,
    authority: Sequence[GraphAuthority] | None = None,
    visibility: Sequence[GraphVisibility] | None = None,
    kinds: Sequence[NodeKind] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[Neighbour]:
    """One- or two-hop neighbourhood of ``identity``, in either direction.

    One result per *edge*, not per node: the same Evidence can reach a Claim through an
    accepted `contradicts` relation and a staged, model-proposed `supports` proposal, and
    collapsing those two into one neighbour would hide exactly the distinction ADR-003
    exists to keep visible. Each node is still expanded once, at the fewest hops that
    reached it.

    A node the filters exclude is not traversed *through*: it is marked visited and never
    expanded, so a two-hop walk cannot reach a node by passing through one the caller was
    not allowed to see (graph spec §8). ``limit=0`` means no cap.
    """
    if hops < 1:
        return []
    depth = min(int(hops), MAX_HOPS)
    start = str(identity)
    filters = GraphFilter(
        kinds=tuple(kinds or ()),
        authorities=tuple(authority or ()),
        visibility=tuple(visibility or ()),
        edge_kinds=tuple(edge_kinds or ()),
        origins=tuple(origins or ()),
    )
    seen: set[str] = {start}
    frontier: list[str] = [start]
    found: list[Neighbour] = []
    for hop in range(1, depth + 1):
        if not frontier:
            break
        touching = edges_of(
            engine,
            frontier,
            direction=direction,
            edge_kinds=filters.edge_kinds or None,
            origins=filters.origins or None,
        )
        reached = [
            (edge.to_id if way is Direction.OUT else edge.from_id, edge, way)
            for edge, way in sorted(touching, key=_edge_order)
        ]
        records = nodes(engine, [target for target, _edge, _way in reached if target not in seen])
        frontier = []
        for target, edge, way in reached:
            record = records.get(target)
            if record is None:
                continue
            if target not in seen:
                seen.add(target)
                if filters.allows_node(record):
                    frontier.append(target)
            if filters.allows_node(record):
                found.append(Neighbour(node=record, edge=edge, direction=way, hops=hop))
    found.sort(key=_neighbour_order)
    return found if limit <= 0 else found[:limit]


def _neighbour_order(item: Neighbour) -> tuple[int, str, str, str, str]:
    return (
        item.hops,
        item.direction.value,
        item.edge.kind.value,
        item.node.identity,
        item.edge.origin.value,
    )


def _edge_order(item: tuple[EdgeRecord, Direction]) -> tuple[str, str, str, str]:
    edge, way = item
    return (way.value, edge.kind.value, edge.to_id, edge.from_id)


def dependents(engine: Engine, identity: str, *, limit: int = DEFAULT_LIMIT) -> list[NodeRecord]:
    """Nodes that declare a `depends_on` edge onto ``identity`` — what a change reaches.

    The authority for staleness is still `projection.dependencies`; this is the navigable
    view of the same canonical fields, restricted to namespaces the graph projects.
    """
    return _distinct(
        neighbors(
            engine,
            identity,
            hops=1,
            direction=Direction.IN,
            edge_kinds=(EdgeKind.DEPENDS_ON,),
            limit=limit,
        )
    )


def citations(engine: Engine, identity: str, *, limit: int = DEFAULT_LIMIT) -> list[NodeRecord]:
    """What ``identity`` cites. For what cites it, traverse `cites` inbound instead."""
    return _distinct(
        neighbors(
            engine,
            identity,
            hops=1,
            direction=Direction.OUT,
            edge_kinds=(EdgeKind.CITES,),
            limit=limit,
        )
    )


def _distinct(found: Sequence[Neighbour]) -> list[NodeRecord]:
    """The neighbours' nodes, each once, in the order they were reached."""
    seen: dict[str, NodeRecord] = {}
    for neighbour in found:
        seen.setdefault(neighbour.node.identity, neighbour.node)
    return list(seen.values())


# --- provenance -------------------------------------------------------------


def provenance(
    engine: Engine,
    from_id: str,
    *,
    to_kind: NodeKind = NodeKind.ARTIFACT,
    max_hops: int = 4,
    visibility: Sequence[GraphVisibility] | None = None,
) -> ProvenancePath | None:
    """Shortest path from ``from_id`` to a node of ``to_kind``, following edges either way.

    Claim → Evidence → Artifact anchor is the path this exists for: the supports edge runs
    evidence-to-claim and the anchor edge evidence-to-artifact, so the walk has to be able
    to go against an edge as well as along it. The last step's edge metadata carries the
    exact page and block the evidence was accepted from (graph spec §11.2).
    """
    origin = node(engine, from_id)
    if origin is None:
        return None
    if origin.kind is to_kind:
        return ProvenancePath(origin=origin, steps=())
    allowed = tuple(visibility or ())
    seen: set[str] = {origin.identity}
    queue: deque[tuple[str, tuple[ProvenanceStep, ...]]] = deque([(origin.identity, ())])
    for _ in range(max(1, int(max_hops))):
        if not queue:
            break
        for _index in range(len(queue)):
            current, path = queue.popleft()
            touching = sorted(
                edges_of(engine, [current], direction=Direction.BOTH),
                key=_edge_order,
            )
            reached: dict[str, tuple[EdgeRecord, Direction]] = {}
            for edge, way in touching:
                target = edge.to_id if way is Direction.OUT else edge.from_id
                if target not in seen:
                    reached.setdefault(target, (edge, way))
            records = nodes(engine, list(reached))
            for target in sorted(records):
                edge, way = reached[target]
                record = records[target]
                seen.add(target)
                if allowed and record.visibility not in allowed:
                    continue
                step = ProvenanceStep(edge=edge, node=record, direction=way)
                extended = (*path, step)
                if record.kind is to_kind:
                    return ProvenancePath(origin=origin, steps=extended)
                queue.append((target, extended))
    return None


# --- lexical search ---------------------------------------------------------


def _fts_expression(terms: str, *, prefix: bool = False) -> str:
    """Reduce user text to a MATCH expression that cannot be an FTS5 syntax error."""
    parts: list[str] = []
    for match in _FTS_SCAN.finditer(str(terms)):
        phrase = match.group("phrase")
        raw = phrase if phrase is not None else match.group("word")
        quoted = phrase is not None
        wants_prefix = prefix or (not quoted and raw.endswith("*"))
        token = raw.rstrip("*")
        if not quoted and token.upper() in _FTS_OPERATORS:
            parts.append(token.upper())
            continue
        cleaned = " ".join(
            "".join(character if character.isalnum() else " " for character in token).split()
        )
        if not cleaned:
            continue
        parts.append(f'"{cleaned}"*' if wants_prefix else f'"{cleaned}"')
    kept: list[str] = []
    for part in parts:
        if part in _FTS_OPERATORS and (not kept or kept[-1] in _FTS_OPERATORS):
            continue
        kept.append(part)
    while kept and kept[-1] in _FTS_OPERATORS:
        kept.pop()
    return " ".join(kept)


def _fts_hits(
    connection: Any,
    terms: str,
    *,
    kinds: Sequence[NodeKind] | None,
    limit: int,
    prefix: bool = False,
    identities: Collection[str] | None = None,
) -> list[SearchHit]:
    expression = _fts_expression(terms, prefix=prefix)
    if not expression or limit <= 0:
        return []
    clauses = [f'"{NODES_FTS}" MATCH :match']
    parameters: dict[str, Any] = {"match": expression, "limit": limit}
    if kinds:
        names = {f"kind{index}": kind.value for index, kind in enumerate(kinds)}
        clauses.append(f"n.kind IN ({', '.join(f':{key}' for key in names)})")
        parameters.update(names)
    if identities is not None:
        wanted = sorted({str(value) for value in identities})
        if not wanted:
            return []
        names = {f"id{index}": value for index, value in enumerate(wanted)}
        clauses.append(f"n.identity IN ({', '.join(f':{key}' for key in names)})")
        parameters.update(names)
    statement = (
        "SELECT n.*, "
        f"snippet(\"{NODES_FTS}\", -1, '[', ']', '…', {_SNIPPET_TOKENS}) AS snippet, "
        f'bm25("{NODES_FTS}") AS score '
        f'FROM "{NODES_FTS}" JOIN "{NODES.name}" AS n ON n.rowid = "{NODES_FTS}".rowid '
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY score, n.identity LIMIT :limit"
    )
    rows = connection.execute(text(statement), parameters).mappings()
    return [
        SearchHit(node=_node(row), snippet=str(row["snippet"]), rank=float(str(row["score"])))
        for row in rows
    ]


def search(
    engine: Engine,
    terms: str,
    *,
    kinds: Sequence[NodeKind] | None = None,
    neighbourhood: str | None = None,
    hops: int = 1,
    limit: int = DEFAULT_LIMIT,
    filters: GraphFilter | None = None,
) -> list[SearchHit]:
    """Lexical search over node labels and text, best match first.

    ``neighbourhood`` restricts hits to a node and everything within ``hops`` of it, which
    is what "search inside this claim's evidence" means; ``filters`` applies the same node
    filters :func:`query` uses, so a search can be constrained by authority and visibility
    as well.
    """
    if limit <= 0:
        return []
    identities: set[str] | None = None
    if neighbourhood is not None:
        identities = {str(neighbourhood)}
        identities.update(
            neighbour.node.identity
            for neighbour in neighbors(engine, neighbourhood, hops=hops, limit=0)
        )
    with engine.connect() as connection:
        hits = _fts_hits(
            connection,
            terms,
            kinds=kinds,
            limit=limit if filters is None else limit * 4,
            identities=identities,
        )
    if filters is None:
        return hits[:limit]
    return [hit for hit in hits if filters.allows_node(hit.node)][:limit]
