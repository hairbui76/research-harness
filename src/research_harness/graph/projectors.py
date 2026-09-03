"""One projector per namespace: canonical and durable files in, nodes and edges out.

Every projector yields :class:`ProjectionUnit`s, and a unit is the whole projection of one
durable file — its workspace-relative path is the *source key*, and its digest is the
fingerprint. That is what makes an incremental update exact: when a file's digest changes,
`graph.rebuild` deletes everything that file produced and inserts what it produces now
(graph spec §4).

Authority is read off canonical state, never invented:

* a relation written into a `Claim` is accepted state, so its edge is
  ``origin=accepted`` and (unless the claim is stale) ``authority=accepted``;
* a proposal sitting in `.research/staging/` is ``origin=model_proposed`` and
  ``authority=candidate``, and :class:`~research_harness.domain.graph.GraphEdge` refuses to
  build any other combination (ADR-003, ADR-007).

Staged files are read as plain JSON rather than through `evidence/` and `workflows/`,
which reach `providers/` and `capabilities/` and would drag both into a projection layer
that `docs/architecture/conventions.md` keeps free of them. A staged file that cannot be
read the way this module expects is skipped with a debug log: staging is regenerable, and
an unreadable proposal is never a reason to fail a rebuild.

Adding a namespace means adding a :class:`Projector` to :func:`default_projectors`; nothing
else in the package changes, which is how the conversation namespace joins later.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from research_harness.domain import (
    Claim,
    ClaimEvidenceRelationType,
    ClaimStatus,
    Decision,
    DecisionStatus,
    DocumentBlock,
    DocumentBlockKind,
    Evidence,
    EvidenceStatus,
    ManuscriptAnchor,
    ManuscriptAnchorStatus,
    ResearchQuestion,
    StaleState,
    SynthesisMatrix,
    Work,
)
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.graph import (
    EdgeKind,
    EdgeOrigin,
    GraphAuthority,
    GraphEdge,
    GraphMetadata,
    GraphNode,
    NodeKind,
)
from research_harness.domain.ids import (
    ArtifactId,
    ClaimId,
    DecisionId,
    EvidenceId,
    QuestionId,
    SynthesisId,
    VersionId,
    WorkId,
    parse_id,
)
from research_harness.projection.dependencies import DependencyGraph
from research_harness.projection.rows import MANUSCRIPT_ANCHOR_PREFIX, manuscript_anchor_key
from research_harness.workspace.events import file_digest
from research_harness.workspace.layout import (
    BLOCKS_SUFFIX,
    RESEARCH_DIRNAME,
    WorkspaceLayout,
)
from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "ANCHOR_PREFIX",
    "BLOCK_PREFIX",
    "CANDIDATE_PREFIX",
    "CITATION_PREFIX",
    "FILE_PREFIX",
    "PROJECT_PREFIX",
    "CandidateProjector",
    "ClaimProjector",
    "CorpusProjector",
    "DecisionProjector",
    "DocumentProjector",
    "EvidenceProjector",
    "ManuscriptProjector",
    "ProjectProjector",
    "ProjectionContext",
    "ProjectionUnit",
    "Projector",
    "QuestionProjector",
    "SynthesisProjector",
    "anchor_identity",
    "block_identity",
    "candidate_identity",
    "citation_identity",
    "default_projectors",
    "graph_identity",
    "manuscript_file_identity",
    "project_all",
    "project_identity",
]

logger = logging.getLogger(__name__)

PROJECT_PREFIX = "project:"
BLOCK_PREFIX = "block:"
FILE_PREFIX = "file:"
ANCHOR_PREFIX = "anchor:"
CITATION_PREFIX = "cite:"
CANDIDATE_PREFIX = "candidate:"

_LABEL_CHARS = 120
_STAGING_EVIDENCE = ("staging", "evidence")
_STAGING_CLAIM_AUDIT = ("staging", "claim_audit")
_MANUSCRIPT_SUFFIXES = frozenset({".tex", ".bib", ".sty", ".cls", ".bbl"})
_BIB_SUFFIX = ".bib"


# --- identities -------------------------------------------------------------


def project_identity(name: str) -> str:
    """``project:<name>`` — the root node every corpus object hangs off."""
    return f"{PROJECT_PREFIX}{name}"


def block_identity(artifact: str, block: str) -> str:
    """``block:<artifact>#<block>``; a `BlockId` is unique inside its artifact, not globally."""
    return f"{BLOCK_PREFIX}{artifact}#{block}"


def manuscript_file_identity(path: str) -> str:
    """``file:manuscript/main.tex`` — a manuscript source file has no research id."""
    return f"{FILE_PREFIX}{path}"


def anchor_identity(file: str, sentence_fingerprint: str) -> str:
    """``anchor:<file>#<sentence fingerprint>`` — the anchor's own canonical coordinate."""
    return f"{ANCHOR_PREFIX}{file}#{sentence_fingerprint}"


def citation_identity(key: str) -> str:
    """``cite:<bibtex or parsed reference key>``."""
    return f"{CITATION_PREFIX}{key}"


def candidate_identity(candidate_id: str) -> str:
    """``candidate:<candidate id>`` — a staged proposal, never an `EvidenceId`."""
    return f"{CANDIDATE_PREFIX}{candidate_id}"


_DEPENDENCY_NODE_TYPES = (WorkId, VersionId, ArtifactId, EvidenceId, ClaimId, QuestionId)


