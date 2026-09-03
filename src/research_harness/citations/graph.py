"""Citation adjacency: deterministic `cites` edges, node identity, same-work merging.

Two kinds of link live here and they are deliberately different types (Product 17).
A :class:`CitationEdge` is `cites` and nothing else: it is read straight off a source's
reference metadata, so it is deterministic, needs no judgement, and carries only the
provenance of the source that reported it. A :class:`SemanticRelation` (`extends`,
`compares`, `contradicts`, `replicates`) is a reading of what a citation *means*; it
cannot be constructed without at least one Evidence id, and it records whether a verifier
confirmed it.

Nodes are identified by a :data:`NodeKey`: the ``Work`` id once a record is corpus state,
otherwise a deterministic key derived from the strongest identifier the record carries.
Merging is therefore an explicit operation (:meth:`CitationGraph.merge_nodes`) fed by
identity resolution (:func:`resolve_same_work`), not a similarity guess - and the merge
history stays queryable so double-counted support can be reported (ADR-002, Product 17).

Everything in this module is a disposable projection over reference metadata (ADR-006,
Product 15.1): it holds no canonical state and can always be rebuilt from the sources.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, model_validator

from research_harness.domain.base import DomainModel, NonEmptyStr, UtcDatetime, utc_now
from research_harness.domain.enums import IdentityResolutionOutcome
from research_harness.domain.errors import DomainValidationError
from research_harness.domain.ids import EvidenceId, WorkId
from research_harness.domain.research import SourceFailure
from research_harness.domain.work import CandidateMetadata, Work, WorkCandidate
from research_harness.ingest.identity import (
    ExistingRecord,
    IdentityResolution,
    MetadataLookup,
    arxiv_base_id,
    normalize_doi,
    normalize_title,
    resolve_identity,
)

__all__ = [
    "ARTIFACT_REFERENCES",
    "SAME_WORK_OUTCOMES",
    "CitationEdge",
    "CitationGraph",
    "EdgeKey",
    "FetchDirection",
    "NodeKey",
    "NodeResolution",
    "ReferenceList",
    "SemanticRelation",
    "SemanticRelationKind",
    "candidate_key",
    "node_key_for",
    "resolve_nodes",
    "resolve_same_work",
]

logger = logging.getLogger(__name__)

NodeKey = str
"""A graph node: a ``Work`` id (`W0017`) for corpus state, else a candidate key.

Candidate keys are `doi:<normalized doi>`, `arxiv:<base id>`, `title:<title>|<year>`, or
a source-specific identifier, in that order of preference - see :func:`candidate_key`.
"""

EdgeKey = tuple[str, str, str]
"""Identity of a `cites` edge: ``(citing, cited, source)``."""

SemanticRelationKind = Literal["extends", "compares", "contradicts", "replicates"]
FetchDirection = Literal["backward", "forward"]

ARTIFACT_REFERENCES = "artifact_references"
"""Source name for edges parsed out of an artifact this workstation holds."""

#: Outcomes that definitely identify an existing Work, and so may collapse a node.
SAME_WORK_OUTCOMES: frozenset[IdentityResolutionOutcome] = frozenset(
    {
        IdentityResolutionOutcome.SAME_ARTIFACT,
        IdentityResolutionOutcome.SAME_VERSION,
        IdentityResolutionOutcome.SAME_WORK,
    }
)

_SECONDARY_IDENTIFIERS: tuple[str, ...] = ("dblp", "semantic_scholar", "openalex")


# -- node identity -----------------------------------------------------------


def candidate_key(metadata: CandidateMetadata) -> NodeKey:
    """Deterministic node key for candidate metadata, strongest identifier first.

    DOI beats arXiv beats title, because a DOI and an arXiv base id name the work
    globally while a title only names it within this corpus. Source-specific ids (DBLP,
    Semantic Scholar, OpenAlex) rank *below* the title on purpose: two sources that both
    report the same title deduplicate, whereas keying on one source's id would keep them
    apart. A record with none of these cannot be deduplicated at all and is refused
    rather than given an arbitrary key.
    """
    identifiers = metadata.identifiers
    if identifiers.doi is not None:
        doi = normalize_doi(identifiers.doi.value)
        if doi:
            return f"doi:{doi}"
    if identifiers.arxiv is not None:
        base = arxiv_base_id(identifiers.arxiv.value)
        if base:
            return f"arxiv:{base}"
    if metadata.title is not None:
        title = normalize_title(metadata.title.value)
        if title:
            return f"title:{title}|{_year_part(metadata)}"
    for name in _SECONDARY_IDENTIFIERS:
        field = getattr(identifiers, name)
        if field is not None and field.value.strip():
            return f"{name}:{field.value.strip().casefold()}"
    raise DomainValidationError(
        "candidate has neither an identifier nor a title, so it has no deterministic "
        "citation-graph identity"
    )


def node_key_for(item: Work | WorkCandidate) -> NodeKey:
    """Graph identity of a work or candidate; a resolved candidate keys on its Work."""
    if isinstance(item, Work):
        return str(item.id)
    if item.matched_work is not None:
        return str(item.matched_work)
    return candidate_key(item.metadata)


def _year_part(metadata: CandidateMetadata) -> str:
    """The year as a bare integer string, or empty when the source stated none."""
    if metadata.year is None:
        return ""
    text = metadata.year.value.strip()
    try:
        return str(int(text))
    except ValueError:
        return text.casefold()


# -- link types --------------------------------------------------------------


class CitationEdge(DomainModel):
    """One directed `cites` edge, deterministic from a source's reference metadata.

    ``kind`` is pinned to `cites` in the type system: there is no value of it that turns
    an edge into a semantic judgement. What a citation *means* is a
    :class:`SemanticRelation`, which requires Evidence.
    """

    citing: NonEmptyStr
    cited: NonEmptyStr
    source: NonEmptyStr
    recorded_at: UtcDatetime = Field(default_factory=utc_now)
    kind: Literal["cites"] = "cites"

    @property
    def key(self) -> EdgeKey:
        """``(citing, cited, source)`` - one source's report of one citation."""
        return (self.citing, self.cited, self.source)


