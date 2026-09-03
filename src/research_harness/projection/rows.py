"""Deterministic canonical object -> projection row mapping.

``rows_for(obj)`` is pure: the same canonical object always yields the same
:class:`RowSpec` list, in the same order, with the same values. Primary keys are the
canonical IDs verbatim (ADR-001: projection IDs equal canonical IDs), so a rebuild
changes neither content nor identity.

**Nothing in this package is ever read back as scientific truth.** These rows are a
disposable index over the canonical YAML/JSONL files (PRODUCT 8.2, ADR-001, ADR-006);
if a value exists only here, the workspace is broken, not merely un-indexed.

Values are JSON-compatible scalars only. Nested collections (author lists, identifier
maps, section paths, condition dicts, event payloads, provenance) are stored as compact
JSON text with sorted keys so that two projections of the same object compare byte for
byte.

Intentional omissions
---------------------

* :class:`~research_harness.domain.work.WorkCandidate` is not projected at all: staged
  candidates carry no scientific authority (PRODUCT 8.3) and are not corpus state.
* :class:`~research_harness.domain.manuscript.ManuscriptAuditFinding` is not projected:
  audit findings are recomputed on demand, never stored.
* :class:`~research_harness.domain.document.ParsedDocument` projects its blocks and table
  cells only; its ``work``, ``version``, ``artifact``, and ``file_hash`` reach the block
  rows. ``parser_name``, ``parser_version``, ``page_count``, ``parsed_at``, its own
  ``provenance`` and ``schema_version`` are parser-generation metadata, which ADR-006
  keeps in index metadata (``projection_meta.parser_name`` / ``parser_version``), never
  in per-object rows. A block projected on its own carries no ``file_hash``: only the
  parsed document knows which bytes the parse read.
* Objects without a canonical ID get a deterministic surrogate key documented on the
  helper that computes it (:func:`note_key`, :func:`event_id`,
  :func:`manuscript_anchor_key`, :func:`taxonomy_node_id`, :func:`matrix_cell_node_id`).
* ``Interpretation.evidence`` is stored as a JSON list rather than a link table; the
  ``interprets`` dependency edges in :mod:`~research_harness.projection.dependencies`
  carry the queryable form.

Every other non-empty field of every projected type is recoverable from its row.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Connection
from sqlalchemy.dialects.sqlite import Insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from research_harness.domain import (
    Artifact,
    Claim,
    Decision,
    DocumentBlock,
    Evidence,
    IdentifierField,
    Interpretation,
    ManuscriptAnchor,
    ParsedDocument,
    ResearchEvent,
    ResearchNote,
    ResearchQuestion,
    SearchCandidate,
    SearchRun,
    SynthesisMatrix,
    Taxonomy,
    Version,
    Work,
)
from research_harness.domain.errors import ProjectionError
from research_harness.projection.schema import (
    ARTIFACTS,
    BLOCKS,
    CLAIM_DECISIONS,
    CLAIM_EVIDENCE,
    CLAIMS,
    DECISIONS,
    EVENTS,
    EVIDENCE,
    INTERPRETATIONS,
    MANUSCRIPT_ANCHORS,
    MATRICES,
    MATRIX_CELLS,
    NOTES,
    QUESTION_LINKS,
    QUESTIONS,
    SEARCH_CANDIDATES,
    SEARCH_RUNS,
    TABLE_CELLS,
    TAXONOMIES,
    TAXONOMY_TERMS,
    VERSIONS,
    WORKS,
    table_for,
)

__all__ = [
    "MANUSCRIPT_ANCHOR_PREFIX",
    "NODE_SEPARATOR",
    "TAXONOMY_PREFIX",
    "QuestionLinkKind",
    "RowSpec",
    "event_id",
    "manuscript_anchor_key",
    "matrix_cell_node_id",
    "node_id_for",
    "note_key",
    "rows_for",
    "taxonomy_node_id",
    "upsert_rows",
]

MANUSCRIPT_ANCHOR_PREFIX = "MA:"
"""Node-id prefix for manuscript anchors, which have no canonical research ID."""

TAXONOMY_PREFIX = "TX:"
"""Node-id prefix for taxonomies, which are named rather than ID'd."""

