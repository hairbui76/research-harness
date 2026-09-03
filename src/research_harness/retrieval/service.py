"""The retrieval service: walk the ladder, stop as soon as it is answered, say what it used.

`RetrievalService.search` is the one entry point behind the `retrieval.search` capability.
It plans a query (`retrieval.planner`), executes the planned rungs in ladder order,
reranks what came back (`retrieval.rerank`), and returns a response that names every rung
it consulted and every one it skipped.

Two behaviours matter more than the plumbing:

* **Higher authority stops the walk.** Once the accepted rungs have produced ``k`` hits,
  the parsed corpus, the citation neighbourhood, and external discovery are not consulted
  at all. That is Product SS15.3 as executable behaviour, not as advice.
* **A missing index is a note, never an error.** Deleting the vector index costs recall
  and nothing else (ADR-006, Task 5.2): structured and lexical answers are unchanged, the
  response carries a note saying the index is not there, and no message ever suggests that
  the project's scientific state is incomplete.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field

from sqlalchemy.engine import Engine

from research_harness.citations.graph import CitationGraph
from research_harness.domain.base import Provenance
from research_harness.domain.claim import Claim
from research_harness.domain.document import DocumentBlock, ParsedDocument
from research_harness.domain.enums import DocumentBlockKind
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.ids import WorkId
from research_harness.domain.work import Artifact, Work
from research_harness.projection.fts import FtsKind
from research_harness.providers.models.embeddings import EmbeddingProvider
from research_harness.retrieval.lexical import LexicalHit, lexical_search
from research_harness.retrieval.planner import (
    QueryHints,
    RetrievalHit,
    RetrievalMode,
    RetrievalPlan,
    RetrievalResponse,
    plan_query,
)
from research_harness.retrieval.rerank import rerank
from research_harness.retrieval.semantic import IndexStats, SemanticHit, SemanticIndex
from research_harness.retrieval.structured import (
    Authority,
    Location,
    SourceRef,
    StructuredHit,
    StructuredQuery,
    resolve_source,
    structured_search,
    works_with_evidence,
)
from research_harness.retrieval.units import (
    IndexUnit,
    IndexUnitKind,
    unit_from_work,
    units_from_claim,
    units_from_document,
    units_from_evidence,
)
from research_harness.workspace.repository import WorkspaceRepository

__all__ = [
    "DEFAULT_FTS_KINDS",
    "SNIPPET_CHARS",
    "STORED_PARSER",
    "ModeResult",
    "RetrievalService",
    "build_semantic_index",
    "corpus_units",
]

logger = logging.getLogger(__name__)

SNIPPET_CHARS = 240
"""How much text travels with a hit. Enough to recognise it; the source is reopened with
`retrieval.resolve_source`, never read out of a result list."""

DEFAULT_FTS_KINDS: tuple[FtsKind, ...] = (
    FtsKind.BLOCK,
    FtsKind.EVIDENCE,
    FtsKind.CLAIM,
    FtsKind.WORK,
)
"""Lexical indexes searched by default. Notes are left out: a note is explicitly
low-authority and can never be cited as support (Product SS31), so it does not belong in a
result list a researcher reads as evidence."""

STORED_PARSER = "stored-blocks"
"""Parser identity of the transient `ParsedDocument` assembled from stored blocks. The
object exists for one function call and is never written; the real parse identity lives on
the canonical blocks it was built from."""

#: Parser block kinds mapped onto the retrieval-unit vocabulary used for ranking.
_BLOCK_KINDS: dict[str, str] = {
    DocumentBlockKind.PARAGRAPH.value: IndexUnitKind.PARAGRAPH.value,
    DocumentBlockKind.SECTION.value: IndexUnitKind.SECTION.value,
    DocumentBlockKind.TABLE.value: IndexUnitKind.TABLE.value,
    DocumentBlockKind.FIGURE_CAPTION.value: IndexUnitKind.CAPTION.value,
    DocumentBlockKind.TABLE_CAPTION.value: IndexUnitKind.CAPTION.value,
}

#: Authority of a lexical hit by index, before an evidence status lookup refines it.
_FTS_AUTHORITY: dict[FtsKind, Authority] = {
    FtsKind.BLOCK: Authority.PARSED_CORPUS,
    FtsKind.EVIDENCE: Authority.ACCEPTED_EVIDENCE,
    FtsKind.CLAIM: Authority.ACCEPTED_CLAIM,
    FtsKind.WORK: Authority.STRUCTURED_FIELD,
    FtsKind.NOTE: Authority.EXTERNAL_HINT,
}

#: Authority of a semantic hit by unit kind, before an evidence status lookup refines it.
_UNIT_AUTHORITY: dict[IndexUnitKind, Authority] = {
    IndexUnitKind.EVIDENCE: Authority.ACCEPTED_EVIDENCE,
    IndexUnitKind.CLAIM: Authority.ACCEPTED_CLAIM,
    IndexUnitKind.WORK: Authority.STRUCTURED_FIELD,
    IndexUnitKind.SECTION: Authority.PARSED_CORPUS,
    IndexUnitKind.PARAGRAPH: Authority.PARSED_CORPUS,
    IndexUnitKind.TABLE: Authority.PARSED_CORPUS,
    IndexUnitKind.CAPTION: Authority.PARSED_CORPUS,
}


@dataclass(frozen=True, slots=True)
class ModeResult:
    """What one rung produced: its hits, its remarks, and whether it actually ran."""

    hits: tuple[RetrievalHit, ...] = ()
    notes: tuple[str, ...] = ()
    ran: bool = True

    @property
    def empty(self) -> bool:
        return not self.hits


@dataclass
class _Walk:
    """Accumulator for one ladder walk."""

    hits: dict[str, RetrievalHit] = field(default_factory=dict)
    consulted: list[RetrievalMode] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, hit: RetrievalHit) -> None:
        existing = self.hits.get(hit.ref)
        self.hits[hit.ref] = hit if existing is None else existing.merged_with(hit)

    def above(self, rung: int) -> int:
        """How many hits already came from a rung stronger than ``rung``."""
        return sum(1 for hit in self.hits.values() if hit.authority.rung < rung)


class RetrievalService:
    """Local retrieval over one workspace: structured, lexical, semantic, citation graph."""

    def __init__(
        self,
        engine: Engine,
        repo: WorkspaceRepository,
        *,
        semantic: SemanticIndex | None = None,
        embedder: EmbeddingProvider | None = None,
        graph: CitationGraph | None = None,
    ) -> None:
        self._engine = engine
        self._repo = repo
        self._graph = graph
        self._embedder = embedder
        self._semantic = semantic
        if semantic is None and embedder is not None:
            self._semantic = SemanticIndex.open(repo.layout.index_dir, embedder)

    # -- reads ---------------------------------------------------------------

    @property
    def semantic(self) -> SemanticIndex | None:
        """The vector index, when one is configured; ``None`` degrades to lexical only."""
        return self._semantic

    def search(
        self,
        text: str,
        *,
        k: int = 10,
        hints: QueryHints | None = None,
        plan: RetrievalPlan | None = None,
    ) -> RetrievalResponse:
        """Plan ``text``, walk the ladder, and return the reranked hits with their sources."""
        resolved = plan if plan is not None else plan_query(text, hints=hints)
        walk = _Walk()
        for mode in resolved.modes:
            if walk.above(mode.rung) >= k:
                walk.notes.append(
                    f"{mode.value}: not consulted; {k} hits already came from a higher "
                    "rung of the authority ladder"
                )
                continue
            result = self._run(mode, resolved, k=k, walk=walk)
            walk.notes.extend(result.notes)
            if result.ran:
                walk.consulted.append(mode)
            for hit in result.hits:
                walk.add(hit)
        ranked = rerank(walk.hits.values(), intent=resolved.intent)[:k]
        return RetrievalResponse(
            query=text,
            plan=resolved,
            hits=tuple(ranked),
            rungs_consulted=tuple(walk.consulted),
            notes=tuple(dict.fromkeys(walk.notes)),
        )

    def search_semantic(
        self,
        text: str,
        *,
        k: int = 10,
        work: WorkId | None = None,
        kinds: Collection[IndexUnitKind] | None = None,
        exclude: Collection[str] = (),
    ) -> ModeResult:
        """Semantic neighbours of ``text``, or a note explaining why there are none.

        An absent, empty, or foreign vector index is a retrieval-performance fact and is
        reported as one: the note names the directory and the command that rebuilds it, and
        says explicitly that accepted state is unaffected (ADR-006).
        """
        index = self._semantic
        if index is None:
            return ModeResult(
                notes=(
                    "semantic search skipped: no embedding provider is configured for this "
                    "workspace. Structured and lexical answers are unaffected.",
                ),
                ran=False,
            )
        if index.needs_rebuild:
            return ModeResult(
                notes=(
                    f"semantic search skipped: no usable vector index at {index.directory}. "
                    "This costs recall on terminology-mismatch queries only - accepted "
                    "Evidence, Claims and exact-term search are unaffected. Run "
                    "`research index build` to restore it.",
                ),
                ran=False,
            )
        hits = index.query(text, k=k, kinds=kinds, work=work, exclude_ids=exclude)
        if not hits:
            return ModeResult(notes=("semantic search returned nothing above the index's floor.",))
        return ModeResult(hits=tuple(self._semantic_hits(hits)))

    def resolve_source(self, ref: str) -> SourceRef:
        """The exact page, block, character range, and geometry behind ``ref``."""
        return resolve_source(self._engine, ref)

    # -- rungs ---------------------------------------------------------------

    def _run(self, mode: RetrievalMode, plan: RetrievalPlan, *, k: int, walk: _Walk) -> ModeResult:
        if mode is RetrievalMode.STRUCTURED_ONLY:
            return self._structured(plan, k=k)
        if mode is RetrievalMode.FTS_SECTION:
            return self._lexical(plan, k=k)
        if mode is RetrievalMode.STRUCTURED_SEMANTIC:
            return self._structured_semantic(plan, k=k)
        if mode is RetrievalMode.CLAIM_GRAPH_SEMANTIC:
            return self._claim_graph(plan, k=k)
        if mode is RetrievalMode.CITATION_NEIGHBORHOOD:
            return self._neighborhood(plan, k=k, walk=walk)
        return ModeResult(
            notes=(
                "external_discovery: not run by local retrieval; discovery is the "
                "`corpus.search` capability and adds screening state, not retrieval hits.",
            ),
            ran=False,
        )

    def _structured(self, plan: RetrievalPlan, *, k: int) -> ModeResult:
        query = plan.structured
        hits: list[RetrievalHit] = []
        notes: list[str] = []
        if query is None:
            return ModeResult(
                notes=(
                    "structured_only: the query names no field this projection can filter "
                    "on, so nothing was looked up at this rung.",
                ),
                ran=False,
            )
        found = structured_search(self._engine, query.model_copy(update={"limit": max(k, 1)}))
        hits.extend(_structured_hit(hit, "structured") for hit in found)
        if plan.works_question and plan.identifiers:
            value = plan.identifiers[0]
            joined = works_with_evidence(self._engine, field="dataset", value=value, limit=k)
            hits.extend(_structured_hit(hit, "works_with_evidence") for hit in joined)
            if not joined:
                notes.append(
                    f"no Work has accepted Evidence recording dataset {value!r}; this is "
                    "'not found in accepted state', not 'no such work exists'."
                )
        return ModeResult(hits=tuple(hits), notes=tuple(notes))

    def _lexical(self, plan: RetrievalPlan, *, k: int) -> ModeResult:
        if not plan.terms:
            return ModeResult(
                notes=("fts_section: the query carries no searchable term.",), ran=False
            )
        found = lexical_search(
            self._engine,
            plan.terms,
            kinds=DEFAULT_FTS_KINDS,
            work=plan.work,
            section_prefix=plan.sections or None,
            synonyms=plan.synonyms,
            limit=max(k, 1),
        )
        notes: list[str] = []
        if not found and plan.sections:
            notes.append(
                "no exact match inside " + "/".join(plan.sections) + "; the constraint was "
                "kept rather than widened, so this is an absence in those sections only."
            )
        return ModeResult(hits=tuple(self._lexical_hits(found)), notes=tuple(notes))

    def _structured_semantic(self, plan: RetrievalPlan, *, k: int) -> ModeResult:
        query = plan.semantic_query or plan.text
        result = self.search_semantic(query, k=k, work=plan.work)
        return ModeResult(hits=result.hits, notes=result.notes, ran=result.ran)

    def _claim_graph(self, plan: RetrievalPlan, *, k: int) -> ModeResult:
        if plan.claim is None:
            return ModeResult(notes=("claim_graph_semantic: the query names no Claim.",), ran=False)
        try:
            claim = self._repo.get_claim(plan.claim)
        except ResearchHarnessError as exc:
            return ModeResult(notes=(f"claim_graph_semantic: {exc}",), ran=False)
        hits = list(self.claim_relations(claim))
        semantic = self.search_semantic(claim.statement, k=k)
        return ModeResult(hits=(*hits, *semantic.hits), notes=semantic.notes)

    def _neighborhood(self, plan: RetrievalPlan, *, k: int, walk: _Walk) -> ModeResult:
        if self._graph is None:
            return ModeResult(
                notes=(
                    "citation_neighborhood: no citation graph is loaded for this "
                    "workspace; corpus answers above are unaffected.",
                ),
                ran=False,
            )
        seeds = {hit.work for hit in walk.hits.values() if hit.work is not None}
        if plan.work is not None:
            seeds.add(plan.work)
        if not seeds:
            return ModeResult(
                notes=("citation_neighborhood: nothing to expand from yet.",), ran=False
            )
        corpus = {str(work.id): work for work in self._repo.list_works()}
        neighbours: list[str] = []
        for seed in sorted(str(work) for work in seeds):
            for key in (
                *self._graph.predecessors(seed),
                *self._graph.successors(seed),
            ):
                if key in corpus and key not in seeds and key not in neighbours:
                    neighbours.append(key)
        hits = [
            RetrievalHit(
                ref=key,
                kind="work",
                work=WorkId(key),
                authority=Authority.CITATION_NEIGHBORHOOD,
                snippet=corpus[key].title[:SNIPPET_CHARS],
                provenance="citation_neighborhood",
            )
            for key in neighbours[:k]
        ]
        return ModeResult(hits=tuple(hits))

    # -- building blocks other application code reuses ------------------------

    def claim_relations(
        self, claim: Claim, *, relations: Collection[str] | None = None
    ) -> list[RetrievalHit]:
        """The Evidence a Claim already records, as hits, in relation order.

        This is the top of the ladder for any claim question: the project has already
        decided what supports, contradicts, and qualifies this claim, and that record
        outranks anything an index can find (Product SS10.4, SS15.3).
        """
        wanted = [
            link
            for link in claim.relations
            if relations is None or link.relation.value in relations
        ]
        if not wanted:
            return []
        ids = [str(link.evidence) for link in wanted]
        rows = {
            hit.object_id: hit
            for hit in structured_search(
                self._engine,
                StructuredQuery(entity="evidence", filters={"id": ids}, limit=len(ids)),
            )
        }
        hits: list[RetrievalHit] = []
        for link in wanted:
            row = rows.get(str(link.evidence))
            if row is None:
                continue
            hits.append(_structured_hit(row, f"claim_graph:{link.relation.value}"))
        return hits

    def lexical(
        self,
        terms: str,
        *,
        kinds: Sequence[FtsKind] | None = None,
        work: WorkId | None = None,
        section_prefix: str | Sequence[str] | None = None,
        limit: int = 10,
    ) -> list[RetrievalHit]:
        """Lexical search as retrieval hits, with authority resolved from the projection."""
        found = lexical_search(
            self._engine,
            terms,
            kinds=kinds if kinds is not None else DEFAULT_FTS_KINDS,
            work=work,
            section_prefix=section_prefix,
            limit=limit,
        )
        return list(self._lexical_hits(found))

    def structured(self, query: StructuredQuery) -> list[RetrievalHit]:
        """Structured lookup as retrieval hits."""
        found = structured_search(self._engine, query)
        return [_structured_hit(hit, "structured") for hit in found]

    # -- conversions ---------------------------------------------------------

    def _lexical_hits(self, hits: Sequence[LexicalHit]) -> list[RetrievalHit]:
        blocks = self._block_rows([hit.object_id for hit in hits if hit.kind is FtsKind.BLOCK])
        states = self._object_states(
            [hit.object_id for hit in hits if hit.kind in (FtsKind.EVIDENCE, FtsKind.CLAIM)]
        )
        built: list[RetrievalHit] = []
        for hit in hits:
            ref = hit.object_id
            kind = hit.kind.value
            location = hit.location
            authority = _FTS_AUTHORITY[hit.kind]
            stale = False
            if hit.kind is FtsKind.BLOCK:
                row = blocks.get(hit.object_id)
                if row is None or _is_heading(row):
                    continue
                ref, kind, location = row.object_id, _block_kind(row), row.location
            elif hit.object_id in states:
                authority, stale = states[hit.object_id]
            built.append(
                RetrievalHit(
                    ref=ref,
                    kind=kind,
                    work=hit.work,
                    location=location,
                    authority=authority,
                    components={"lexical": hit.score},
                    snippet=_collapsed(hit.snippet),
                    provenance=f"fts:{hit.kind.value}" + ("" if hit.exact else f"~{hit.via}"),
                    stale=stale,
                )
            )
        return built

    def _semantic_hits(self, hits: Sequence[SemanticHit]) -> list[RetrievalHit]:
        states = self._object_states(
            [
                hit.unit.id
                for hit in hits
                if hit.unit.kind in (IndexUnitKind.EVIDENCE, IndexUnitKind.CLAIM)
            ]
        )
        built: list[RetrievalHit] = []
        for hit in hits:
            unit = hit.unit
            authority = _UNIT_AUTHORITY[unit.kind]
            stale = False
            if unit.id in states:
                authority, stale = states[unit.id]
            built.append(
                RetrievalHit(
                    ref=unit.id,
                    kind=unit.kind.value,
                    work=unit.work,
                    location=Location(page=unit.page, section_path=unit.section_path),
                    authority=authority,
                    components={"semantic": max(0.0, hit.score)},
                    snippet=_collapsed(unit.preview),
                    provenance="semantic",
                    stale=stale,
                )
            )
        return built

    def _block_rows(self, ids: Sequence[str]) -> dict[str, StructuredHit]:
        """Projected block rows by bare block id; a block ref needs its artifact."""
        unique = list(dict.fromkeys(ids))
        if not unique:
            return {}
        rows = structured_search(
            self._engine,
            StructuredQuery(entity="block", filters={"id": unique}, limit=len(unique)),
        )
        return {str(row.location.block): row for row in rows if row.location.block is not None}

    def _object_states(self, ids: Sequence[str]) -> dict[str, tuple[Authority, bool]]:
        """Authority and staleness for Evidence and Claim ids, read from the projection."""
        evidence = [ref for ref in dict.fromkeys(ids) if ref.startswith("E")]
        claims = [ref for ref in dict.fromkeys(ids) if ref.startswith("C")]
        states: dict[str, tuple[Authority, bool]] = {}
        for entity, refs in (("evidence", evidence), ("claim", claims)):
            if not refs:
                continue
            for row in structured_search(
                self._engine,
                StructuredQuery(entity=entity, filters={"id": refs}, limit=len(refs)),  # type: ignore[arg-type]
            ):
                states[row.object_id] = (row.authority, row.stale)
        return states


# ------------------------------------------------------------------- conversions


def _structured_hit(hit: StructuredHit, provenance: str) -> RetrievalHit:
    return RetrievalHit(
        ref=hit.object_id,
        kind=_block_kind(hit) if hit.entity == "block" else hit.entity,
        work=hit.work,
        location=hit.location,
        authority=hit.authority,
        components={},
        snippet=_collapsed(hit.snippet),
        provenance=f"{provenance}:{hit.entity}",
        stale=hit.stale,
    )


def _block_kind(hit: StructuredHit) -> str:
    """A block's parsed kind in the retrieval-unit vocabulary, for structure scoring."""
    kind = hit.fields.get("kind", "")
    return _BLOCK_KINDS.get(kind, kind or "block")


