"""Dependency graph and stale propagation (PRODUCT 19.2, 37; ADR-008).

When an upstream object changes, everything derived from it becomes **stale**; nothing is
recomputed and nothing is rewritten. That is the whole point of this module: there is no
API here that takes a repository, no API that returns a rewritten canonical object, and
no code path that mutates one. :func:`mark_changed` answers "what does the researcher now
have to look at?" and stops there.

Edge direction is always *upstream -> downstream*: an edge ``(u, d)`` means "changing
``u`` makes ``d`` stale". :class:`DependencyKind` names how the pair relates, reading the
relation from whichever side is idiomatic, so one kind reads backwards relative to the
stored direction: ``anchored_in`` describes evidence anchored in an artifact, and is
stored as ``artifact -> evidence`` because the artifact is what changes.

The graph is a projection like everything else in this package: it is derived from
canonical fields by :meth:`DependencyGraph.from_objects`, is deletable, and is never the
only copy of anything.

Stale priority follows PRODUCT 37, ordered by how far the staleness reaches the written
science: a stale manuscript anchor is in the paper; a stale Claim is a citable
conclusion; a stale matrix or interpretation is a derived comparison; a stale matrix cell,
taxonomy, or Evidence anchor is an attribution detail whose scientific consequence is
already carried upward to the Claims that cite it; everything else is index-only.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum

from sqlalchemy import Connection, select

from research_harness.domain import (
    Claim,
    Evidence,
    Interpretation,
    ManuscriptAnchor,
    ResearchQuestion,
    SynthesisMatrix,
    Taxonomy,
)
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.ids import (
    ClaimId,
    EvidenceId,
    InterpretationId,
    QuestionId,
    SynthesisId,
    parse_id,
)
from research_harness.projection.rows import (
    MANUSCRIPT_ANCHOR_PREFIX,
    NODE_SEPARATOR,
    TAXONOMY_PREFIX,
    RowSpec,
    matrix_cell_node_id,
    node_id_for,
    taxonomy_node_id,
    upsert_rows,
)
from research_harness.projection.schema import DEPENDENCIES, STALE_MARKS

__all__ = [
    "DependencyEdge",
    "DependencyGraph",
    "DependencyKind",
    "StaleMark",
    "StalePriority",
    "StaleSet",
    "affected_by",
    "load_stale_marks",
    "mark_changed",
    "mark_changed_many",
    "persist_stale_marks",
    "priority_for",
]


class DependencyKind(StrEnum):
    """How a downstream object depends on its upstream object."""

    ANCHORED_IN = "anchored_in"
    """Evidence is anchored in an Artifact; stored ``artifact -> evidence``."""

    SUPPORTS_CLAIM = "supports_claim"
    """Evidence stands in a claim-evidence relation; stored ``evidence -> claim``."""

    DECIDES_CLAIM = "decides_claim"
    """A Decision governs a Claim; stored ``decision -> claim``."""

    DERIVES_CLAIM = "derives_claim"
    """A synthesis Claim is read off a matrix; stored ``matrix -> claim``."""

    COVERS_CLAIM = "covers_claim"
    """A SearchRun backs a Claim's coverage; stored ``search_run -> claim``."""

    CLASSIFIES = "classifies"
    """A Decision, Taxonomy, or classification cell feeds a matrix; stored downstream."""

    CITES_EVIDENCE = "cites_evidence"
    """A matrix cell cites Evidence; stored ``evidence -> cell``."""

    ATTACHES_CLAIM = "attaches_claim"
    """A manuscript anchor asserts a Claim; stored ``claim -> anchor``."""

    ANSWERS_QUESTION = "answers_question"
    """A Claim answers a ResearchQuestion; stored ``claim -> question``."""

    INTERPRETS = "interprets"
    """An Interpretation reads Evidence; stored ``evidence -> interpretation``."""


