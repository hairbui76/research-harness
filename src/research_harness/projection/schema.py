"""SQLAlchemy Core tables for the deletable SQLite projection of canonical state.

Nothing here has scientific authority (PRODUCT 8.2, ADR-001). Every table is a
regenerable index over the canonical YAML/JSONL files, and no row in this database is
ever read back as scientific truth: deleting ``.research/`` and rebuilding must
reproduce these tables exactly, so a value that exists only here is a bug.

The schema is Core-only (no ORM), primary keys are the canonical string IDs verbatim,
and every nested collection is stored as JSON text rather than as a second normalized
table, so that a projected row stays a faithful, diff-free echo of its canonical object.

Foreign keys are declared for structural containment only - Version/Artifact/Block/
TableCell/MatrixCell/TaxonomyTerm/claim links - because those relationships cannot be
valid without their parent. References that may legitimately dangle in a partially
rebuilt projection (Evidence to its Work/Version/Artifact/Block, claim-evidence to
Evidence, dependency and stale-mark node ids) are indexed columns without constraints:
a dangling reference is an audit finding for the rebuild and manuscript audit tasks, not
an insert failure that would abort a rebuild.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL
from sqlalchemy.exc import DatabaseError

from research_harness.domain.errors import ProjectionError

__all__ = [
    "ARTIFACTS",
    "BLOCKS",
    "CLAIMS",
    "CLAIM_DECISIONS",
    "CLAIM_EVIDENCE",
    "DECISIONS",
    "DEPENDENCIES",
    "EVENTS",
    "EVIDENCE",
    "INTERPRETATIONS",
    "MANUSCRIPT_ANCHORS",
    "MATRICES",
    "MATRIX_CELLS",
    "METADATA",
    "NOTES",
    "PROJECTION_META",
    "PROJECTION_META_ID",
    "PROJECTION_SCHEMA_VERSION",
    "QUESTIONS",
    "QUESTION_LINKS",
    "SEARCH_CANDIDATES",
    "SEARCH_RUNS",
    "STALE_MARKS",
    "TABLES",
    "TABLE_CELLS",
    "TAXONOMIES",
    "TAXONOMY_TERMS",
    "VERSIONS",
    "WORKS",
    "assert_fts5_available",
    "create_all",
    "create_engine_for",
    "drop_all",
    "table_for",
]

PROJECTION_SCHEMA_VERSION = 2
"""Bumped whenever these tables change shape; a mismatch forces a full rebuild."""

PROJECTION_META_ID = "projection"
"""Primary key of the single :data:`PROJECTION_META` row."""

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}

METADATA = MetaData(naming_convention=NAMING_CONVENTION)


def _tracked() -> list[Column[Any]]:
    """Columns every canonical/tracked object carries (conventions: canonical serialization)."""
    return [
        Column("schema_version", Integer, nullable=False),
        Column("created_at", String, nullable=False),
        Column("updated_at", String, nullable=False),
        Column("provenance", Text, nullable=False),
    ]


# --- corpus identity --------------------------------------------------------

WORKS = Table(
    "works",
    METADATA,
    Column("id", String, primary_key=True),
    Column("title", Text, nullable=False),
    Column("authors", Text, nullable=False),
    Column("year", Integer),
    Column("venue", Text),
    Column("identifiers", Text, nullable=False),
    Column("screening", String, nullable=False),
    Column("exclusion_reason", Text),
    Column("versions", Text, nullable=False),
    Column("artifacts", Text, nullable=False),
    *_tracked(),
)

VERSIONS = Table(
    "versions",
    METADATA,
    Column("id", String, primary_key=True),
    Column("work", String, ForeignKey("works.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String, nullable=False),
    Column("label", Text),
    Column("date", String),
    Column("identifiers", Text, nullable=False),
    *_tracked(),
)

ARTIFACTS = Table(
    "artifacts",
    METADATA,
    Column("id", String, primary_key=True),
    Column("work", String, ForeignKey("works.id", ondelete="CASCADE"), nullable=False),
    Column("version", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String, nullable=False),
    Column("file_hash", String, nullable=False),
    Column("original_filename", Text, nullable=False),
    Column("mime_type", String, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("ingested_at", String, nullable=False),
    *_tracked(),
)

# --- parsed document IR -----------------------------------------------------

BLOCKS = Table(
    "blocks",
    METADATA,
    Column("artifact", String, ForeignKey("artifacts.id", ondelete="CASCADE"), primary_key=True),
    Column("id", String, primary_key=True),
    Column("work", String, nullable=False),
    Column("version", String, nullable=False),
    # Filled when the block is projected as part of its `ParsedDocument`, which is the
    # only object that knows which artifact bytes the parse read.
    Column("file_hash", String),
    Column("kind", String, nullable=False),
    Column("page", Integer, nullable=False),
    Column("order", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("text_hash", String, nullable=False),
    Column("section_path", Text, nullable=False),
    Column("bbox", Text),
    Column("caption", Text),
    Column("caption_for", String),
    Column("reference_key", Text),
    Column("reference_raw", Text),
    *_tracked(),
)

TABLE_CELLS = Table(
    "table_cells",
    METADATA,
    Column("artifact", String, primary_key=True),
    Column("block", String, primary_key=True),
    Column("row", Integer, primary_key=True),
    Column("col", Integer, primary_key=True),
    Column("text", Text, nullable=False),
    Column("bbox", Text),
    ForeignKeyConstraint(
        ["artifact", "block"], ["blocks.artifact", "blocks.id"], ondelete="CASCADE"
    ),
)

# --- evidence ---------------------------------------------------------------

EVIDENCE = Table(
    "evidence",
    METADATA,
    Column("id", String, primary_key=True),
    # source anchor
    Column("work", String, nullable=False),
    Column("version", String, nullable=False),
    Column("artifact", String, nullable=False),
    Column("file_hash", String, nullable=False),
    Column("page", Integer),
    Column("block", String, nullable=False),
    Column("text_hash", String, nullable=False),
    Column("section_path", Text, nullable=False),
    Column("char_start", Integer),
    Column("char_end", Integer),
    Column("bbox", Text),
    # epistemic classification
    Column("origin", String, nullable=False),
    Column("evidence_type", String, nullable=False),
    Column("strength", String, nullable=False),
    Column("stale", String, nullable=False),
    Column("review_tier", Integer, nullable=False),
    Column("qualification", Text),
    Column("decisions", Text, nullable=False),
    # content
    Column("exact_text", Text, nullable=False),
    Column("negative_state", String),
    Column("field", Text),
    # flattened numeric value
    Column("metric", Text),
    Column("dataset", Text),
    Column("unit", Text),
    Column("numeric_value", Float),
    Column("numeric_raw", Text),
    Column("numeric_condition", Text),
    Column("numeric_source_table", Text),
    Column("numeric_source_row", Text),
    Column("numeric_source_column", Text),
    # verification record
    Column("status", String, nullable=False),
    Column("verdict", String),
    Column("extractor", Text),
    Column("verifier", Text),
    Column("accepted_by", Text),
    Column("review_action", String),
    Column("rationale", Text),
    Column("reviewed_at", String),
    *_tracked(),
)

INTERPRETATIONS = Table(
    "interpretations",
    METADATA,
    Column("id", String, primary_key=True),
    Column("evidence", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("origin", String, nullable=False),
    Column("stale", String, nullable=False),
    Column("review_tier", Integer, nullable=False),
    Column("qualification", Text),
    Column("status", String, nullable=False),
    Column("verdict", String),
    Column("extractor", Text),
    Column("verifier", Text),
    Column("accepted_by", Text),
    Column("review_action", String),
    Column("rationale", Text),
    Column("reviewed_at", String),
    *_tracked(),
)

# --- claims -----------------------------------------------------------------

CLAIMS = Table(
    "claims",
    METADATA,
    Column("id", String, primary_key=True),
    Column("statement", Text, nullable=False),
    Column("type", String, nullable=False),
    Column("semantics_subject", Text, nullable=False),
    Column("semantics_predicate", Text, nullable=False),
    Column("semantics_object", Text, nullable=False),
    Column("semantics_qualifier", Text, nullable=False),
    Column("scope_level", String, nullable=False),
    Column("corpus", Text),
    Column("publication_until", String),
    Column("status", String, nullable=False),
    Column("requested_strength", String, nullable=False),
    Column("allowed_strength", String, nullable=False),
    Column("maximum_defensible_wording", Text),
    Column("audited_at", String),
    Column("stale", String, nullable=False),
    Column("relevant_works", Integer, nullable=False),
    Column("examined_works", Integer, nullable=False),
    Column("unresolved_works", Integer, nullable=False),
    Column("overturn_risk", String, nullable=False),
    Column("coverage_cutoff", String),
    Column("coverage_search_runs", Text, nullable=False),
    Column("derived_from", Text, nullable=False),
    *_tracked(),
)

CLAIM_EVIDENCE = Table(
    "claim_evidence",
    METADATA,
    Column("claim", String, ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("evidence", String, nullable=False),
    Column("relation", String, nullable=False),
    Column("aspect", Text),
    Column("note", Text),
)

CLAIM_DECISIONS = Table(
    "claim_decisions",
    METADATA,
    Column("claim", String, ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True),
    Column("decision", String, primary_key=True),
    Column("ordinal", Integer, nullable=False),
)

# --- decisions, questions, taxonomy, search ---------------------------------

DECISIONS = Table(
    "decisions",
    METADATA,
    Column("id", String, primary_key=True),
    Column("type", String, nullable=False),
    Column("status", String, nullable=False),
    Column("title", Text),
    Column("rationale", Text, nullable=False),
    Column("claim", String),
    Column("auditor_recommendation", String),
    Column("researcher_selected", String),
    Column("taxonomy_terms", Text, nullable=False),
    Column("supersedes", String),
    *_tracked(),
)

QUESTIONS = Table(
    "questions",
    METADATA,
    Column("id", String, primary_key=True),
    Column("question", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("remaining_uncertainty", Text),
    Column("stale", String, nullable=False),
    *_tracked(),
)

QUESTION_LINKS = Table(
    "question_links",
    METADATA,
    Column("question", String, ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True),
    Column("kind", String, primary_key=True),
    Column("target", String, primary_key=True),
    Column("ordinal", Integer, nullable=False),
)

TAXONOMIES = Table(
    "taxonomies",
    METADATA,
    Column("name", String, primary_key=True),
    Column("node_id", String, nullable=False, unique=True),
    *_tracked(),
)

TAXONOMY_TERMS = Table(
    "taxonomy_terms",
    METADATA,
    Column("taxonomy", String, ForeignKey("taxonomies.name", ondelete="CASCADE"), primary_key=True),
    Column("term", String, primary_key=True),
    Column("parent", String),
    Column("definition", Text),
    Column("decision", String),
    Column("ordinal", Integer, nullable=False),
)

SEARCH_RUNS = Table(
    "search_runs",
    METADATA,
    Column("id", String, primary_key=True),
    Column("question", Text, nullable=False),
    Column("research_question", String),
    Column("sources", Text, nullable=False),
    Column("queries", Text, nullable=False),
    Column("filters", Text, nullable=False),
    Column("discovered", Integer, nullable=False),
    Column("screened", Integer, nullable=False),
    Column("included", Integer, nullable=False),
    Column("executed_at", String, nullable=False),
    Column("cutoff", String),
    Column("cursors", Text, nullable=False),
    Column("failures", Text, nullable=False),
    Column("unresolved_identities", Text, nullable=False),
    Column("unavailable_full_text", Text, nullable=False),
    Column("unresolved_keys", Text, nullable=False),
    Column("full_text_unavailable_keys", Text, nullable=False),
    Column("reproduces", String),
    *_tracked(),
)

SEARCH_CANDIDATES = Table(
    "search_candidates",
    METADATA,
    Column("run", String, ForeignKey("search_runs.id", ondelete="CASCADE"), primary_key=True),
    Column("key", String, primary_key=True),
    Column("ordinal", Integer, nullable=False),
    Column("sources", Text, nullable=False),
    Column("ranks", Text, nullable=False),
    Column("screening", String, nullable=False),
    Column("exclusion_reason", Text),
    Column("screened_by", Text),
    Column("screened_at", String),
    Column("identity", String),
    Column("matched_work", String),
    # 0/1/NULL: SQLite has no boolean, and NULL is the honest "nobody checked yet".
    Column("full_text_available", Integer),
    Column("title", Text),
    Column("year", Integer),
    Column("doi", Text),
    Column("arxiv", Text),
    Column("source_query", Text),
    # The staged candidate verbatim; a discovery record has no canonical id to join on.
    Column("candidate", Text, nullable=False),
)

# --- synthesis, notes, manuscript, events -----------------------------------

MATRICES = Table(
    "matrices",
    METADATA,
    Column("id", String, primary_key=True),
    Column("name", Text, nullable=False),
    Column("taxonomy", String),
    Column("works", Text, nullable=False),
    Column("fields", Text, nullable=False),
    Column("stale", String, nullable=False),
    *_tracked(),
)

MATRIX_CELLS = Table(
    "matrix_cells",
    METADATA,
    Column("matrix", String, ForeignKey("matrices.id", ondelete="CASCADE"), primary_key=True),
    Column("work", String, primary_key=True),
    Column("field", String, primary_key=True),
    Column("cell_id", String, nullable=False, unique=True),
    Column("labels", Text, nullable=False),
    Column("evidence", Text, nullable=False),
)

NOTES = Table(
    "notes",
    METADATA,
    Column("note_key", String, primary_key=True),
    Column("key", Text),
    Column("text", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("promoted_to", String),
    *_tracked(),
)

MANUSCRIPT_ANCHORS = Table(
    "manuscript_anchors",
    METADATA,
    Column("file", String, primary_key=True),
    Column("sentence_fingerprint", String, primary_key=True),
    Column("anchor_id", String, nullable=False, unique=True),
    Column("line_start", Integer, nullable=False),
    Column("line_end", Integer, nullable=False),
    Column("char_start", Integer, nullable=False),
    Column("char_end", Integer, nullable=False),
    Column("sentence", Text, nullable=False),
    Column("claim", String, nullable=False),
    Column("citation_keys", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("stale", String, nullable=False),
    *_tracked(),
)

EVENTS = Table(
    "events",
    METADATA,
    Column("event_id", String, primary_key=True),
    Column("event", String, nullable=False),
    Column("actor", Text, nullable=False),
    Column("occurred_at", String, nullable=False),
    Column("summary", Text, nullable=False),
    Column("subjects", Text, nullable=False),
    Column("payload", Text, nullable=False),
    Column("objects", Text, nullable=False),
    Column("schema_version", Integer, nullable=False),
)

# --- dependency graph and staleness -----------------------------------------

DEPENDENCIES = Table(
    "dependencies",
    METADATA,
    Column("upstream_id", String, primary_key=True),
    Column("downstream_id", String, primary_key=True),
    Column("kind", String, primary_key=True),
)

STALE_MARKS = Table(
    "stale_marks",
    METADATA,
    Column("object_id", String, primary_key=True),
    Column("source_change_id", String, primary_key=True),
    Column("reason", Text, nullable=False),
    Column("since", String, nullable=False),
    Column("priority", Integer, nullable=False),
)

# --- projection metadata ----------------------------------------------------

PROJECTION_META = Table(
    "projection_meta",
    METADATA,
    Column("id", String, primary_key=True),
    Column("schema_version", Integer, nullable=False),
    Column("built_at", String, nullable=False),
    Column("canonical_digest", String),
    # slots filled by later phases; never canonical state (ADR-006)
    Column("parser_name", String),
    Column("parser_version", String),
    Column("fts_version", String),
    Column("embedding_provider", String),
    Column("embedding_model", String),
    Column("embedding_dimensions", Integer),
)

# --- indexes for the obvious lookups ---------------------------------------

Index("ix_works_screening", WORKS.c.screening)
Index("ix_versions_work", VERSIONS.c.work)
Index("ix_artifacts_work", ARTIFACTS.c.work)
Index("ix_artifacts_version", ARTIFACTS.c.version)
Index("ix_artifacts_file_hash", ARTIFACTS.c.file_hash)
Index("ix_blocks_work", BLOCKS.c.work)
Index("ix_blocks_kind", BLOCKS.c.kind)
Index("ix_blocks_text_hash", BLOCKS.c.text_hash)
Index("ix_evidence_work", EVIDENCE.c.work)
Index("ix_evidence_artifact", EVIDENCE.c.artifact)
Index("ix_evidence_block", EVIDENCE.c.block)
Index("ix_evidence_status", EVIDENCE.c.status)
Index("ix_evidence_stale", EVIDENCE.c.stale)
Index("ix_evidence_origin", EVIDENCE.c.origin)
Index("ix_interpretations_status", INTERPRETATIONS.c.status)
Index("ix_claims_status", CLAIMS.c.status)
Index("ix_claims_stale", CLAIMS.c.stale)
Index("ix_claims_type", CLAIMS.c.type)
Index("ix_claim_evidence_evidence", CLAIM_EVIDENCE.c.evidence)
Index("ix_claim_decisions_decision", CLAIM_DECISIONS.c.decision)
Index("ix_decisions_type", DECISIONS.c.type)
Index("ix_decisions_status", DECISIONS.c.status)
Index("ix_questions_status", QUESTIONS.c.status)
Index("ix_question_links_target", QUESTION_LINKS.c.target)
Index("ix_taxonomy_terms_decision", TAXONOMY_TERMS.c.decision)
Index("ix_search_runs_research_question", SEARCH_RUNS.c.research_question)
Index("ix_search_candidates_screening", SEARCH_CANDIDATES.c.screening)
Index("ix_search_candidates_matched_work", SEARCH_CANDIDATES.c.matched_work)
Index("ix_search_candidates_key", SEARCH_CANDIDATES.c.key)
Index("ix_matrix_cells_work", MATRIX_CELLS.c.work)
Index("ix_notes_status", NOTES.c.status)
Index("ix_manuscript_anchors_claim", MANUSCRIPT_ANCHORS.c.claim)
Index("ix_manuscript_anchors_status", MANUSCRIPT_ANCHORS.c.status)
Index("ix_manuscript_anchors_stale", MANUSCRIPT_ANCHORS.c.stale)
Index("ix_events_event", EVENTS.c.event)
Index("ix_events_occurred_at", EVENTS.c.occurred_at)
Index("ix_dependencies_downstream_id", DEPENDENCIES.c.downstream_id)
Index("ix_dependencies_kind", DEPENDENCIES.c.kind)
Index("ix_stale_marks_priority", STALE_MARKS.c.priority)
Index("ix_stale_marks_source_change_id", STALE_MARKS.c.source_change_id)

TABLES: dict[str, Table] = dict(METADATA.tables)
"""Every projection table by name."""


def table_for(name: str) -> Table:
    """The projection table called ``name``; raises :class:`ProjectionError` if unknown."""
    try:
        return TABLES[name]
    except KeyError:
        raise ProjectionError(f"unknown projection table: {name!r}") from None


# --- engine lifecycle -------------------------------------------------------


def create_engine_for(db_path: Path) -> Engine:
    """SQLite engine for ``db_path`` with WAL journalling and foreign keys enforced."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(URL.create("sqlite+pysqlite", database=str(path)))

    @event.listens_for(engine, "connect")
    def _apply_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    return engine