NODE_SEPARATOR = "#"
"""Separator inside composite projection node ids."""

JsonScalar = str | int | float | bool | None


class QuestionLinkKind(StrEnum):
    """What a row in ``question_links`` connects a research question to."""

    CLAIM = "claim"
    SEARCH_RUN = "search_run"
    SUPPORTING_EVIDENCE = "supporting_evidence"
    COUNTER_EVIDENCE = "counter_evidence"


@dataclass(frozen=True, slots=True)
class RowSpec:
    """One projection row: the table it belongs to and its scalar column values."""

    table: str
    values: Mapping[str, JsonScalar]


# --- scalar encoding --------------------------------------------------------


def _json(value: Any) -> str:
    """Compact, key-sorted JSON text; the only representation of nested collections."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _dumped(model: BaseModel | None) -> Any:
    return None if model is None else model.model_dump(mode="json")


def _json_model(model: BaseModel | None) -> str | None:
    return None if model is None else _json(_dumped(model))


def _strings(values: Iterable[Any]) -> list[str]:
    return [str(value) for value in values]


def _moment(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _flag(value: bool | None) -> int | None:
    """SQLite has no boolean: 1/0 for a decision, NULL for "nobody checked yet"."""
    return None if value is None else int(value)


def _year(field: IdentifierField | None) -> int | None:
    """A candidate's stated year as an int, or ``None`` when it stated none it can parse."""
    if field is None:
        return None
    try:
        return int(field.value.strip())
    except ValueError:
        return None


# --- surrogate keys for objects without a canonical ID ----------------------


def manuscript_anchor_key(file: str, sentence_fingerprint: str) -> str:
    """Stable node id of a manuscript anchor: ``MA:<file>#<sentence_fingerprint>``.

    An anchor has no research ID; PRODUCT 30.1 identifies it by file plus sentence
    fingerprint, which is exactly what invalidates it when the sentence is reworded.
    """
    return f"{MANUSCRIPT_ANCHOR_PREFIX}{file}{NODE_SEPARATOR}{sentence_fingerprint}"


def taxonomy_node_id(name: str) -> str:
    """Stable node id of a taxonomy: ``TX:<name>``."""
    return f"{TAXONOMY_PREFIX}{name}"


def matrix_cell_node_id(matrix: str, work: str, field: str) -> str:
    """Stable node id of one matrix cell: ``<matrix>#<work>#<field>``."""
    return f"{matrix}{NODE_SEPARATOR}{work}{NODE_SEPARATOR}{field}"


def note_key(note: ResearchNote) -> str:
    """Stable primary key of a note: its ``key`` when set, else a content digest.

    Notes are low-authority captures with no research ID (PRODUCT 31). The digest covers
    text, creation time, and actor, so re-projecting the same note is idempotent while two
    distinct notes with identical text stay distinct rows.
    """
    if note.key:
        return note.key
    material = _json(
        {
            "text": note.text,
            "created_at": note.created_at.isoformat(),
            "actor": note.provenance.actor,
        }
    )
    return f"note:{hashlib.sha256(material.encode()).hexdigest()[:32]}"


def event_id(event: ResearchEvent) -> str:
    """Stable primary key of a semantic event: a digest of its whole serialized content."""
    material = _json(event.model_dump(mode="json"))
    return f"ev:{hashlib.sha256(material.encode()).hexdigest()[:32]}"


def node_id_for(obj: object) -> str:
    """Dependency-graph node id of a canonical object.

    Equal to ``obj.id`` for every object that has one; a documented surrogate otherwise.
    """
    if isinstance(obj, ManuscriptAnchor):
        return manuscript_anchor_key(obj.file, obj.sentence_fingerprint)
    if isinstance(obj, Taxonomy):
        return taxonomy_node_id(obj.name)
    if isinstance(obj, ResearchNote):
        return note_key(obj)
    if isinstance(obj, ResearchEvent):
        return event_id(obj)
    identifier = getattr(obj, "id", None)
    if identifier is None:
        raise ProjectionError(f"{type(obj).__name__} has no projection node id")
    return str(identifier)