def graph_identity(dependency_node: str) -> str | None:
    """Graph identity of a `projection.dependencies` node id, or ``None`` if it has none.

    The dependency projection also has nodes for taxonomies, search runs, matrix cells,
    notes, and interpretations. Those namespaces are deliberately outside the graph's node
    vocabulary (graph spec §2), so a `depends_on` edge through one is dropped rather than
    invented; `projection.dependencies` remains the authority for staleness, and the
    projectors that own such a link collapse it explicitly where it is worth keeping
    (`SynthesisProjector` does this for matrix cells).
    """
    text = str(dependency_node)
    if text.startswith(MANUSCRIPT_ANCHOR_PREFIX):
        file, _, fingerprint = text[len(MANUSCRIPT_ANCHOR_PREFIX) :].partition("#")
        return anchor_identity(file, fingerprint) if fingerprint else None
    try:
        identifier = parse_id(text)
    except ResearchHarnessError:
        return None
    if isinstance(identifier, DecisionId | SynthesisId):
        return text
    if isinstance(identifier, _DEPENDENCY_NODE_TYPES):
        return text
    return None


# --- units and context ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProjectionUnit:
    """Everything one durable file projects, keyed by that file so it can be replaced."""

    source_key: str
    """Workspace-relative POSIX path of the file, e.g. `claims/C0041.yaml`."""

    fingerprint: str
    """`sha256:<hex>` of the file's bytes; a change is what triggers a re-projection."""

    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True when the file projected nothing (an empty collection, say)."""
        return not self.nodes and not self.edges


@dataclass
class ProjectionContext:
    """Canonical state read once, shared by every projector, plus path/digest helpers.

    Reading is eager per collection and cached: a rebuild and an update both walk the whole
    workspace, exactly as `projection.rebuild` does, and the projectors then divide the
    same objects between them rather than each reopening the tree.
    """

    repo: WorkspaceRepository
    research_dir: Path
    _digests: dict[str, str] = field(default_factory=dict, repr=False)
    _cache: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def open(
        cls, repo: WorkspaceRepository, *, research_dir: Path | str | None = None
    ) -> ProjectionContext:
        """Context for ``repo``; ``research_dir`` overrides where staging is read from."""
        directory = repo.layout.research_dir if research_dir is None else Path(research_dir)
        return cls(repo=repo, research_dir=directory)

    @property
    def layout(self) -> WorkspaceLayout:
        return self.repo.layout

    @property
    def project(self) -> str:
        """The project's name, from `research.yaml`."""
        return self.repo.config.name

    def relative(self, path: Path) -> str:
        """Workspace-relative POSIX path, used as the source key of a unit.

        A file under the research directory is always named `.research/<path>`, whatever
        directory this projection was told to use. A graph built into a temporary index
        directory therefore carries the same source keys as one built in place, which is
        what lets a test compare the two dumps at all.
        """
        try:
            return f"{RESEARCH_DIRNAME}/{path.relative_to(self.research_dir).as_posix()}"
        except ValueError:
            pass
        try:
            return str(self.layout.relative(path))
        except ResearchHarnessError:
            return str(path)

    def digest(self, path: Path) -> str:
        """Cached `sha256:<hex>` of a file's bytes; ``""`` when it cannot be read."""
        key = str(path)
        cached = self._digests.get(key)
        if cached is None:
            try:
                cached = file_digest(path)
            except OSError:
                cached = ""
            self._digests[key] = cached
        return cached

    def works(self) -> list[Work]:
        return self._memo("works", self.repo.list_works)

    def claims(self) -> list[Claim]:
        return self._memo("claims", self.repo.list_claims)

    def questions(self) -> list[ResearchQuestion]:
        return self._memo("questions", self.repo.list_questions)

    def decisions(self) -> list[Decision]:
        return self._memo("decisions", self.repo.list_decisions)

    def matrices(self) -> list[SynthesisMatrix]:
        return self._memo("matrices", self.repo.list_matrices)

    def anchors(self) -> list[ManuscriptAnchor]:
        return self._memo("anchors", lambda: list(self.repo.iter_anchors()))

    def evidence(self, work: WorkId) -> list[Evidence]:
        return self._memo(f"evidence:{work}", lambda: list(self.repo.iter_evidence(work)))

    def dependencies(self) -> DependencyGraph:
        """The `projection.dependencies` graph over every canonical object, built once."""
        return self._memo("dependencies", self._build_dependencies)

    def _build_dependencies(self) -> DependencyGraph:
        objects: list[object] = []
        for work in self.works():
            objects.extend(self.evidence(work.id))
        objects.extend(self.claims())
        objects.extend(self.questions())
        objects.extend(self.matrices())
        objects.extend(self.anchors())
        objects.extend(self.repo.list_taxonomies())
        return DependencyGraph.from_objects(objects)

    def _memo[T](self, key: str, build: Callable[[], T]) -> T:
        if key not in self._cache:
            self._cache[key] = build()
        value: T = self._cache[key]
        return value