def _is_heading(hit: StructuredHit) -> bool:
    """A section block holds only its heading, so a lexical match on it answers nothing.

    "5 Limitations" matches the term `limitations` perfectly and says nothing about the
    paper; the paragraphs beneath the heading are the content, and they are indexed
    separately. A researcher who wants the section itself asks for it structurally
    (`StructuredQuery(entity="block", filters={"section_prefix": ...})`), which is the same
    reason `retrieval.units` indexes a section as heading-plus-body rather than as a
    heading on its own.
    """
    return hit.fields.get("kind", "") == DocumentBlockKind.SECTION.value


def _collapsed(text: str) -> str:
    """Snippet text on one line, trimmed to `SNIPPET_CHARS`; a result list is a list."""
    return " ".join(text.split())[:SNIPPET_CHARS]


# ------------------------------------------------------------------ index building


def corpus_units(repo: WorkspaceRepository) -> list[IndexUnit]:
    """Every retrieval unit this workspace contributes, in corpus order.

    Work cards, then the parsed blocks of each artifact, then accepted and candidate
    Evidence, then Claims (Product SS15.4). Nothing here reads the projection: the index is
    built from canonical state, so a rebuilt index and a rebuilt projection cannot drift
    apart.
    """
    units: list[IndexUnit] = []
    for work in repo.list_works():
        units.append(unit_from_work(work))
        for document in repo.iter_parsed_documents(work.id):
            units.extend(units_from_document(document))
        for evidence in repo.iter_evidence(work.id):
            units.extend(units_from_evidence(evidence))
    for claim in repo.list_claims():
        units.extend(units_from_claim(claim))
    return units