class SemanticRelation(DomainModel):
    """A semantic reading of a citation, impossible to state without Evidence.

    Product 17 separates raw `cites`, which a reference list yields deterministically,
    from `extends` / `compares` / `contradicts` / `replicates`, which are judgements
    about content. ``evidence`` must name at least one Evidence object - the validator
    below refuses an empty tuple - and ``verified`` records whether a verifier has
    confirmed the reading. An unverified relation is a proposal, never support.

    Both ends are ``WorkId``s: asserting a semantic relation means having read both
    works, so neither end can be a bare discovery candidate.
    """

    kind: SemanticRelationKind
    from_work: WorkId
    to_work: WorkId
    evidence: tuple[EvidenceId, ...]
    verified: bool = False

    @model_validator(mode="after")
    def _requires_evidence(self) -> SemanticRelation:
        """Product 17: only `cites` may exist without evidence."""
        if not self.evidence:
            raise ValueError(
                f"a {self.kind!r} relation requires at least one Evidence id; only "
                "'cites' is deterministic from reference metadata"
            )
        if self.from_work == self.to_work:
            raise ValueError("a semantic relation must relate two different works")
        return self

    @property
    def is_asserted(self) -> bool:
        """True when a verifier has confirmed the relation (Product 17, 20.4)."""
        return self.verified


class ReferenceList(DomainModel):
    """One source's answer for one node: what it cites, or what cites it.

    Kept alongside the edges because coverage depends on the difference between "this
    source reported no references" and "this source could not be asked" (Product 18):
    ``incomplete`` and ``failures`` say which, and ``entries`` preserves each source's
    own candidate records with their own provenance.
    """

    work: NonEmptyStr
    source: NonEmptyStr
    fetched_at: UtcDatetime = Field(default_factory=utc_now)
    direction: FetchDirection = "backward"
    entries: tuple[WorkCandidate, ...] = ()
    incomplete: bool = False
    failures: tuple[SourceFailure, ...] = ()
    warnings: tuple[str, ...] = ()
    """What this answer does not contain: records the source deposited and the adapter or
    the walk refused to seed from, counted rather than silently dropped (dogfood F10)."""


# -- graph -------------------------------------------------------------------