class StalePriority(IntEnum):
    """Scientific impact of a stale object, highest first (PRODUCT 37)."""

    MANUSCRIPT_ANCHOR = 5
    CLAIM = 4
    SYNTHESIS = 3
    CLASSIFICATION = 2
    INDEX = 1


@dataclass(frozen=True, slots=True, order=True)
class DependencyEdge:
    """One directed edge; changing ``upstream_id`` makes ``downstream_id`` stale."""

    upstream_id: str
    downstream_id: str
    kind: DependencyKind


@dataclass(frozen=True, slots=True)
class StaleMark:
    """One object marked stale, and the change that made it stale."""

    object_id: str
    reason: str
    priority: StalePriority
    source_change: str


def priority_for(object_id: str) -> StalePriority:
    """Stale priority of ``object_id``, dispatching on its node-id prefix / shape.

    Unknown ids fall back to :attr:`StalePriority.INDEX` rather than raising: an
    unrecognised node is index-only noise, never a reason to abort an invalidation.
    """
    text = str(object_id)
    if text.startswith(MANUSCRIPT_ANCHOR_PREFIX):
        return StalePriority.MANUSCRIPT_ANCHOR
    if text.startswith(TAXONOMY_PREFIX):
        return StalePriority.CLASSIFICATION
    if NODE_SEPARATOR in text:
        # ``<matrix>#<work>#<field>`` - one classification cell.
        return StalePriority.CLASSIFICATION
    try:
        identifier = parse_id(text)
    except DomainValidationError:
        return StalePriority.INDEX
    if isinstance(identifier, ClaimId | QuestionId):
        return StalePriority.CLAIM
    if isinstance(identifier, SynthesisId | InterpretationId):
        return StalePriority.SYNTHESIS
    if isinstance(identifier, EvidenceId):
        return StalePriority.CLASSIFICATION
    return StalePriority.INDEX


class StaleSet(AbstractSet[StaleMark]):
    """A set of :class:`StaleMark`s that iterates by priority (desc), then object id."""

    __slots__ = ("_marks",)

    def __init__(self, marks: Iterable[StaleMark] = ()) -> None:
        self._marks: frozenset[StaleMark] = frozenset(marks)

    def __contains__(self, item: object) -> bool:
        return item in self._marks

    def __iter__(self) -> Iterator[StaleMark]:
        return iter(
            sorted(
                self._marks,
                key=lambda mark: (-int(mark.priority), mark.object_id, mark.source_change),
            )
        )

    def __len__(self) -> int:
        return len(self._marks)

    def __repr__(self) -> str:
        return f"StaleSet({list(self)!r})"

    def by_priority(self) -> dict[StalePriority, tuple[StaleMark, ...]]:
        """Marks grouped by priority, highest impact first (the Review Inbox order)."""
        grouped: dict[StalePriority, list[StaleMark]] = {}
        for mark in self:
            grouped.setdefault(mark.priority, []).append(mark)
        return {priority: tuple(marks) for priority, marks in grouped.items()}

    def object_ids(self) -> tuple[str, ...]:
        """Distinct stale object ids in iteration order."""
        seen: dict[str, None] = {}
        for mark in self:
            seen.setdefault(mark.object_id, None)
        return tuple(seen)


