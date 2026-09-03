"""Hypothesis strategies and deterministic builders for domain objects."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hypothesis import strategies as st

from research_harness.domain import (
    Artifact,
    ArtifactId,
    ArtifactKind,
    BlockId,
    Claim,
    ClaimAssessment,
    ClaimEvidenceRelation,
    ClaimEvidenceRelationType,
    ClaimId,
    ClaimScope,
    ClaimScopeSpec,
    ClaimSemantics,
    ClaimStatus,
    ClaimType,
    Coverage,
    Decision,
    DecisionId,
    DecisionStatus,
    DecisionType,
    DocumentBlock,
    DocumentBlockKind,
    Evidence,
    EvidenceContent,
    EvidenceId,
    EvidenceOrigin,
    EvidenceStrength,
    EvidenceType,
    IdentifierField,
    NumericValue,
    OverturnRisk,
    Provenance,
    ProvenanceSource,
    QuestionId,
    ResearchNote,
    ResearchQuestion,
    ReviewTier,
    ScreeningState,
    SearchRun,
    SearchRunId,
    SourceAnchor,
    Version,
    VersionId,
    VersionKind,
    Work,
    WorkId,
    WorkIdentifiers,
)

TEXT_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_.,"

# --- deterministic builders -------------------------------------------------

HUMAN = Provenance.human()
MODEL = Provenance.model("vendor-a/model-x")
SYSTEM = Provenance.system()

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64


def make_work(**overrides: Any) -> Work:
    """A minimal valid Work."""
    fields: dict[str, Any] = {
        "id": WorkId("W0017"),
        "title": "Structured traffic representations for LLM detection",
        "authors": ("A. Researcher", "B. Coauthor"),
        "year": 2026,
        "venue": "Journal of Examples",
        "provenance": SYSTEM,
    }
    return Work(**{**fields, **overrides})


def make_version(**overrides: Any) -> Version:
    """A minimal valid Version."""
    fields: dict[str, Any] = {
        "id": VersionId("V0017-2"),
        "work": WorkId("W0017"),
        "kind": VersionKind.ARXIV,
        "label": "v2",
        "provenance": SYSTEM,
    }
    return Version(**{**fields, **overrides})


def make_artifact(**overrides: Any) -> Artifact:
    """A minimal valid Artifact."""
    fields: dict[str, Any] = {
        "id": ArtifactId("A0017-3"),
        "work": WorkId("W0017"),
        "version": VersionId("V0017-2"),
        "kind": ArtifactKind.PDF,
        "file_hash": HASH_A,
        "original_filename": "paper.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 1024,
        "provenance": SYSTEM,
    }
    return Artifact(**{**fields, **overrides})


def make_anchor(**overrides: Any) -> SourceAnchor:
    """A complete source anchor."""
    fields: dict[str, Any] = {
        "work": WorkId("W0017"),
        "version": VersionId("V0017-2"),
        "artifact": ArtifactId("A0017-3"),
        "file_hash": HASH_A,
        "block": BlockId("B0081"),
        "text_hash": HASH_B,
        "page": 8,
        "section_path": ("Experiments", "Dataset"),
        "char_start": 284,
        "char_end": 516,
    }
    return SourceAnchor(**{**fields, **overrides})


def make_numeric(**overrides: Any) -> NumericValue:
    """A numeric value with full provenance."""
    fields: dict[str, Any] = {
        "raw": "94.32",
        "parsed": 94.32,
        "unit": "percent",
        "metric": "F1",
        "dataset": "CICIDS2017",
        "condition": {"split": "test"},
        "source_table": "T004",
        "source_row": "ours",
        "source_column": "F1",
    }
    return NumericValue(**{**fields, **overrides})


def make_evidence(**overrides: Any) -> Evidence:
    """A proposed, source-observed evidence object at review tier 1."""
    fields: dict[str, Any] = {
        "id": EvidenceId("E0482"),
        "source": make_anchor(),
        "content": EvidenceContent(exact_text="We evaluate on CICIDS2017."),
        "origin": EvidenceOrigin.SOURCE_OBSERVED,
        "evidence_type": EvidenceType.EXPERIMENTAL_SETUP,
        "strength": EvidenceStrength.DIRECT,
        "review_tier": ReviewTier.TIER_1,
        "provenance": MODEL,
    }
    return Evidence(**{**fields, **overrides})


def make_claim(**overrides: Any) -> Claim:
    """An unverified prevalence claim requesting L3 with an L0 audited ceiling."""
    fields: dict[str, Any] = {
        "id": ClaimId("C0041"),
        "statement": "Existing systems employ heterogeneous traffic tokenization schemes.",
        "type": ClaimType.PREVALENCE,
        "semantics": ClaimSemantics(
            subject="existing_systems",
            predicate="use",
            object="traffic_tokenization",
            qualifier={"property": "heterogeneous"},
        ),
        "scope": ClaimScopeSpec(
            level=ClaimScope.CORPUS_PATTERN,
            corpus="structured-traffic-llm",
            publication_until="2026-08",
        ),
        "relations": (
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0132"),
                relation=ClaimEvidenceRelationType.SUPPORTS,
            ),
            ClaimEvidenceRelation(
                evidence=EvidenceId("E0180"),
                relation=ClaimEvidenceRelationType.QUALIFIES,
                aspect="tokenizer granularity",
            ),
        ),
        "coverage": Coverage(
            relevant_works=17,
            examined_works=14,
            unresolved_works=3,
            overturn_risk=OverturnRisk.LOW_MODERATE,
        ),
        "assessment": ClaimAssessment(
            requested_strength=ClaimScope.FIELD_GENERALIZATION,
            allowed_strength=ClaimScope.INDIVIDUAL,
            status=ClaimStatus.UNVERIFIED,
        ),
        "provenance": HUMAN,
    }
    return Claim(**{**fields, **overrides})


def make_override_decision(**overrides: Any) -> Decision:
    """An accepted epistemic override for C0041."""
    fields: dict[str, Any] = {
        "id": DecisionId("D0027"),
        "type": DecisionType.EPISTEMIC_OVERRIDE,
        "status": DecisionStatus.ACCEPTED,
        "claim": ClaimId("C0041"),
        "auditor_recommendation": ClaimScope.CORPUS_PATTERN,
        "researcher_selected": ClaimScope.FIELD_GENERALIZATION,
        "rationale": "Coverage is strong enough for a field-level statement.",
        "provenance": HUMAN,
    }
    return Decision(**{**fields, **overrides})


def make_note(**overrides: Any) -> ResearchNote:
    """A captured research note."""
    fields: dict[str, Any] = {
        "text": "Tokenization terminology differs between these two papers.",
        "provenance": HUMAN,
    }
    return ResearchNote(**{**fields, **overrides})


def make_question(**overrides: Any) -> ResearchQuestion:
    """An open research question."""
    fields: dict[str, Any] = {
        "id": QuestionId("RQ0003"),
        "question": "Which systems retain protocol field semantics?",
        "provenance": HUMAN,
    }
    return ResearchQuestion(**{**fields, **overrides})


def make_block(**overrides: Any) -> DocumentBlock:
    """A parsed paragraph block."""
    fields: dict[str, Any] = {
        "id": BlockId("B0081"),
        "work": WorkId("W0017"),
        "version": VersionId("V0017-2"),
        "artifact": ArtifactId("A0017-3"),
        "kind": DocumentBlockKind.PARAGRAPH,
        "page": 8,
        "order": 12,
        "text": "We evaluate on CICIDS2017.",
        "text_hash": HASH_B,
        "section_path": ("Experiments", "Dataset"),
        "provenance": SYSTEM,
    }
    return DocumentBlock(**{**fields, **overrides})


def make_search_run(**overrides: Any) -> SearchRun:
    """A minimal search run."""
    fields: dict[str, Any] = {
        "id": SearchRunId("SR0019"),
        "question": "protocol-compliant adversarial traffic",
        "sources": ("semantic_scholar", "openalex"),
        "queries": ("protocol compliant adversarial traffic",),
        "provenance": SYSTEM,
    }
    return SearchRun(**{**fields, **overrides})


# --- hypothesis strategies --------------------------------------------------


def texts(min_size: int = 1, max_size: int = 24) -> st.SearchStrategy[str]:
    """Short printable text that survives whitespace stripping."""
    return (
        st.text(alphabet=TEXT_ALPHABET, min_size=min_size, max_size=max_size)
        .map(str.strip)
        .filter(lambda value: len(value) >= min_size)
    )


def hashes() -> st.SearchStrategy[str]:
    """Well-formed ``sha256:<hex>`` digests."""
    return st.text(alphabet="0123456789abcdef", min_size=64, max_size=64).map(
        lambda hexdigest: f"sha256:{hexdigest}"
    )


def timestamps() -> st.SearchStrategy[datetime]:
    """Timezone-aware UTC datetimes."""
    return st.datetimes(
        min_value=datetime(2000, 1, 1),
        max_value=datetime(2100, 1, 1),
        timezones=st.just(UTC),
    )


def numbers() -> st.SearchStrategy[int]:
    """Sequence numbers usable in stable ids."""
    return st.integers(min_value=1, max_value=9999)


def provenances() -> st.SearchStrategy[Provenance]:
    """Provenance records across every source."""
    return st.builds(
        Provenance,
        source=st.sampled_from(list(ProvenanceSource)),
        actor=texts(),
        workflow=st.none() | texts(),
        run_id=st.none() | texts(),
        template_version=st.none() | texts(),
        note=st.none() | texts(),
    )


def identifier_fields() -> st.SearchStrategy[IdentifierField]:
    """Metadata values with field-level provenance."""
    return st.builds(
        IdentifierField,
        value=texts(),
        source=st.sampled_from(list(ProvenanceSource)),
        confidence=st.none() | st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    )


def works() -> st.SearchStrategy[Work]:
    """Valid Work objects, including excluded ones with an exclusion reason."""
    return st.builds(
        Work,
        id=numbers().map(WorkId.make),
        title=texts(),
        authors=st.lists(texts(), max_size=3).map(tuple),
        year=st.none() | st.integers(min_value=1900, max_value=2100),
        venue=st.none() | texts(),
        identifiers=st.builds(WorkIdentifiers, doi=st.none() | identifier_fields()),
        screening=st.sampled_from(
            [state for state in ScreeningState if state is not ScreeningState.EXCLUDED]
        ),
        versions=st.lists(numbers().map(VersionId.make), max_size=2).map(tuple),
        artifacts=st.lists(numbers().map(ArtifactId.make), max_size=2).map(tuple),
        created_at=timestamps(),
        updated_at=timestamps(),
        provenance=provenances(),
    )


def versions() -> st.SearchStrategy[Version]:
    """Valid Version objects."""
    return st.builds(
        Version,
        id=numbers().map(lambda number: VersionId.make(number, 1)),
        work=numbers().map(WorkId.make),
        kind=st.sampled_from(list(VersionKind)),
        label=st.none() | texts(),
        date=st.none() | st.dates(),
        created_at=timestamps(),
        updated_at=timestamps(),
        provenance=provenances(),
    )


def artifacts() -> st.SearchStrategy[Artifact]:
    """Valid Artifact objects."""
    return st.builds(
        Artifact,
        id=numbers().map(lambda number: ArtifactId.make(number, 1)),
        work=numbers().map(WorkId.make),
        version=numbers().map(lambda number: VersionId.make(number, 1)),
        kind=st.sampled_from(list(ArtifactKind)),
        file_hash=hashes(),
        original_filename=texts(),
        mime_type=st.sampled_from(["application/pdf", "text/html"]),
        size_bytes=st.integers(min_value=0, max_value=10**9),
        ingested_at=timestamps(),
        created_at=timestamps(),
        updated_at=timestamps(),
        provenance=provenances(),
    )


def anchors() -> st.SearchStrategy[SourceAnchor]:
    """Complete source anchors."""
    return st.builds(
        SourceAnchor,
        work=numbers().map(WorkId.make),
        version=numbers().map(lambda number: VersionId.make(number, 1)),
        artifact=numbers().map(lambda number: ArtifactId.make(number, 1)),
        file_hash=hashes(),
        block=numbers().map(BlockId.make),
        text_hash=hashes(),
        page=st.none() | st.integers(min_value=1, max_value=500),
        section_path=st.lists(texts(), max_size=3).map(tuple),
    )


def numeric_values() -> st.SearchStrategy[NumericValue]:
    """Numeric values that always carry metric, dataset, and table provenance."""
    return st.builds(
        NumericValue,
        raw=texts(),
        parsed=st.floats(allow_nan=False, allow_infinity=False, width=32),
        unit=st.none() | texts(),
        metric=texts(),
        dataset=texts(),
        condition=st.dictionaries(texts(), texts(), max_size=2),
        source_table=texts(),
        source_row=st.none() | texts(),
        source_column=st.none() | texts(),
    )


def evidence_objects() -> st.SearchStrategy[Evidence]:
    """Proposed evidence objects across origins, types, and strengths."""
    return st.builds(
        Evidence,
        id=numbers().map(EvidenceId.make),
        source=anchors(),
        content=st.builds(
            EvidenceContent,
            exact_text=texts(),
            numeric=st.none() | numeric_values(),
            field=st.none() | texts(),
        ),
        origin=st.sampled_from(list(EvidenceOrigin)),
        evidence_type=st.sampled_from(list(EvidenceType)),
        strength=st.sampled_from(list(EvidenceStrength)),
        review_tier=st.sampled_from(list(ReviewTier)),
        created_at=timestamps(),
        updated_at=timestamps(),
        provenance=provenances(),
    )


def claim_assessments() -> st.SearchStrategy[ClaimAssessment]:
    """Assessments where allowed strength never exceeds the requested strength."""
    return st.integers(min_value=0, max_value=4).flatmap(
        lambda requested: st.builds(
            ClaimAssessment,
            requested_strength=st.just(ClaimScope.from_level(requested)),
            allowed_strength=st.integers(min_value=0, max_value=requested).map(
                ClaimScope.from_level
            ),
            status=st.sampled_from(list(ClaimStatus)),
            maximum_defensible_wording=st.none() | texts(),
            audited_at=st.none() | timestamps(),
        )
    )


def claims() -> st.SearchStrategy[Claim]:
    """Valid Claim objects with evidence relations and coverage."""
    return st.builds(
        Claim,
        id=numbers().map(ClaimId.make),
        statement=texts(),
        type=st.sampled_from(list(ClaimType)),
        semantics=st.builds(
            ClaimSemantics,
            subject=texts(),
            predicate=texts(),
            object=texts(),
            qualifier=st.dictionaries(texts(), texts(), max_size=2),
        ),
        scope=st.builds(
            ClaimScopeSpec,
            level=st.sampled_from(list(ClaimScope)),
            corpus=st.none() | texts(),
            publication_until=st.none() | st.just("2026-08"),
        ),
        relations=st.lists(
            st.builds(
                ClaimEvidenceRelation,
                evidence=numbers().map(EvidenceId.make),
                relation=st.sampled_from(list(ClaimEvidenceRelationType)),
                aspect=st.none() | texts(),
                note=st.none() | texts(),
            ),
            max_size=3,
        ).map(tuple),
        coverage=st.builds(
            Coverage,
            relevant_works=st.integers(min_value=0, max_value=1000),
            examined_works=st.integers(min_value=0, max_value=1000),
            unresolved_works=st.integers(min_value=0, max_value=1000),
            overturn_risk=st.sampled_from(list(OverturnRisk)),
            search_runs=st.lists(numbers().map(SearchRunId.make), max_size=2).map(tuple),
            cutoff=st.none() | st.dates(),
        ),
        assessment=claim_assessments(),
        decisions=st.lists(numbers().map(DecisionId.make), max_size=2).map(tuple),
        created_at=timestamps(),
        updated_at=timestamps(),
        provenance=provenances(),
    )


def decisions() -> st.SearchStrategy[Decision]:
    """Valid Decision objects for every decision type."""
    non_override = st.builds(
        Decision,
        id=numbers().map(DecisionId.make),
        type=st.sampled_from(
            [
                kind
                for kind in DecisionType
                if kind not in {DecisionType.EPISTEMIC_OVERRIDE, DecisionType.TAXONOMY_REVISION}
            ]
        ),
        status=st.sampled_from(list(DecisionStatus)),
        rationale=texts(),
        created_at=timestamps(),
        updated_at=timestamps(),
        provenance=provenances(),
    )
    taxonomy = st.builds(
        Decision,
        id=numbers().map(DecisionId.make),
        type=st.just(DecisionType.TAXONOMY_REVISION),
        status=st.sampled_from(list(DecisionStatus)),
        rationale=texts(),
        taxonomy_terms=st.lists(texts(), min_size=1, max_size=3).map(tuple),
        created_at=timestamps(),
        updated_at=timestamps(),
        provenance=provenances(),
    )
    override = st.integers(min_value=0, max_value=4).flatmap(
        lambda level: st.builds(
            Decision,
            id=numbers().map(DecisionId.make),
            type=st.just(DecisionType.EPISTEMIC_OVERRIDE),
            status=st.sampled_from(list(DecisionStatus)),
            rationale=texts(),
            claim=numbers().map(ClaimId.make),
            auditor_recommendation=st.just(ClaimScope.from_level(level)),
            researcher_selected=st.integers(min_value=level, max_value=4).map(
                ClaimScope.from_level
            ),
            created_at=timestamps(),
            updated_at=timestamps(),
            provenance=provenances(),
        )
    )
    return st.one_of(non_override, taxonomy, override)