# --- per-type row builders --------------------------------------------------


def _tracked(obj: Any) -> dict[str, JsonScalar]:
    return {
        "schema_version": obj.schema_version,
        "created_at": obj.created_at.isoformat(),
        "updated_at": obj.updated_at.isoformat(),
        "provenance": _json(_dumped(obj.provenance)),
    }


def _work_rows(work: Work) -> list[RowSpec]:
    return [
        RowSpec(
            WORKS.name,
            {
                "id": str(work.id),
                "title": work.title,
                "authors": _json(list(work.authors)),
                "year": work.year,
                "venue": work.venue,
                "identifiers": _json(_dumped(work.identifiers)),
                "screening": work.screening.value,
                "exclusion_reason": work.exclusion_reason,
                "versions": _json(_strings(work.versions)),
                "artifacts": _json(_strings(work.artifacts)),
                **_tracked(work),
            },
        )
    ]


def _version_rows(version: Version) -> list[RowSpec]:
    return [
        RowSpec(
            VERSIONS.name,
            {
                "id": str(version.id),
                "work": str(version.work),
                "kind": version.kind.value,
                "label": version.label,
                "date": _day(version.date),
                "identifiers": _json(_dumped(version.identifiers)),
                **_tracked(version),
            },
        )
    ]


def _artifact_rows(artifact: Artifact) -> list[RowSpec]:
    return [
        RowSpec(
            ARTIFACTS.name,
            {
                "id": str(artifact.id),
                "work": str(artifact.work),
                "version": str(artifact.version),
                "kind": artifact.kind.value,
                "file_hash": artifact.file_hash,
                "original_filename": artifact.original_filename,
                "mime_type": artifact.mime_type,
                "size_bytes": artifact.size_bytes,
                "ingested_at": artifact.ingested_at.isoformat(),
                **_tracked(artifact),
            },
        )
    ]


def _block_rows(block: DocumentBlock, file_hash: str | None = None) -> list[RowSpec]:
    rows = [
        RowSpec(
            BLOCKS.name,
            {
                "artifact": str(block.artifact),
                "id": str(block.id),
                "work": str(block.work),
                "version": str(block.version),
                "file_hash": file_hash,
                "kind": block.kind.value,
                "page": block.page,
                "order": block.order,
                "text": block.text,
                "text_hash": block.text_hash,
                "section_path": _json(list(block.section_path)),
                "bbox": _json_model(block.bbox),
                "caption": block.caption,
                "caption_for": _text(block.caption_for),
                "reference_key": block.reference_key,
                "reference_raw": block.reference_raw,
                **_tracked(block),
            },
        )
    ]
    rows.extend(
        RowSpec(
            TABLE_CELLS.name,
            {
                "artifact": str(block.artifact),
                "block": str(block.id),
                "row": cell.row,
                "col": cell.col,
                "text": cell.text,
                "bbox": _json_model(cell.bbox),
            },
        )
        for cell in block.cells
    )
    return rows


def _parsed_document_rows(document: ParsedDocument) -> list[RowSpec]:
    rows: list[RowSpec] = []
    for block in document.blocks:
        rows.extend(_block_rows(block, document.file_hash))
    return rows