class DependencyGraph:
    """Directed dependency graph over projection node ids.

    Cycles are permitted: canonical state should not contain them, but a graph built from
    partially repaired state might, and invalidation must terminate regardless.
    """

    __slots__ = ("_downstream", "_edges", "_upstream")

    def __init__(self, edges: Iterable[DependencyEdge] = ()) -> None:
        self._edges: set[DependencyEdge] = set()
        self._downstream: dict[str, set[str]] = {}
        self._upstream: dict[str, set[str]] = {}
        for edge in edges:
            self.add_edge(edge.upstream_id, edge.downstream_id, edge.kind)

    def add_edge(self, upstream_id: str, downstream_id: str, kind: DependencyKind) -> None:
        """Record that changing ``upstream_id`` makes ``downstream_id`` stale.

        Also the supported way to register a dependency the canonical schema does not
        express, for example a link a plugin or a repair tool knows about and no canonical
        field records.
        """
        upstream = str(upstream_id)
        downstream = str(downstream_id)
        self._edges.add(DependencyEdge(upstream, downstream, kind))
        self._downstream.setdefault(upstream, set()).add(downstream)
        self._upstream.setdefault(downstream, set()).add(upstream)

    def downstream(self, object_id: str) -> frozenset[str]:
        """Objects that directly depend on ``object_id``."""
        return frozenset(self._downstream.get(str(object_id), ()))

    def upstream(self, object_id: str) -> frozenset[str]:
        """Objects that ``object_id`` directly depends on."""
        return frozenset(self._upstream.get(str(object_id), ()))

    def edges(self) -> tuple[DependencyEdge, ...]:
        """Every edge, in a deterministic order."""
        return tuple(sorted(self._edges))

    def nodes(self) -> frozenset[str]:
        """Every node id mentioned by an edge."""
        return frozenset(self._downstream) | frozenset(self._upstream)

    def rows(self) -> list[RowSpec]:
        """Projection rows for the ``dependencies`` table."""
        return [
            RowSpec(
                DEPENDENCIES.name,
                {
                    "upstream_id": edge.upstream_id,
                    "downstream_id": edge.downstream_id,
                    "kind": edge.kind.value,
                },
            )
            for edge in self.edges()
        ]

    @classmethod
    def from_objects(cls, objects: Iterable[object]) -> DependencyGraph:
        """Derive the graph from canonical objects; pure, and it reads fields only.

        Derived edges: ``artifact -> evidence`` (anchor), ``evidence -> claim`` (claim
        relations), ``decision -> claim``, ``search_run -> claim`` (coverage),
        ``matrix -> claim`` (a synthesis claim's ``derived_from``), ``decision ->
        taxonomy`` (the decision that approved a term), ``taxonomy -> matrix`` and
        ``taxonomy -> cell``, ``cell -> matrix``, ``evidence -> cell``, ``claim ->
        manuscript anchor``, ``claim -> question``, ``evidence -> interpretation``.
        Objects with no dependency-bearing fields are ignored.
        """
        graph = cls()
        for obj in objects:
            _derive_edges(graph, obj)
        return graph


def _derive_edges(graph: DependencyGraph, obj: object) -> None:
    if isinstance(obj, Evidence):
        graph.add_edge(str(obj.source.artifact), str(obj.id), DependencyKind.ANCHORED_IN)
    elif isinstance(obj, Interpretation):
        for evidence_id in obj.evidence:
            graph.add_edge(str(evidence_id), str(obj.id), DependencyKind.INTERPRETS)
    elif isinstance(obj, Claim):
        for link in obj.relations:
            graph.add_edge(str(link.evidence), str(obj.id), DependencyKind.SUPPORTS_CLAIM)
        for decision_id in obj.decisions:
            graph.add_edge(str(decision_id), str(obj.id), DependencyKind.DECIDES_CLAIM)
        for run_id in obj.coverage.search_runs:
            graph.add_edge(str(run_id), str(obj.id), DependencyKind.COVERS_CLAIM)
        for matrix_id in obj.derived_from:
            graph.add_edge(str(matrix_id), str(obj.id), DependencyKind.DERIVES_CLAIM)
    elif isinstance(obj, Taxonomy):
        taxonomy_node = taxonomy_node_id(obj.name)
        for term in obj.terms:
            if term.decision is not None:
                graph.add_edge(str(term.decision), taxonomy_node, DependencyKind.CLASSIFIES)
    elif isinstance(obj, SynthesisMatrix):
        matrix_node = str(obj.id)
        scheme_node = None if obj.taxonomy is None else taxonomy_node_id(obj.taxonomy)
        if scheme_node is not None:
            graph.add_edge(scheme_node, matrix_node, DependencyKind.CLASSIFIES)
        for cell in obj.cells:
            cell_node = matrix_cell_node_id(matrix_node, str(cell.work), cell.field)
            graph.add_edge(cell_node, matrix_node, DependencyKind.CLASSIFIES)
            if scheme_node is not None:
                graph.add_edge(scheme_node, cell_node, DependencyKind.CLASSIFIES)
            for evidence_id in cell.evidence:
                graph.add_edge(str(evidence_id), cell_node, DependencyKind.CITES_EVIDENCE)
    elif isinstance(obj, ManuscriptAnchor):
        graph.add_edge(str(obj.claim), node_id_for(obj), DependencyKind.ATTACHES_CLAIM)
    elif isinstance(obj, ResearchQuestion):
        for claim_id in obj.claims:
            graph.add_edge(str(claim_id), str(obj.id), DependencyKind.ANSWERS_QUESTION)