def build_semantic_index(
    repo: WorkspaceRepository,
    embedder: EmbeddingProvider,
    *,
    rebuild: bool = True,
) -> IndexStats:
    """Build or refresh the vector index under `.research/index/semantic/`.

    ``rebuild`` re-embeds everything, which is also what happens when the stored index is
    absent or was written by another provider. Incremental mode re-embeds only changed
    units and therefore cannot notice a unit that disappeared, so a corpus that lost
    documents wants a full rebuild - cheap, because the index is disposable by design.
    """
    index = SemanticIndex.open(repo.layout.index_dir, embedder)
    units = corpus_units(repo)
    if rebuild or index.needs_rebuild:
        index.rebuild(units)
    else:
        index.upsert(units)
    return index.stats()


def _stored_document(
    work: Work, artifact: Artifact, blocks: Sequence[DocumentBlock]
) -> ParsedDocument:
    """Wrap stored blocks so `units_from_document` can aggregate sections from them.

    `WorkspaceRepository.get_parsed_document` is the reconstruction the index now uses;
    this stays for a caller that already holds the blocks and does not want to read them
    again. Either way the object lives for one call, is never written, and carries a
    placeholder parser identity rather than a claim about who parsed the artifact.
    """
    return ParsedDocument(
        work=work.id,
        version=artifact.version,
        artifact=artifact.id,
        file_hash=artifact.file_hash,
        parser_name=STORED_PARSER,
        parser_version=str(artifact.schema_version),
        page_count=max((block.page for block in blocks), default=0),
        blocks=tuple(blocks),
        provenance=Provenance.system(),
    )