def _evidence_rows(evidence: Evidence) -> list[RowSpec]:
    anchor = evidence.source
    content = evidence.content
    numeric = content.numeric
    verification = evidence.verification
    return [
        RowSpec(
            EVIDENCE.name,
            {
                "id": str(evidence.id),
                "work": str(anchor.work),
                "version": str(anchor.version),
                "artifact": str(anchor.artifact),
                "file_hash": anchor.file_hash,
                "page": anchor.page,
                "block": str(anchor.block),
                "text_hash": anchor.text_hash,
                "section_path": _json(list(anchor.section_path)),
                "char_start": anchor.char_start,
                "char_end": anchor.char_end,
                "bbox": _json_model(anchor.bbox),
                "origin": evidence.origin.value,
                "evidence_type": evidence.evidence_type.value,
                "strength": evidence.strength.value,
                "stale": evidence.stale.value,
                "review_tier": int(evidence.review_tier),
                "qualification": evidence.qualification,
                "decisions": _json(_strings(evidence.decisions)),
                "exact_text": content.exact_text,
                "negative_state": _text(content.negative_state),
                "field": content.field,
                "metric": None if numeric is None else numeric.metric,
                "dataset": None if numeric is None else numeric.dataset,
                "unit": None if numeric is None else numeric.unit,
                "numeric_value": None if numeric is None else numeric.parsed,
                "numeric_raw": None if numeric is None else numeric.raw,
                "numeric_condition": None if numeric is None else _json(numeric.condition),
                "numeric_source_table": None if numeric is None else numeric.source_table,
                "numeric_source_row": None if numeric is None else numeric.source_row,
                "numeric_source_column": None if numeric is None else numeric.source_column,
                "status": verification.status.value,
                "verdict": _text(verification.verdict),
                "extractor": verification.extractor,
                "verifier": verification.verifier,
                "accepted_by": verification.accepted_by,
                "review_action": _text(verification.review_action),
                "rationale": verification.rationale,
                "reviewed_at": _moment(verification.reviewed_at),
                **_tracked(evidence),
            },
        )
    ]


def _interpretation_rows(interpretation: Interpretation) -> list[RowSpec]:
    verification = interpretation.verification
    return [
        RowSpec(
            INTERPRETATIONS.name,
            {
                "id": str(interpretation.id),
                "evidence": _json(_strings(interpretation.evidence)),
                "text": interpretation.text,
                "origin": interpretation.origin.value,
                "stale": interpretation.stale.value,
                "review_tier": int(interpretation.review_tier),
                "qualification": interpretation.qualification,
                "status": verification.status.value,
                "verdict": _text(verification.verdict),
                "extractor": verification.extractor,
                "verifier": verification.verifier,
                "accepted_by": verification.accepted_by,
                "review_action": _text(verification.review_action),
                "rationale": verification.rationale,
                "reviewed_at": _moment(verification.reviewed_at),
                **_tracked(interpretation),
            },
        )
    ]


def _claim_rows(claim: Claim) -> list[RowSpec]:
    semantics = claim.semantics
    scope = claim.scope
    coverage = claim.coverage
    assessment = claim.assessment
    rows = [
        RowSpec(
            CLAIMS.name,
            {
                "id": str(claim.id),
                "statement": claim.statement,
                "type": claim.type.value,
                "semantics_subject": semantics.subject,
                "semantics_predicate": semantics.predicate,
                "semantics_object": semantics.object,
                "semantics_qualifier": _json(semantics.qualifier),
                "scope_level": scope.level.value,
                "corpus": scope.corpus,
                "publication_until": scope.publication_until,
                "status": assessment.status.value,
                "requested_strength": assessment.requested_strength.value,
                "allowed_strength": assessment.allowed_strength.value,
                "maximum_defensible_wording": assessment.maximum_defensible_wording,
                "audited_at": _moment(assessment.audited_at),
                "stale": claim.stale.value,
                "relevant_works": coverage.relevant_works,
                "examined_works": coverage.examined_works,
                "unresolved_works": coverage.unresolved_works,
                "overturn_risk": coverage.overturn_risk.value,
                "coverage_cutoff": _day(coverage.cutoff),
                "coverage_search_runs": _json(_strings(coverage.search_runs)),
                "derived_from": _json(_strings(claim.derived_from)),
                **_tracked(claim),
            },
        )
    ]
    rows.extend(
        RowSpec(
            CLAIM_EVIDENCE.name,
            {
                "claim": str(claim.id),
                "ordinal": ordinal,
                "evidence": str(link.evidence),
                "relation": link.relation.value,
                "aspect": link.aspect,
                "note": link.note,
            },
        )
        for ordinal, link in enumerate(claim.relations)
    )
    rows.extend(
        RowSpec(
            CLAIM_DECISIONS.name,
            {"claim": str(claim.id), "decision": str(decision), "ordinal": ordinal},
        )
        for ordinal, decision in enumerate(claim.decisions)
    )
    return rows