def create_all(engine: Engine) -> None:
    """Create every projection table and index."""
    METADATA.create_all(engine)


def drop_all(engine: Engine) -> None:
    """Drop every projection table, FTS5 tables included (ADR-001, ADR-006).

    The lexical indexes are external-content FTS5 tables built over these rows, so a drop
    that left them behind would leave a "deleted" projection still answering queries from
    shadow tables whose content table is gone. They go first, for the same reason.

    `projection.fts` is imported here rather than at module scope because it reads
    :func:`assert_fts5_available` from this module.
    """
    from research_harness.projection.fts import drop_fts

    drop_fts(engine)
    METADATA.drop_all(engine)


def assert_fts5_available(engine: Engine) -> None:
    """Raise :class:`ProjectionError` unless this SQLite build provides FTS5.

    The lexical index (Task 3.3) needs FTS5, and PRODUCT 15.1 requires exact-terminology
    search to work with no embeddings and no services. This only probes; it never creates
    a projection FTS table.
    """
    with engine.connect() as connection:
        try:
            connection.execute(text("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(probe)"))
        except DatabaseError as error:
            raise ProjectionError(
                "this SQLite build lacks FTS5; the lexical projection cannot be built"
            ) from error
        # The probe is a throwaway temp table; the real FTS tables belong to fts.py.
        connection.execute(text("DROP TABLE temp.fts5_probe"))
        connection.rollback()
