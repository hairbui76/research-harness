"""Local retrieval over the disposable projections under `.research/` (Product SS15).

Retrieval is deliberately not the knowledge model: an index answers "where might this be
written down", and accepted Evidence and Claims answer "what does this project hold to be
true" (SS15.3, ADR-006). Everything in this package is regenerable from canonical state,
and a retrieval chunk is an implementation artifact, not a research object (SS15.4).

The pieces, lowest first:

* `units` and `semantic` — what gets indexed, and the disposable vector index over it.
* `structured` — lookups and joins over the SQLite projection, plus `resolve_source`.
* `lexical` — exact terminology over FTS5, with section constraints and synonyms.
* `planner` — query classification, the authority ladder, and the hit vocabulary.
* `rerank` — research-utility ranking with explicit, inspectable components.
* `service` — `RetrievalService`, the ladder walk behind `retrieval.search`.
* `counter` — counter-evidence search for a claim audit; proposals only.
"""

from __future__ import annotations

from research_harness.retrieval.counter import (
    COUNTER_RELATIONS,
    NEGATION_CUES,
    RetrievalCounterEvidenceFinder,
    counter_terms,
    plan_counter_evidence,
)
from research_harness.retrieval.lexical import (
    CONCLUSION_SECTIONS,
    LEXICAL_FLOOR,
    RESULT_SECTIONS,
    LexicalHit,
    SynonymTable,
    lexical_search,
)
from research_harness.retrieval.planner import (
    LADDER,
    METRIC_WORDS,
    STOP_WORDS,
    Intent,
    QueryHints,
    RetrievalHit,
    RetrievalMode,
    RetrievalPlan,
    RetrievalResponse,
    identifiers,
    infer_intent,
    plan_query,
    search_terms,
)
from research_harness.retrieval.rerank import (
    AUTHORITY_SCORES,
    RERANK_WEIGHTS,
    RerankWeights,
    authority_score,
    rerank,
    structure_score,
)
from research_harness.retrieval.semantic import (
    INDEX_VERSION,
    META_FILENAME,
    PREVIEW_CHARS,
    SEMANTIC_DIRNAME,
    UNITS_FILENAME,
    VECTORS_FILENAME,
    IndexedUnit,
    IndexMeta,
    IndexStats,
    SemanticHit,
    SemanticIndex,
    fingerprint_slug,
    semantic_index_dir,
)
from research_harness.retrieval.service import (
    DEFAULT_FTS_KINDS,
    ModeResult,
    RetrievalService,
    build_semantic_index,
    corpus_units,
)
from research_harness.retrieval.structured import (
    AUTHORITY_RUNGS,
    STRUCTURED_ENTITIES,
    Authority,
    Location,
    SourceRef,
    StructuredEntity,
    StructuredHit,
    StructuredQuery,
    block_ref,
    filters_for,
    normalize_section,
    resolve_source,
    section_matches,
    structured_search,
    works_with_evidence,
)
from research_harness.retrieval.units import (
    MAX_SECTION_CHARS,
    IndexUnit,
    IndexUnitKind,
    block_unit_id,
    unit_from_work,
    units_from_claim,
    units_from_document,
    units_from_evidence,
)

__all__ = [
    "AUTHORITY_RUNGS",
    "AUTHORITY_SCORES",
    "CONCLUSION_SECTIONS",
    "COUNTER_RELATIONS",
    "DEFAULT_FTS_KINDS",
    "INDEX_VERSION",
    "LADDER",
    "LEXICAL_FLOOR",
    "MAX_SECTION_CHARS",
    "META_FILENAME",
    "METRIC_WORDS",
    "NEGATION_CUES",
    "PREVIEW_CHARS",
    "RERANK_WEIGHTS",
    "RESULT_SECTIONS",
    "SEMANTIC_DIRNAME",
    "STOP_WORDS",
    "STRUCTURED_ENTITIES",
    "UNITS_FILENAME",
    "VECTORS_FILENAME",
    "Authority",
    "IndexMeta",
    "IndexStats",
    "IndexUnit",
    "IndexUnitKind",
    "IndexedUnit",
    "Intent",
    "LexicalHit",
    "Location",
    "ModeResult",
    "QueryHints",
    "RerankWeights",
    "RetrievalCounterEvidenceFinder",
    "RetrievalHit",
    "RetrievalMode",
    "RetrievalPlan",
    "RetrievalResponse",
    "RetrievalService",
    "SemanticHit",
    "SemanticIndex",
    "SourceRef",
    "StructuredEntity",
    "StructuredHit",
    "StructuredQuery",
    "SynonymTable",
    "authority_score",
    "block_ref",
    "block_unit_id",
    "build_semantic_index",
    "corpus_units",
    "counter_terms",
    "filters_for",
    "fingerprint_slug",
    "identifiers",
    "infer_intent",
    "lexical_search",
    "normalize_section",
    "plan_counter_evidence",
    "plan_query",
    "rerank",
    "resolve_source",
    "search_terms",
    "section_matches",
    "semantic_index_dir",
    "structure_score",
    "structured_search",
    "unit_from_work",
    "units_from_claim",
    "units_from_document",
    "units_from_evidence",
    "works_with_evidence",
]