def _decision_rows(decision: Decision) -> list[RowSpec]:
    return [
        RowSpec(
            DECISIONS.name,
            {
                "id": str(decision.id),
                "type": decision.type.value,
                "status": decision.status.value,
                "title": decision.title,
                "rationale": decision.rationale,
                "claim": _text(decision.claim),
                "auditor_recommendation": _text(decision.auditor_recommendation),
                "researcher_selected": _text(decision.researcher_selected),
                "taxonomy_terms": _json(list(decision.taxonomy_terms)),
                "supersedes": _text(decision.supersedes),
                **_tracked(decision),
            },
        )
    ]


def _question_rows(question: ResearchQuestion) -> list[RowSpec]:
    rows = [
        RowSpec(
            QUESTIONS.name,
            {
                "id": str(question.id),
                "question": question.question,
                "status": question.status.value,
                "remaining_uncertainty": question.remaining_uncertainty,
                "stale": question.stale.value,
                **_tracked(question),
            },
        )
    ]
    linked: Sequence[tuple[QuestionLinkKind, tuple[Any, ...]]] = (
        (QuestionLinkKind.CLAIM, question.claims),
        (QuestionLinkKind.SEARCH_RUN, question.search_runs),
        (QuestionLinkKind.SUPPORTING_EVIDENCE, question.supporting_evidence),
        (QuestionLinkKind.COUNTER_EVIDENCE, question.counter_evidence),
    )
    for kind, targets in linked:
        rows.extend(
            RowSpec(
                QUESTION_LINKS.name,
                {
                    "question": str(question.id),
                    "kind": kind.value,
                    "target": str(target),
                    "ordinal": ordinal,
                },
            )
            for ordinal, target in enumerate(targets)
        )
    return rows


def _taxonomy_rows(taxonomy: Taxonomy) -> list[RowSpec]:
    rows = [
        RowSpec(
            TAXONOMIES.name,
            {
                "name": taxonomy.name,
                "node_id": taxonomy_node_id(taxonomy.name),
                **_tracked(taxonomy),
            },
        )
    ]
    rows.extend(
        RowSpec(
            TAXONOMY_TERMS.name,
            {
                "taxonomy": taxonomy.name,
                "term": term.term,
                "parent": term.parent,
                "definition": term.definition,
                "decision": _text(term.decision),
                "ordinal": ordinal,
            },
        )
        for ordinal, term in enumerate(taxonomy.terms)
    )
    return rows


def _search_run_rows(run: SearchRun) -> list[RowSpec]:
    rows = [
        RowSpec(
            SEARCH_RUNS.name,
            {
                "id": str(run.id),
                "question": run.question,
                "research_question": _text(run.research_question),
                "sources": _json(list(run.sources)),
                "queries": _json(list(run.queries)),
                "filters": _json(run.filters),
                "discovered": run.results.discovered,
                "screened": run.results.screened,
                "included": run.results.included,
                "executed_at": run.executed_at.isoformat(),
                "cutoff": _day(run.cutoff),
                "cursors": _json([_dumped(cursor) for cursor in run.cursors]),
                "failures": _json([_dumped(failure) for failure in run.failures]),
                "unresolved_identities": _json(list(run.unresolved_identities)),
                "unavailable_full_text": _json(_strings(run.unavailable_full_text)),
                "unresolved_keys": _json(list(run.unresolved_keys)),
                "full_text_unavailable_keys": _json(list(run.full_text_unavailable_keys)),
                "reproduces": _text(run.reproduces),
                **_tracked(run),
            },
        )
    ]
    rows.extend(
        _search_candidate_row(run, ordinal, candidate)
        for ordinal, candidate in enumerate(run.candidates)
    )
    return rows