# --- invalidation -----------------------------------------------------------


def _default_reason(source_change: str) -> str:
    return f"upstream {source_change} changed"


def mark_changed(graph: DependencyGraph, object_id: str, *, reason: str | None = None) -> StaleSet:
    """Every object transitively downstream of ``object_id``, marked stale.

    The changed object itself is never in the result: it is the change, not a casualty of
    it. Traversal is breadth-first and visits each node once, so it terminates on cyclic
    graphs. Nothing is written and no object is modified (ADR-008).
    """
    source = str(object_id)
    explanation = reason if reason is not None else _default_reason(source)
    seen: set[str] = {source}
    queue: deque[str] = deque([source])
    marks: list[StaleMark] = []
    while queue:
        current = queue.popleft()
        for downstream_id in sorted(graph.downstream(current)):
            if downstream_id in seen:
                continue
            seen.add(downstream_id)
            queue.append(downstream_id)
            marks.append(
                StaleMark(
                    object_id=downstream_id,
                    reason=explanation,
                    priority=priority_for(downstream_id),
                    source_change=source,
                )
            )
    return StaleSet(marks)


def mark_changed_many(
    graph: DependencyGraph, object_ids: Iterable[str], *, reason: str | None = None
) -> StaleSet:
    """Union of :func:`mark_changed` over ``object_ids``; independent of their order.

    An object downstream of two changes keeps one mark per change, so the researcher sees
    both reasons rather than an arbitrary winner.
    """
    marks: set[StaleMark] = set()
    for object_id in object_ids:
        marks |= set(mark_changed(graph, object_id, reason=reason))
    return StaleSet(marks)


def affected_by(graph: DependencyGraph, object_id: str) -> frozenset[str]:
    """Ids of every object transitively downstream of ``object_id``."""
    return frozenset(mark.object_id for mark in mark_changed(graph, object_id))


# --- persistence (the stale_marks projection table only) --------------------


def persist_stale_marks(connection: Connection, stale_set: StaleSet, since: datetime) -> None:
    """Write ``stale_set`` to the ``stale_marks`` projection table.

    This is the only write in the module, and it touches no canonical file.
    """
    stamp = since.isoformat()
    upsert_rows(
        connection,
        (
            RowSpec(
                STALE_MARKS.name,
                {
                    "object_id": mark.object_id,
                    "source_change_id": mark.source_change,
                    "reason": mark.reason,
                    "since": stamp,
                    "priority": int(mark.priority),
                },
            )
            for mark in stale_set
        ),
    )


def load_stale_marks(connection: Connection) -> StaleSet:
    """Read every mark back from the ``stale_marks`` projection table."""
    rows = connection.execute(
        select(
            STALE_MARKS.c.object_id,
            STALE_MARKS.c.reason,
            STALE_MARKS.c.priority,
            STALE_MARKS.c.source_change_id,
        )
    ).mappings()
    return StaleSet(
        StaleMark(
            object_id=str(row["object_id"]),
            reason=str(row["reason"]),
            priority=StalePriority(int(str(row["priority"]))),
            source_change=str(row["source_change_id"]),
        )
        for row in rows
    )