class CitationGraph:
    """Directed `cites` adjacency with fetch provenance and merge history.

    A projection, not canonical state (ADR-006): it is built from reference metadata and
    can always be rebuilt. Edges are deduplicated per source, so two sources reporting
    the same citation stay two rows - dropping one would erase the corroboration that
    independence accounting later needs.
    """

    def __init__(self) -> None:
        self._edges: dict[EdgeKey, CitationEdge] = {}
        self._out: dict[str, set[str]] = {}
        self._in: dict[str, set[str]] = {}
        self._reference_lists: list[ReferenceList] = []
        self._relations: list[SemanticRelation] = []
        self._merges: dict[str, set[str]] = {}

    # -- writing -------------------------------------------------------------

    def add_edge(self, edge: CitationEdge) -> None:
        """Record one `cites` edge; a repeat from the same source keeps the first sighting.

        A self-edge is dropped: after a same-work merge, "this work cites itself" is an
        artefact of the collapse, not a citation between two works.
        """
        if edge.citing == edge.cited:
            logger.debug("dropping self citation on %s reported by %s", edge.citing, edge.source)
            return
        previous = self._edges.get(edge.key)
        if previous is None or edge.recorded_at < previous.recorded_at:
            self._edges[edge.key] = edge
        self._out.setdefault(edge.citing, set()).add(edge.cited)
        self._in.setdefault(edge.cited, set()).add(edge.citing)

    def add_reference_list(self, ref_list: ReferenceList) -> None:
        """Record a fetched list and the edges it implies, oriented by its direction."""
        self._reference_lists.append(ref_list)
        backward = ref_list.direction == "backward"
        for entry in ref_list.entries:
            other = node_key_for(entry)
            citing, cited = (ref_list.work, other) if backward else (other, ref_list.work)
            self.add_edge(
                CitationEdge(
                    citing=citing,
                    cited=cited,
                    source=ref_list.source,
                    recorded_at=ref_list.fetched_at,
                )
            )

    def add_semantic_relation(self, relation: SemanticRelation) -> None:
        """Record an evidence-backed semantic relation; it is never inferred from `cites`."""
        self._relations.append(relation)

    # -- reading -------------------------------------------------------------

    def edges(self) -> tuple[CitationEdge, ...]:
        """Every `cites` edge, ordered by ``(citing, cited, source)``."""
        return tuple(self._edges[key] for key in sorted(self._edges))

    def nodes(self) -> tuple[NodeKey, ...]:
        """Every node the graph knows: edge endpoints plus every fetched node."""
        known = {edge.citing for edge in self._edges.values()}
        known.update(edge.cited for edge in self._edges.values())
        known.update(ref_list.work for ref_list in self._reference_lists)
        return tuple(sorted(known))

    def reference_lists(self) -> tuple[ReferenceList, ...]:
        """Fetched lists in arrival order, each with its own source provenance."""
        return tuple(self._reference_lists)

    def semantic_relations(self) -> tuple[SemanticRelation, ...]:
        """Evidence-backed semantic relations, in declaration order."""
        return tuple(self._relations)

    def merges(self) -> Mapping[NodeKey, tuple[NodeKey, ...]]:
        """Work id -> the node keys that have been collapsed into it (Product 17)."""
        return {target: tuple(sorted(sources)) for target, sources in sorted(self._merges.items())}

    def references_of(self, key: NodeKey) -> tuple[NodeKey, ...]:
        """Nodes ``key`` cites, sorted."""
        return tuple(sorted(self._out.get(key, ())))

    def citations_of(self, key: NodeKey) -> tuple[NodeKey, ...]:
        """Nodes that cite ``key``, sorted."""
        return tuple(sorted(self._in.get(key, ())))

    def predecessors(self, key: NodeKey, depth: int = 1) -> tuple[NodeKey, ...]:
        """Backward neighbourhood: works cited within ``depth`` hops, in BFS order."""
        return self._walk(key, depth, self._out)

    def successors(self, key: NodeKey, depth: int = 1) -> tuple[NodeKey, ...]:
        """Forward neighbourhood: works citing within ``depth`` hops, in BFS order."""
        return self._walk(key, depth, self._in)

    def sources_for(self, citing: NodeKey, cited: NodeKey) -> tuple[str, ...]:
        """Which sources reported this citation; more than one is corroboration."""
        return tuple(
            sorted(
                edge.source
                for edge in self._edges.values()
                if edge.citing == citing and edge.cited == cited
            )
        )

    def _walk(
        self, key: NodeKey, depth: int, adjacency: Mapping[str, set[str]]
    ) -> tuple[NodeKey, ...]:
        """Breadth-first walk of at most ``depth`` levels; cycles terminate on `seen`."""
        if depth <= 0:
            return ()
        seen = {key}
        frontier = [key]
        found: list[str] = []
        for _ in range(depth):
            following: list[str] = []
            for node in frontier:
                for neighbour in sorted(adjacency.get(node, set())):
                    if neighbour in seen:
                        continue
                    seen.add(neighbour)
                    found.append(neighbour)
                    following.append(neighbour)
            if not following:
                break
            frontier = following
        return tuple(found)

    # -- merging -------------------------------------------------------------

    def merge_nodes(self, mapping: Mapping[NodeKey, NodeKey]) -> CitationGraph:
        """A new graph with each key in ``mapping`` replaced by the Work it resolved to.

        This is how a work, its versions, and every source's candidate record for it
        become one node (Product 13, 17): duplicate edges collapse, self-edges disappear,
        and the collapse itself is remembered by :meth:`merges` so that
        `independence.double_counting_risks` can report what stopped being counted twice.
        Semantic relations are carried over unchanged - they are Work-level assertions
        with Evidence behind them, and re-pointing one is a canonical-state decision.
        """
        merged = CitationGraph()
        merged._merges = {target: set(sources) for target, sources in self._merges.items()}
        for source_key, target in mapping.items():
            resolved = _follow(target, mapping)
            if resolved == source_key:
                continue
            merged._merges.setdefault(resolved, set()).add(source_key)
        for edge in self.edges():
            merged.add_edge(
                edge.touch(
                    citing=_follow(edge.citing, mapping),
                    cited=_follow(edge.cited, mapping),
                )
            )
        for ref_list in self._reference_lists:
            merged._reference_lists.append(ref_list.touch(work=_follow(ref_list.work, mapping)))
        merged._relations = list(self._relations)
        return merged

    # -- projection rows -----------------------------------------------------

    def to_rows(self) -> list[dict[str, str]]:
        """`cites` adjacency rows for the citation-graph projection table (Product 15.1).

        Rows are the adjacency and nothing else. Reference lists, merge history, and
        semantic relations are deliberately absent: the first two are fetch provenance
        and the third is evidence-backed canonical state, none of which belongs in a
        deletable adjacency index. ``from_rows(g.to_rows()).edges() == g.edges()``.
        """
        return [
            {
                "citing": edge.citing,
                "cited": edge.cited,
                "kind": edge.kind,
                "source": edge.source,
                "recorded_at": edge.recorded_at.isoformat(),
            }
            for edge in self.edges()
        ]

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, Any]]) -> CitationGraph:
        """Rebuild the adjacency from :meth:`to_rows` output (or an equivalent table)."""
        graph = cls()
        for row in rows:
            graph.add_edge(
                CitationEdge(
                    citing=row["citing"],
                    cited=row["cited"],
                    source=row["source"],
                    recorded_at=row["recorded_at"],
                )
            )
        return graph

    def __len__(self) -> int:
        return len(self._edges)

    def __repr__(self) -> str:
        return f"CitationGraph(nodes={len(self.nodes())}, edges={len(self._edges)})"