def _search_candidate_row(run: SearchRun, ordinal: int, entry: SearchCandidate) -> RowSpec:
    """One discovery candidate of ``run``.

    Keyed by ``(run, key)`` rather than by work: two candidates that resolve to the same
    Work are two rows, because each carries the source and rank that reported it and
    ADR-002 keeps their Version/Artifact records apart.
    """
    metadata = entry.candidate.metadata
    identifiers = metadata.identifiers
    return RowSpec(
        SEARCH_CANDIDATES.name,
        {
            "run": str(run.id),
            "key": entry.key,
            "ordinal": ordinal,
            "sources": _json(list(entry.sources)),
            "ranks": _json(dict(entry.ranks)),
            "screening": entry.screening.value,
            "exclusion_reason": entry.exclusion_reason,
            "screened_by": entry.screened_by,
            "screened_at": _moment(entry.screened_at),
            "identity": None if entry.identity is None else entry.identity.value,
            "matched_work": _text(entry.matched_work),
            "full_text_available": _flag(entry.full_text_available),
            "title": None if metadata.title is None else metadata.title.value,
            "year": _year(metadata.year),
            "doi": None if identifiers.doi is None else identifiers.doi.value,
            "arxiv": None if identifiers.arxiv is None else identifiers.arxiv.value,
            "source_query": entry.candidate.source_query,
            "candidate": _json(_dumped(entry.candidate)),
        },
    )


def _matrix_rows(matrix: SynthesisMatrix) -> list[RowSpec]:
    rows = [
        RowSpec(
            MATRICES.name,
            {
                "id": str(matrix.id),
                "name": matrix.name,
                "taxonomy": matrix.taxonomy,
                "works": _json(_strings(matrix.works)),
                "fields": _json(list(matrix.fields)),
                "stale": matrix.stale.value,
                **_tracked(matrix),
            },
        )
    ]
    rows.extend(
        RowSpec(
            MATRIX_CELLS.name,
            {
                "matrix": str(matrix.id),
                "work": str(cell.work),
                "field": cell.field,
                "cell_id": matrix_cell_node_id(str(matrix.id), str(cell.work), cell.field),
                "labels": _json(list(cell.labels)),
                "evidence": _json(_strings(cell.evidence)),
            },
        )
        for cell in matrix.cells
    )
    return rows


def _note_rows(note: ResearchNote) -> list[RowSpec]:
    return [
        RowSpec(
            NOTES.name,
            {
                "note_key": note_key(note),
                "key": note.key,
                "text": note.text,
                "status": note.status.value,
                "promoted_to": _text(note.promoted_to),
                **_tracked(note),
            },
        )
    ]


def _manuscript_anchor_rows(anchor: ManuscriptAnchor) -> list[RowSpec]:
    return [
        RowSpec(
            MANUSCRIPT_ANCHORS.name,
            {
                "file": anchor.file,
                "sentence_fingerprint": anchor.sentence_fingerprint,
                "anchor_id": manuscript_anchor_key(anchor.file, anchor.sentence_fingerprint),
                "line_start": anchor.line_start,
                "line_end": anchor.line_end,
                "char_start": anchor.char_start,
                "char_end": anchor.char_end,
                "sentence": anchor.sentence,
                "claim": str(anchor.claim),
                "citation_keys": _json(list(anchor.citation_keys)),
                "status": anchor.status.value,
                "stale": anchor.stale.value,
                **_tracked(anchor),
            },
        )
    ]


def _event_rows(event: ResearchEvent) -> list[RowSpec]:
    return [
        RowSpec(
            EVENTS.name,
            {
                "event_id": event_id(event),
                "event": event.event.value,
                "actor": event.actor,
                "occurred_at": event.occurred_at.isoformat(),
                "summary": event.summary,
                "subjects": _json(_strings(event.subjects)),
                "payload": _json(event.payload),
                "objects": _json(event.objects),
                "schema_version": event.schema_version,
            },
        )
    ]