@runtime_checkable
class Projector(Protocol):
    """One namespace's projection. Pure with respect to canonical state: it only reads."""

    name: str

    def project(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        """Yield one unit per durable file this projector is responsible for."""
        ...


# --- shared mappings --------------------------------------------------------

_BLOCK_NODE_KINDS: dict[DocumentBlockKind, NodeKind] = {
    DocumentBlockKind.SECTION: NodeKind.SECTION,
    DocumentBlockKind.PARAGRAPH: NodeKind.PARAGRAPH,
    DocumentBlockKind.TABLE: NodeKind.TABLE,
    DocumentBlockKind.TABLE_CELL: NodeKind.TABLE,
    DocumentBlockKind.TABLE_CAPTION: NodeKind.TABLE,
    DocumentBlockKind.FIGURE_CAPTION: NodeKind.FIGURE,
    DocumentBlockKind.EQUATION: NodeKind.EQUATION,
    DocumentBlockKind.REFERENCE: NodeKind.REFERENCE,
    DocumentBlockKind.FOOTNOTE: NodeKind.PARAGRAPH,
    DocumentBlockKind.OTHER: NodeKind.PARAGRAPH,
}

_RELATION_EDGE_KINDS: dict[ClaimEvidenceRelationType, EdgeKind] = {
    ClaimEvidenceRelationType.SUPPORTS: EdgeKind.SUPPORTS,
    ClaimEvidenceRelationType.CONTRADICTS: EdgeKind.CONTRADICTS,
    ClaimEvidenceRelationType.QUALIFIES: EdgeKind.QUALIFIES,
}
"""The three relations the edge vocabulary names.

`contextualizes`, `exemplifies`, and `incomparable_under_current_evidence` are projected as
`mentioned_in` carrying the exact canonical relation in metadata, because calling any of
them `qualifies` would put a relation in the graph that the Claim does not assert.
"""


def evidence_authority(evidence: Evidence) -> GraphAuthority:
    """Authority label for an Evidence node, read off its verification record."""
    if evidence.stale is StaleState.STALE or evidence.status is EvidenceStatus.STALE:
        return GraphAuthority.STALE
    if evidence.status is EvidenceStatus.ACCEPTED:
        return GraphAuthority.ACCEPTED
    if evidence.status in {EvidenceStatus.REJECTED, EvidenceStatus.SUPERSEDED}:
        return GraphAuthority.CONTESTED
    return GraphAuthority.CANDIDATE


def claim_authority(claim: Claim) -> GraphAuthority:
    """Authority label for a Claim node and for the relations it asserts."""
    if claim.stale is StaleState.STALE:
        return GraphAuthority.STALE
    if claim.status is ClaimStatus.QUALIFIED:
        return GraphAuthority.QUALIFIED
    if claim.status in {ClaimStatus.CONTESTED, ClaimStatus.UNSUPPORTED, ClaimStatus.SUPERSEDED}:
        return GraphAuthority.CONTESTED
    return GraphAuthority.ACCEPTED


def _stale_or_accepted(stale: StaleState) -> GraphAuthority:
    """`stale` when the object's own canonical flag says so, `accepted` otherwise."""
    return GraphAuthority.STALE if stale is StaleState.STALE else GraphAuthority.ACCEPTED


def _evidence_text(evidence: Evidence) -> str:
    """What an Evidence node offers to lexical search: its span, field, and metric."""
    numeric = evidence.content.numeric
    parts = (
        evidence.content.exact_text,
        evidence.content.field or "",
        "" if numeric is None else numeric.metric,
    )
    return " ".join(part for part in parts if part)


def _clip(text: str, limit: int = _LABEL_CHARS) -> str:
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else f"{collapsed[: limit - 1]}…"


def _meta(**values: Any) -> GraphMetadata:
    """Metadata with empty values dropped, so two projections compare byte for byte."""
    return {key: value for key, value in sorted(values.items()) if value not in (None, "", ())}


def _depends_on_edges(
    ctx: ProjectionContext,
    downstream: str,
    *,
    authority: GraphAuthority,
    source: str,
    dependency_node: str | None = None,
) -> list[GraphEdge]:
    """`downstream --depends_on--> upstream` for every upstream the dependency graph knows.

    ``dependency_node`` is the id `projection.dependencies` uses when it differs from the
    graph identity — a manuscript anchor is `MA:<file>#<fingerprint>` there and
    `anchor:<file>#<fingerprint>` here.
    """
    edges: list[GraphEdge] = []
    node = downstream if dependency_node is None else dependency_node
    for upstream in sorted(ctx.dependencies().upstream(node)):
        identity = graph_identity(upstream)
        if identity is None or identity == downstream:
            continue
        edges.append(
            GraphEdge(
                from_id=downstream,
                to_id=identity,
                kind=EdgeKind.DEPENDS_ON,
                origin=EdgeOrigin.STRUCTURAL,
                authority=authority,
                source=source,
            )
        )
    return edges


# --- projectors -------------------------------------------------------------


class ProjectProjector:
    """The project root node, read from `research.yaml`."""

    name = "project"

    def project(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        path = ctx.layout.research_file
        if not path.is_file():
            return
        identity = project_identity(ctx.project)
        source = ctx.relative(path)
        yield ProjectionUnit(
            source_key=source,
            fingerprint=ctx.digest(path),
            nodes=(
                GraphNode(
                    identity=identity,
                    kind=NodeKind.PROJECT,
                    label=ctx.project,
                    text=ctx.project,
                    source=source,
                    fingerprint=ctx.digest(path),
                ),
            ),
        )


class CorpusProjector:
    """Work / Version / Artifact identity and the `version_of` / `artifact_of` spine."""

    name = "corpus"

    def project(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        root = project_identity(ctx.project)
        for work in ctx.works():
            yield self._work(ctx, work, root)
            for version in ctx.repo.list_versions(work.id):
                path = ctx.layout.version_file(work.id, version.id)
                source = ctx.relative(path)
                yield ProjectionUnit(
                    source_key=source,
                    fingerprint=ctx.digest(path),
                    nodes=(
                        GraphNode(
                            identity=str(version.id),
                            kind=NodeKind.VERSION,
                            label=version.label or f"{version.kind.value} of {work.title}",
                            text=_clip(f"{version.label or ''} {work.title}"),
                            source=source,
                            fingerprint=ctx.digest(path),
                            metadata=_meta(
                                work=str(version.work),
                                kind=version.kind.value,
                                date=None if version.date is None else version.date.isoformat(),
                            ),
                        ),
                    ),
                    edges=(
                        GraphEdge(
                            from_id=str(version.id),
                            to_id=str(version.work),
                            kind=EdgeKind.VERSION_OF,
                            origin=EdgeOrigin.STRUCTURAL,
                            authority=GraphAuthority.ACCEPTED,
                            source=source,
                        ),
                    ),
                )
            for artifact in ctx.repo.list_artifacts(work.id):
                path = ctx.layout.artifact_file(work.id, artifact.id)
                source = ctx.relative(path)
                yield ProjectionUnit(
                    source_key=source,
                    fingerprint=ctx.digest(path),
                    nodes=(
                        GraphNode(
                            identity=str(artifact.id),
                            kind=NodeKind.ARTIFACT,
                            label=artifact.original_filename,
                            text=_clip(f"{artifact.original_filename} {work.title}"),
                            source=source,
                            fingerprint=artifact.file_hash,
                            metadata=_meta(
                                work=str(artifact.work),
                                version=str(artifact.version),
                                kind=artifact.kind.value,
                                mime_type=artifact.mime_type,
                                file_hash=artifact.file_hash,
                            ),
                        ),
                    ),
                    edges=(
                        GraphEdge(
                            from_id=str(artifact.id),
                            to_id=str(artifact.version),
                            kind=EdgeKind.ARTIFACT_OF,
                            origin=EdgeOrigin.STRUCTURAL,
                            authority=GraphAuthority.ACCEPTED,
                            source=source,
                        ),
                    ),
                )

    def _work(self, ctx: ProjectionContext, work: Work, root: str) -> ProjectionUnit:
        path = ctx.layout.work_file(work.id)
        source = ctx.relative(path)
        authors = ", ".join(work.authors)
        node = GraphNode(
            identity=str(work.id),
            kind=NodeKind.WORK,
            label=work.title,
            text=_clip(f"{work.title} {authors} {work.venue or ''} {work.year or ''}", 400),
            source=source,
            fingerprint=ctx.digest(path),
            metadata=_meta(
                year=work.year,
                venue=work.venue,
                screening=work.screening.value,
                authors=authors,
            ),
        )
        edge = GraphEdge(
            from_id=root,
            to_id=str(work.id),
            kind=EdgeKind.CONTAINS,
            origin=EdgeOrigin.STRUCTURAL,
            authority=GraphAuthority.ACCEPTED,
            source=source,
        )
        return ProjectionUnit(
            source_key=source, fingerprint=ctx.digest(path), nodes=(node,), edges=(edge,)
        )


class DocumentProjector:
    """Document structure from the stored parse blocks (ADR-011): one unit per blocks file."""

    name = "document"

    def project(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        for work in ctx.works():
            for path in sorted(ctx.layout.parsed_dir(work.id).glob(f"*{BLOCKS_SUFFIX}")):
                artifact = ArtifactId(path.name[: -len(BLOCKS_SUFFIX)])
                blocks = list(ctx.repo.iter_blocks(artifact, work=work.id))
                yield self._blocks(ctx, path, artifact, blocks)

    def _blocks(
        self,
        ctx: ProjectionContext,
        path: Path,
        artifact: ArtifactId,
        blocks: Sequence[DocumentBlock],
    ) -> ProjectionUnit:
        source = ctx.relative(path)
        fingerprint = ctx.digest(path)
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        seen_citations: set[str] = set()
        for block in blocks:
            identity = block_identity(str(artifact), str(block.id))
            nodes.append(
                GraphNode(
                    identity=identity,
                    kind=_BLOCK_NODE_KINDS.get(block.kind, NodeKind.PARAGRAPH),
                    label=_clip(block.caption or block.text or block.kind.value),
                    text=block.text,
                    source=source,
                    fingerprint=block.text_hash,
                    metadata=_meta(
                        artifact=str(artifact),
                        work=str(block.work),
                        version=str(block.version),
                        block=str(block.id),
                        block_kind=block.kind.value,
                        page=block.page,
                        order=block.order,
                        section_path=" / ".join(block.section_path),
                        text_hash=block.text_hash,
                    ),
                )
            )
            edges.append(
                GraphEdge(
                    from_id=str(artifact),
                    to_id=identity,
                    kind=EdgeKind.CONTAINS,
                    origin=EdgeOrigin.STRUCTURAL,
                    authority=GraphAuthority.ACCEPTED,
                    source=source,
                    metadata=_meta(page=block.page, order=block.order),
                )
            )
            if block.caption_for is not None:
                edges.append(
                    GraphEdge(
                        from_id=block_identity(str(artifact), str(block.caption_for)),
                        to_id=identity,
                        kind=EdgeKind.CONTAINS,
                        origin=EdgeOrigin.STRUCTURAL,
                        authority=GraphAuthority.ACCEPTED,
                        source=source,
                        metadata=_meta(role="caption"),
                    )
                )
            key = (block.reference_key or "").strip()
            if key:
                citation = citation_identity(key)
                if citation not in seen_citations:
                    seen_citations.add(citation)
                    nodes.append(
                        GraphNode(
                            identity=citation,
                            kind=NodeKind.CITATION,
                            label=key,
                            text=_clip(block.reference_raw or block.text, 400),
                            source=source,
                            fingerprint=fingerprint,
                            metadata=_meta(key=key, origin="parsed_reference"),
                        )
                    )
                edges.append(
                    GraphEdge(
                        from_id=str(artifact),
                        to_id=citation,
                        kind=EdgeKind.CITES,
                        origin=EdgeOrigin.STRUCTURAL,
                        authority=GraphAuthority.ACCEPTED,
                        source=source,
                        metadata=_meta(block=str(block.id), key=key),
                    )
                )
        return ProjectionUnit(
            source_key=source,
            fingerprint=fingerprint,
            nodes=tuple(nodes),
            edges=tuple(edges),
        )


class EvidenceProjector:
    """Evidence nodes and the `anchored_at` edges that make provenance one hop from a claim."""

    name = "evidence"

    def project(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        for work in ctx.works():
            path = ctx.layout.evidence_file(work.id)
            if not path.is_file():
                continue
            yield self._evidence(ctx, path, ctx.evidence(work.id))

    def _evidence(
        self, ctx: ProjectionContext, path: Path, records: Sequence[Evidence]
    ) -> ProjectionUnit:
        source = ctx.relative(path)
        fingerprint = ctx.digest(path)
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        for evidence in records:
            identity = str(evidence.id)
            anchor = evidence.source
            authority = evidence_authority(evidence)
            nodes.append(
                GraphNode(
                    identity=identity,
                    kind=NodeKind.EVIDENCE,
                    authority=authority,
                    label=_clip(evidence.content.exact_text or evidence.evidence_type.value),
                    text=_evidence_text(evidence),
                    source=source,
                    fingerprint=anchor.text_hash,
                    metadata=_meta(
                        work=str(anchor.work),
                        version=str(anchor.version),
                        artifact=str(anchor.artifact),
                        block=str(anchor.block),
                        page=anchor.page,
                        status=evidence.status.value,
                        origin=evidence.origin.value,
                        strength=evidence.strength.value,
                        evidence_type=evidence.evidence_type.value,
                        review_tier=int(evidence.review_tier),
                        section_path=" / ".join(anchor.section_path),
                    ),
                )
            )
            anchor_meta = _meta(
                page=anchor.page,
                block=str(anchor.block),
                char_start=anchor.char_start,
                char_end=anchor.char_end,
                text_hash=anchor.text_hash,
                file_hash=anchor.file_hash,
                section_path=" / ".join(anchor.section_path),
            )
            edges.append(
                GraphEdge(
                    from_id=identity,
                    to_id=block_identity(str(anchor.artifact), str(anchor.block)),
                    kind=EdgeKind.ANCHORED_AT,
                    origin=EdgeOrigin.STRUCTURAL,
                    authority=authority,
                    status=evidence.status.value,
                    source=source,
                    metadata=anchor_meta,
                )
            )
            edges.append(
                GraphEdge(
                    from_id=identity,
                    to_id=str(anchor.artifact),
                    kind=EdgeKind.ANCHORED_AT,
                    origin=EdgeOrigin.STRUCTURAL,
                    authority=authority,
                    status=evidence.status.value,
                    source=source,
                    metadata=anchor_meta,
                )
            )
            edges.append(
                GraphEdge(
                    from_id=str(anchor.work),
                    to_id=identity,
                    kind=EdgeKind.CONTAINS,
                    origin=EdgeOrigin.STRUCTURAL,
                    authority=authority,
                    source=source,
                )
            )
            edges.extend(_depends_on_edges(ctx, identity, authority=authority, source=source))
        return ProjectionUnit(
            source_key=source, fingerprint=fingerprint, nodes=tuple(nodes), edges=tuple(edges)
        )


class ClaimProjector:
    """Claims and the accepted scientific relations they assert."""

    name = "claim"

    def project(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        for claim in ctx.claims():
            path = ctx.layout.claim_file(claim.id)
            source = ctx.relative(path)
            identity = str(claim.id)
            authority = claim_authority(claim)
            semantics = claim.semantics
            node = GraphNode(
                identity=identity,
                kind=NodeKind.CLAIM,
                authority=authority,
                label=_clip(claim.statement),
                text=" ".join(
                    (claim.statement, semantics.subject, semantics.predicate, semantics.object)
                ),
                source=source,
                fingerprint=ctx.digest(path),
                metadata=_meta(
                    status=claim.status.value,
                    type=claim.type.value,
                    scope=claim.scope.level.value,
                    requested_strength=claim.requested_strength.value,
                    allowed_strength=claim.allowed_strength.value,
                    stale=claim.stale.value,
                ),
            )
            edges: list[GraphEdge] = []
            for link in claim.relations:
                kind = _RELATION_EDGE_KINDS.get(link.relation)
                edges.append(
                    GraphEdge(
                        from_id=str(link.evidence),
                        to_id=identity,
                        kind=EdgeKind.MENTIONED_IN if kind is None else kind,
                        origin=EdgeOrigin.ACCEPTED,
                        authority=authority,
                        status=claim.status.value,
                        source=source,
                        metadata=_meta(
                            relation=link.relation.value, aspect=link.aspect, note=link.note
                        ),
                    )
                )
            for matrix in claim.derived_from:
                edges.append(
                    GraphEdge(
                        from_id=identity,
                        to_id=str(matrix),
                        kind=EdgeKind.DERIVED_FROM,
                        origin=EdgeOrigin.ACCEPTED,
                        authority=authority,
                        status=claim.status.value,
                        source=source,
                    )
                )
            edges.extend(_depends_on_edges(ctx, identity, authority=authority, source=source))
            yield ProjectionUnit(
                source_key=source,
                fingerprint=ctx.digest(path),
                nodes=(node,),
                edges=tuple(edges),
            )


class QuestionProjector:
    """Research questions and the evidence a question already names."""

    name = "question"

    def project(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        for question in ctx.questions():
            path = ctx.layout.question_file(question.id)
            source = ctx.relative(path)
            identity = str(question.id)
            authority = _stale_or_accepted(question.stale)
            node = GraphNode(
                identity=identity,
                kind=NodeKind.QUESTION,
                authority=authority,
                label=_clip(question.question),
                text=" ".join((question.question, question.remaining_uncertainty or "")),
                source=source,
                fingerprint=ctx.digest(path),
                metadata=_meta(status=question.status.value, stale=question.stale.value),
            )
            edges = [
                GraphEdge(
                    from_id=identity,
                    to_id=str(evidence_id),
                    kind=EdgeKind.MENTIONED_IN,
                    origin=EdgeOrigin.ACCEPTED,
                    authority=authority,
                    source=source,
                    metadata=_meta(role=role),
                )
                for role, values in (
                    ("supporting_evidence", question.supporting_evidence),
                    ("counter_evidence", question.counter_evidence),
                )
                for evidence_id in values
            ]
            edges.extend(_depends_on_edges(ctx, identity, authority=authority, source=source))
            yield ProjectionUnit(
                source_key=source,
                fingerprint=ctx.digest(path),
                nodes=(node,),
                edges=tuple(edges),
            )


class DecisionProjector:
    """Researcher decisions, the claim each governs, and the decision it supersedes."""

    name = "decision"

    def project(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        for decision in ctx.decisions():
            path = ctx.layout.decision_file(decision.id)
            source = ctx.relative(path)
            identity = str(decision.id)
            authority = (
                GraphAuthority.ACCEPTED
                if decision.status is DecisionStatus.ACCEPTED
                else GraphAuthority.CANDIDATE
                if decision.status is DecisionStatus.PROPOSED
                else GraphAuthority.CONTESTED
            )
            node = GraphNode(
                identity=identity,
                kind=NodeKind.DECISION,
                authority=authority,
                label=_clip(decision.title or decision.rationale),
                text=" ".join((decision.title or "", decision.rationale)),
                source=source,
                fingerprint=ctx.digest(path),
                metadata=_meta(type=decision.type.value, status=decision.status.value),
            )
            edges: list[GraphEdge] = []
            if decision.claim is not None:
                edges.append(
                    GraphEdge(
                        from_id=identity,
                        to_id=str(decision.claim),
                        kind=EdgeKind.MENTIONED_IN,
                        origin=EdgeOrigin.RESEARCHER,
                        authority=authority,
                        status=decision.status.value,
                        source=source,
                    )
                )
            if decision.supersedes is not None:
                edges.append(
                    GraphEdge(
                        from_id=identity,
                        to_id=str(decision.supersedes),
                        kind=EdgeKind.DERIVED_FROM,
                        origin=EdgeOrigin.RESEARCHER,
                        authority=authority,
                        status=decision.status.value,
                        source=source,
                    )
                )
            yield ProjectionUnit(
                source_key=source,
                fingerprint=ctx.digest(path),
                nodes=(node,),
                edges=tuple(edges),
            )


class SynthesisProjector:
    """Synthesis matrices, the works they compare, and the evidence their cells cite."""

    name = "synthesis"

    def project(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        for matrix in ctx.matrices():
            path = ctx.layout.matrix_file(matrix.id)
            source = ctx.relative(path)
            identity = str(matrix.id)
            authority = _stale_or_accepted(matrix.stale)
            node = GraphNode(
                identity=identity,
                kind=NodeKind.SYNTHESIS,
                authority=authority,
                label=matrix.name,
                text=" ".join((matrix.name, *matrix.fields)),
                source=source,
                fingerprint=ctx.digest(path),
                metadata=_meta(
                    taxonomy=matrix.taxonomy,
                    works=len(matrix.works),
                    fields=" / ".join(matrix.fields),
                    stale=matrix.stale.value,
                ),
            )
            edges = [
                GraphEdge(
                    from_id=identity,
                    to_id=str(work),
                    kind=EdgeKind.MENTIONED_IN,
                    origin=EdgeOrigin.ACCEPTED,
                    authority=authority,
                    source=source,
                )
                for work in matrix.works
            ]
            # A matrix cell is not a node, so the dependency projection's
            # `evidence -> cell -> matrix` chain is collapsed here rather than dropped.
            cited: set[str] = set()
            for cell in matrix.cells:
                for evidence_id in cell.evidence:
                    if str(evidence_id) in cited:
                        continue
                    cited.add(str(evidence_id))
                    edges.append(
                        GraphEdge(
                            from_id=identity,
                            to_id=str(evidence_id),
                            kind=EdgeKind.DEPENDS_ON,
                            origin=EdgeOrigin.STRUCTURAL,
                            authority=authority,
                            source=source,
                            metadata=_meta(field=cell.field, work=str(cell.work)),
                        )
                    )
            yield ProjectionUnit(
                source_key=source,
                fingerprint=ctx.digest(path),
                nodes=(node,),
                edges=tuple(edges),
            )


class ManuscriptProjector:
    """Manuscript source files, bibliography keys, and the anchors that bind them to Claims."""

    name = "manuscript"

    def project(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        yield from self._sources(ctx)
        anchors_file = ctx.layout.anchors_file
        if anchors_file.is_file():
            yield self._anchors(ctx, anchors_file)

    def _sources(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        directory = ctx.layout.manuscript_dir
        if not directory.is_dir():
            return
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _MANUSCRIPT_SUFFIXES:
                continue
            source = ctx.relative(path)
            fingerprint = ctx.digest(path)
            nodes: list[GraphNode] = [
                GraphNode(
                    identity=manuscript_file_identity(source),
                    kind=NodeKind.MANUSCRIPT_FILE,
                    label=path.name,
                    text=source,
                    source=source,
                    fingerprint=fingerprint,
                    metadata=_meta(suffix=path.suffix.lower()),
                )
            ]
            edges: list[GraphEdge] = []
            if path.suffix.lower() == _BIB_SUFFIX:
                for key, label in _bib_entries(path):
                    nodes.append(
                        GraphNode(
                            identity=citation_identity(key),
                            kind=NodeKind.CITATION,
                            label=key,
                            text=label,
                            source=source,
                            fingerprint=fingerprint,
                            metadata=_meta(key=key, origin="bibtex"),
                        )
                    )
                    edges.append(
                        GraphEdge(
                            from_id=manuscript_file_identity(source),
                            to_id=citation_identity(key),
                            kind=EdgeKind.CONTAINS,
                            origin=EdgeOrigin.STRUCTURAL,
                            authority=GraphAuthority.ACCEPTED,
                            source=source,
                            metadata=_meta(key=key),
                        )
                    )
            yield ProjectionUnit(
                source_key=source,
                fingerprint=fingerprint,
                nodes=tuple(nodes),
                edges=tuple(edges),
            )

    def _anchors(self, ctx: ProjectionContext, path: Path) -> ProjectionUnit:
        source = ctx.relative(path)
        fingerprint = ctx.digest(path)
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        files: set[str] = set()
        for anchor in ctx.anchors():
            identity = anchor_identity(anchor.file, anchor.sentence_fingerprint)
            authority = (
                GraphAuthority.STALE
                if anchor.stale is StaleState.STALE
                or anchor.status is not ManuscriptAnchorStatus.VALID
                else GraphAuthority.ACCEPTED
            )
            file_node = manuscript_file_identity(anchor.file)
            if anchor.file not in files:
                files.add(anchor.file)
                nodes.append(
                    GraphNode(
                        identity=file_node,
                        kind=NodeKind.MANUSCRIPT_FILE,
                        label=anchor.file.rsplit("/", 1)[-1],
                        text=anchor.file,
                        source=source,
                        fingerprint=fingerprint,
                    )
                )
            nodes.append(
                GraphNode(
                    identity=identity,
                    kind=NodeKind.MANUSCRIPT_ANCHOR,
                    authority=authority,
                    label=_clip(anchor.sentence),
                    text=anchor.sentence,
                    source=source,
                    fingerprint=anchor.sentence_fingerprint,
                    metadata=_meta(
                        file=anchor.file,
                        claim=str(anchor.claim),
                        line_start=anchor.line_start,
                        line_end=anchor.line_end,
                        status=anchor.status.value,
                        stale=anchor.stale.value,
                    ),
                )
            )
            edges.append(
                GraphEdge(
                    from_id=identity,
                    to_id=file_node,
                    kind=EdgeKind.ANCHORED_AT,
                    origin=EdgeOrigin.STRUCTURAL,
                    authority=authority,
                    status=anchor.status.value,
                    source=source,
                    metadata=_meta(
                        line_start=anchor.line_start,
                        line_end=anchor.line_end,
                        char_start=anchor.char_start,
                        char_end=anchor.char_end,
                    ),
                )
            )
            for key in anchor.citation_keys:
                edges.append(
                    GraphEdge(
                        from_id=identity,
                        to_id=citation_identity(key),
                        kind=EdgeKind.CITES,
                        origin=EdgeOrigin.RESEARCHER,
                        authority=authority,
                        source=source,
                        metadata=_meta(key=key),
                    )
                )
            edges.extend(
                _depends_on_edges(
                    ctx,
                    identity,
                    authority=authority,
                    source=source,
                    dependency_node=manuscript_anchor_key(anchor.file, anchor.sentence_fingerprint),
                )
            )
        return ProjectionUnit(
            source_key=source, fingerprint=fingerprint, nodes=tuple(nodes), edges=tuple(edges)
        )


class CandidateProjector:
    """Staged proposals under `.research/staging/`, always `model_proposed` and `candidate`.

    Two staging shapes are read: an evidence candidate (`staging/evidence/<work>/<id>.json`)
    and a claim audit report (`staging/claim_audit/<claim>/<run>.json`), whose
    `incomparable` entries are relation changes a model proposed and nobody has reviewed.
    Neither can produce an accepted edge; :class:`GraphEdge` refuses the combination.
    """

    name = "candidate"

    def project(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        yield from self._evidence_candidates(ctx)
        yield from self._relation_proposals(ctx)

    def _evidence_candidates(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        root = ctx.research_dir.joinpath(*_STAGING_EVIDENCE)
        if not root.is_dir():
            return
        for path in sorted(root.glob("*/cand_*.json")):
            payload = _read_json(path)
            if payload is None:
                continue
            unit = self._evidence_candidate(ctx, path, payload)
            if unit is not None:
                yield unit

    def _evidence_candidate(
        self, ctx: ProjectionContext, path: Path, payload: dict[str, Any]
    ) -> ProjectionUnit | None:
        candidate_id = str(payload.get("candidate_id") or "")
        evidence = payload.get("evidence")
        if not candidate_id or not isinstance(evidence, dict):
            logger.debug("skipping staged candidate without an evidence body: %s", path)
            return None
        anchor = evidence.get("source")
        content = evidence.get("content")
        if not isinstance(anchor, dict) or not isinstance(content, dict):
            logger.debug("skipping staged candidate without a source anchor: %s", path)
            return None
        source = ctx.relative(path)
        identity = candidate_identity(candidate_id)
        artifact = str(anchor.get("artifact") or "")
        block = str(anchor.get("block") or "")
        status = str(payload.get("status") or "proposed")
        text = str(content.get("exact_text") or "")
        node = GraphNode(
            identity=identity,
            kind=NodeKind.EVIDENCE,
            authority=GraphAuthority.CANDIDATE,
            label=_clip(text or candidate_id),
            text=text,
            source=source,
            fingerprint=ctx.digest(path),
            metadata=_meta(
                candidate_id=candidate_id,
                work=str(payload.get("work") or ""),
                artifact=artifact,
                block=block,
                field=str(payload.get("field") or ""),
                status=status,
                page=_as_int(anchor.get("page")),
            ),
        )
        edges: list[GraphEdge] = []
        if artifact and block:
            edges.append(
                GraphEdge(
                    from_id=identity,
                    to_id=block_identity(artifact, block),
                    kind=EdgeKind.ANCHORED_AT,
                    origin=EdgeOrigin.MODEL_PROPOSED,
                    authority=GraphAuthority.CANDIDATE,
                    status=status,
                    source=source,
                    metadata=_meta(page=_as_int(anchor.get("page")), block=block),
                )
            )
        if artifact:
            edges.append(
                GraphEdge(
                    from_id=identity,
                    to_id=artifact,
                    kind=EdgeKind.ANCHORED_AT,
                    origin=EdgeOrigin.MODEL_PROPOSED,
                    authority=GraphAuthority.CANDIDATE,
                    status=status,
                    source=source,
                    metadata=_meta(page=_as_int(anchor.get("page")), block=block),
                )
            )
        return ProjectionUnit(
            source_key=source,
            fingerprint=ctx.digest(path),
            nodes=(node,),
            edges=tuple(edges),
        )

    def _relation_proposals(self, ctx: ProjectionContext) -> Iterator[ProjectionUnit]:
        root = ctx.research_dir.joinpath(*_STAGING_CLAIM_AUDIT)
        if not root.is_dir():
            return
        for path in sorted(root.glob("*/*.json")):
            payload = _read_json(path)
            if payload is None:
                continue
            result = payload.get("result")
            if not isinstance(result, dict):
                continue
            claim = str(result.get("claim") or payload.get("claim") or "")
            proposals = result.get("incomparable")
            if not claim or not isinstance(proposals, list):
                continue
            source = ctx.relative(path)
            edges: list[GraphEdge] = []
            for entry in proposals:
                edge = _relation_proposal_edge(entry, claim=claim, source=source)
                if edge is not None:
                    edges.append(edge)
            if edges:
                yield ProjectionUnit(
                    source_key=source, fingerprint=ctx.digest(path), edges=tuple(edges)
                )


def _relation_proposal_edge(entry: object, *, claim: str, source: str) -> GraphEdge | None:
    """One `ProposedRelationChange` as a candidate edge, or ``None`` if it is not one."""
    if not isinstance(entry, dict):
        return None
    evidence = str(entry.get("evidence") or "")
    proposed = str(entry.get("proposed") or "")
    if not evidence or not proposed:
        return None
    try:
        relation = ClaimEvidenceRelationType(proposed)
    except ValueError:
        logger.debug("skipping staged relation proposal with unknown relation %r", proposed)
        return None
    kind = _RELATION_EDGE_KINDS.get(relation, EdgeKind.MENTIONED_IN)
    return GraphEdge(
        from_id=evidence,
        to_id=claim,
        kind=kind,
        origin=EdgeOrigin.MODEL_PROPOSED,
        authority=GraphAuthority.CANDIDATE,
        status="proposed",
        source=source,
        metadata=_meta(
            relation=relation.value,
            current=str(entry.get("current") or ""),
            note=_clip(str(entry.get("note") or "")),
        ),
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    """A staged JSON object, or ``None``; staging is regenerable and never fails a rebuild."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.debug("ignoring unreadable staged file %s", path)
        return None
    return payload if isinstance(payload, dict) else None


def _as_int(value: object) -> int | None:
    try:
        return None if value is None else int(str(value))
    except ValueError:
        return None


def _bib_entries(path: Path) -> list[tuple[str, str]]:
    """`(key, label)` for every BibTeX entry, or an empty list when the file is malformed."""
    from research_harness.manuscript.bibtex import BibtexError, parse_bibtex_file

    try:
        database = parse_bibtex_file(path)
    except (BibtexError, OSError, ValueError):
        logger.debug("ignoring unparseable bibliography %s", path)
        return []
    entries: list[tuple[str, str]] = []
    for key, entry in database.entries.items():
        label = " ".join(
            part
            for part in (entry.field("title"), entry.field("author"), entry.field("year"))
            if part
        )
        entries.append((key, _clip(label, 400)))
    return entries


# --- the registry -----------------------------------------------------------


def default_projectors() -> tuple[Projector, ...]:
    """Every projector a full rebuild runs, in containment order.

    Order matters only for readability of a dump: units are keyed by source, and the writer
    applies them independently.

    `SessionProjector` is imported here rather than at module scope because it builds on
    this module's context and unit types; the deferred import keeps the dependency in one
    direction.
    """
    from research_harness.graph.sessions import SessionProjector

    return (
        ProjectProjector(),
        SessionProjector(),
        CorpusProjector(),
        DocumentProjector(),
        EvidenceProjector(),
        ClaimProjector(),
        QuestionProjector(),
        DecisionProjector(),
        SynthesisProjector(),
        ManuscriptProjector(),
        CandidateProjector(),
    )


def project_all(
    ctx: ProjectionContext, projectors: Iterable[Projector] | None = None
) -> list[ProjectionUnit]:
    """Run every projector and return its units, deduplicated by source key.

    Two projectors that claim the same file would make the fingerprint ambiguous, so the
    first one wins and the collision is logged; in the shipped registry there are none.
    """
    selected = default_projectors() if projectors is None else tuple(projectors)
    units: dict[str, ProjectionUnit] = {}
    for projector in selected:
        for unit in projector.project(ctx):
            if unit.source_key in units:
                logger.warning(
                    "projector %s re-projects %s; keeping the first unit",
                    projector.name,
                    unit.source_key,
                )
                continue
            units[unit.source_key] = unit
    return [units[key] for key in sorted(units)]
