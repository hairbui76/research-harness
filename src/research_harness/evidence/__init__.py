"""The candidate evidence pipeline: interrogation, extraction, staging, verification.

Everything in this package produces *candidates*. A candidate has a real source anchor, a
real epistemic classification, and no authority whatsoever: it lives under `.research/`, it
is regenerable, and it becomes accepted Evidence only when a researcher accepts it through
the capability layer (Product §8.3, ADR-003, ADR-007). No module here opens a workspace
transaction or writes a canonical file — a wrong model, a bad prompt, or a provider outage
leaves the scientific record exactly as it was.

    from research_harness.evidence import DEFAULT_SCHEMA, StagingStore, extract_candidates

    result = extract_candidates(doc, DEFAULT_SCHEMA, provider, run_id=run.run_id)
    staging.put_all(result.candidates)

`review.py` and `service.py` are the other half: the inbox that decides what a researcher is
asked first, and the one service that turns an answer into accepted state — through the
capability layer, never by writing a file here.
"""

from __future__ import annotations

from research_harness.evidence.conflicts import (
    CONFLICT_ID_PATTERN,
    ConflictError,
    ConflictKind,
    ConflictNotFoundError,
    ConflictRecord,
    ConflictResolution,
    ConflictStore,
    conflict_id_for,
    load_conflict_records,
    materialize_candidate_vs_accepted_conflict,
    materialize_extractor_verifier_conflict,
    materialize_provider_conflict,
    new_conflict_id,
)
from research_harness.evidence.extraction import (
    DEFAULT_MAX_BLOCKS_PER_REQUEST,
    BackendInfo,
    ExtractionResult,
    ModelClient,
    RejectedOutput,
    backend_label,
    block_payload,
    chunk_blocks,
    extract_candidates,
    resolve_backend,
)
from research_harness.evidence.interrogation import (
    DEFAULT_SCHEMA,
    InterrogationField,
    InterrogationSchema,
    UnknownFieldError,
    ValueKind,
)
from research_harness.evidence.review import (
    CATEGORY_ORDER,
    REVIEWABLE_STATUSES,
    ReviewCategory,
    ReviewItem,
    ReviewQueue,
    SessionSummary,
    SourceContext,
    build_inbox,
    load_provider_conflicts,
    session_summary,
    stored_document,
    stored_documents,
)
from research_harness.evidence.service import (
    FACT_ORIGINS,
    LOW_RISK_TIERS,
    BatchResult,
    EvidenceReviewService,
    SplitAcceptance,
)
from research_harness.evidence.staging import (
    CANDIDATE_ID_PATTERN,
    PROVISIONAL_EVIDENCE_ID,
    CandidateNotFoundError,
    CandidateStatus,
    EvidenceCandidate,
    ExtractionProvenance,
    StagingError,
    StagingStore,
    apply_verification,
    candidate_id_for,
    new_candidate_id,
)
from research_harness.evidence.verification import (
    QUOTE_NOT_IN_SOURCE,
    SUPPORTING_VERDICTS,
    build_source_context,
    candidate_payload,
    context_blocks,
    enforce_quoted_support,
    verify_candidate,
)

__all__ = [
    "CANDIDATE_ID_PATTERN",
    "CATEGORY_ORDER",
    "CONFLICT_ID_PATTERN",
    "DEFAULT_MAX_BLOCKS_PER_REQUEST",
    "DEFAULT_SCHEMA",
    "FACT_ORIGINS",
    "LOW_RISK_TIERS",
    "PROVISIONAL_EVIDENCE_ID",
    "QUOTE_NOT_IN_SOURCE",
    "REVIEWABLE_STATUSES",
    "SUPPORTING_VERDICTS",
    "BackendInfo",
    "BatchResult",
    "CandidateNotFoundError",
    "CandidateStatus",
    "ConflictError",
    "ConflictKind",
    "ConflictNotFoundError",
    "ConflictRecord",
    "ConflictResolution",
    "ConflictStore",
    "EvidenceCandidate",
    "EvidenceReviewService",
    "ExtractionProvenance",
    "ExtractionResult",
    "InterrogationField",
    "InterrogationSchema",
    "ModelClient",
    "RejectedOutput",
    "ReviewCategory",
    "ReviewItem",
    "ReviewQueue",
    "SessionSummary",
    "SourceContext",
    "SplitAcceptance",
    "StagingError",
    "StagingStore",
    "UnknownFieldError",
    "ValueKind",
    "apply_verification",
    "backend_label",
    "block_payload",
    "build_inbox",
    "build_source_context",
    "candidate_id_for",
    "candidate_payload",
    "chunk_blocks",
    "conflict_id_for",
    "context_blocks",
    "enforce_quoted_support",
    "extract_candidates",
    "load_conflict_records",
    "load_provider_conflicts",
    "materialize_candidate_vs_accepted_conflict",
    "materialize_extractor_verifier_conflict",
    "materialize_provider_conflict",
    "new_candidate_id",
    "new_conflict_id",
    "resolve_backend",
    "session_summary",
    "stored_document",
    "stored_documents",
    "verify_candidate",
]