def rows_for(obj: object) -> list[RowSpec]:
    """Projection rows for one canonical object, in a stable order.

    The first row is always the object's own row and its primary key is the canonical ID;
    any following rows are its owned child rows (table cells, claim-evidence links,
    question links, taxonomy terms, matrix cells).
    """
    if isinstance(obj, Work):
        return _work_rows(obj)
    if isinstance(obj, Version):
        return _version_rows(obj)
    if isinstance(obj, Artifact):
        return _artifact_rows(obj)
    if isinstance(obj, DocumentBlock):
        return _block_rows(obj)
    if isinstance(obj, ParsedDocument):
        return _parsed_document_rows(obj)
    if isinstance(obj, Evidence):
        return _evidence_rows(obj)
    if isinstance(obj, Interpretation):
        return _interpretation_rows(obj)
    if isinstance(obj, Claim):
        return _claim_rows(obj)
    if isinstance(obj, Decision):
        return _decision_rows(obj)
    if isinstance(obj, ResearchQuestion):
        return _question_rows(obj)
    if isinstance(obj, Taxonomy):
        return _taxonomy_rows(obj)
    if isinstance(obj, SearchRun):
        return _search_run_rows(obj)
    if isinstance(obj, SynthesisMatrix):
        return _matrix_rows(obj)
    if isinstance(obj, ResearchNote):
        return _note_rows(obj)
    if isinstance(obj, ManuscriptAnchor):
        return _manuscript_anchor_rows(obj)
    if isinstance(obj, ResearchEvent):
        return _event_rows(obj)
    raise ProjectionError(f"{type(obj).__name__} has no projection mapping")


def upsert_rows(connection: Connection, rows: Iterable[RowSpec]) -> None:
    """Insert or update ``rows`` with SQLite ``INSERT ... ON CONFLICT``.

    Re-projecting an unchanged object is a no-op, so a rebuild is idempotent.

    Consecutive rows that address the same table with the same columns are sent as one
    ``executemany``, and the statement for a `(table, columns)` shape is built once per
    process. Building and compiling one statement per row was 44 % of a full rebuild;
    SQLite still applies the rows one at a time in the order given, so the resulting tables
    and the rebuild's determinism are unchanged.
    """
    for statement, parameters in _batched(rows):
        connection.execute(statement, parameters)


def _batched(rows: Iterable[RowSpec]) -> Iterator[tuple[Insert, list[dict[str, JsonScalar]]]]:
    """Group ``rows`` into runs of one table and one column shape, in the order given."""
    shape: tuple[str, tuple[str, ...]] | None = None
    batch: list[dict[str, JsonScalar]] = []
    for row in rows:
        current = (row.table, tuple(row.values))
        if current != shape:
            if shape is not None and batch:
                yield _upsert_statement(shape), batch
            shape, batch = current, []
        batch.append(dict(row.values))
    if shape is not None and batch:
        yield _upsert_statement(shape), batch


def _upsert_statement(shape: tuple[str, tuple[str, ...]]) -> Insert:
    """The cached ``INSERT ... ON CONFLICT`` for one table and one set of columns."""
    cached = _STATEMENTS.get(shape)
    if cached is not None:
        return cached
    name, columns = shape
    table = table_for(name)
    key_names = [column.name for column in table.primary_key.columns]
    statement = sqlite_insert(table)
    updates = {name: statement.excluded[name] for name in columns if name not in key_names}
    if updates:
        statement = statement.on_conflict_do_update(index_elements=key_names, set_=updates)
    else:
        statement = statement.on_conflict_do_nothing(index_elements=key_names)
    _STATEMENTS[shape] = statement
    return statement


#: `(table, columns) -> statement`. Bounded by the schema: one entry per column shape a
#: :func:`rows_for` mapping can produce, never by the number of rows written.
_STATEMENTS: dict[tuple[str, tuple[str, ...]], Insert] = {}