def _follow(key: NodeKey, mapping: Mapping[NodeKey, NodeKey]) -> NodeKey:
    """Follow ``mapping`` to its fixed point, stopping on a cycle rather than hanging."""
    seen = {key}
    current = key
    while current in mapping:
        nxt = mapping[current]
        if nxt in seen:
            logger.debug("same-work mapping cycles at %s; stopping there", nxt)
            return current
        seen.add(nxt)
        current = nxt
    return current


# -- same-work resolution ----------------------------------------------------


class NodeResolution(DomainModel):
    """One candidate's node key and what identity resolution decided about it."""

    key: NonEmptyStr
    candidate: WorkCandidate
    resolution: IdentityResolution

    @property
    def outcome(self) -> IdentityResolutionOutcome:
        """The resolver's verdict."""
        return self.resolution.outcome

    @property
    def work(self) -> WorkId | None:
        """The Work this candidate is, when the resolver was sure; else ``None``."""
        return self.resolution.work

    @property
    def is_same_work(self) -> bool:
        """True when the outcome definitely identifies an existing Work."""
        return self.outcome in SAME_WORK_OUTCOMES

    @property
    def resolved(self) -> WorkCandidate:
        """The candidate carrying this outcome; screening state is untouched."""
        return self.resolution.applied_to(self.candidate)


def resolve_nodes(
    candidates: Sequence[WorkCandidate],
    existing: Sequence[ExistingRecord],
    *,
    lookup: MetadataLookup | None = None,
) -> tuple[NodeResolution, ...]:
    """Resolve each distinct candidate node against the corpus, in first-seen order.

    Candidates sharing a node key are resolved once: they are already the same record as
    far as the graph is concerned.
    """
    records = tuple(existing)
    seen: set[str] = set()
    resolutions: list[NodeResolution] = []
    for candidate in candidates:
        key = node_key_for(candidate)
        if key in seen:
            continue
        seen.add(key)
        resolutions.append(
            NodeResolution(
                key=key,
                candidate=candidate,
                resolution=resolve_identity(candidate, records, lookup=lookup),
            )
        )
    return tuple(resolutions)


def resolve_same_work(
    candidates: Sequence[WorkCandidate],
    existing: Sequence[ExistingRecord],
    *,
    lookup: MetadataLookup | None = None,
) -> dict[NodeKey, NodeKey]:
    """Node key -> Work id for candidates the resolver definitely identified.

    Only `same_work`, `same_version`, and `same_artifact` collapse a node: those three
    name an existing Work. `distinct_work` keeps its own key because it *is* a new work,
    and `unresolved` keeps its own key because merging on a guess is exactly the
    double-counting error this mapping exists to prevent - use :func:`resolve_nodes` to
    report those to the researcher.
    """
    return {
        resolution.key: str(resolution.work)
        for resolution in resolve_nodes(candidates, existing, lookup=lookup)
        if resolution.work is not None and resolution.key != str(resolution.work)
    }
