"""Controlled vocabularies for the research domain (Product 9-14, 18, 24, 31, 37, 38).

Every vocabulary is an ``enum.StrEnum`` so canonical YAML/JSONL stays human readable and
schema-validated instead of free-form text. ``ReviewTier`` is the one exception: tiers are
an ordered numeric level, so it is an ``IntEnum``.

Domain plugins may extend these vocabularies; the core never widens them silently.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

__all__ = [
    "ACCEPTING_REVIEW_ACTIONS",
    "INTERPRETIVE_ORIGINS",
    "PROMOTABLE_NEGATIVE_STATES",
    "ArtifactKind",
    "ClaimEvidenceRelationType",
    "ClaimScope",
    "ClaimStatus",
    "ClaimType",
    "DecisionStatus",
    "DecisionType",
    "DocumentBlockKind",
    "EvidenceOrigin",
    "EvidenceStatus",
    "EvidenceStrength",
    "EvidenceType",
    "FindingSeverity",
    "IdentityResolutionOutcome",
    "ManuscriptAnchorStatus",
    "ManuscriptFindingKind",
    "NegativeEvidenceState",
    "NoteStatus",
    "OverturnRisk",
    "ProvenanceSource",
    "QuestionStatus",
    "ResearchEventType",
    "ReviewAction",
    "ReviewPolicy",
    "ReviewTier",
    "ScreeningState",
    "StaleState",
    "TransitionKind",
    "VerificationVerdict",
    "VersionKind",
]


class ProvenanceSource(StrEnum):
    """Who produced a record. Never a provider or host name; see `Provenance.actor`."""

    HUMAN = "human"
    MODEL = "model"
    SYSTEM = "system"
    EXTERNAL_METADATA = "external_metadata"


class EvidenceOrigin(StrEnum):
    """Epistemic origin of an evidence object (Product 9.1)."""

    SOURCE_OBSERVED = "source_observed"
    AUTHOR_CLAIMED = "author_claimed"
    AUTHOR_INTERPRETED = "author_interpreted"
    RESEARCHER_INFERRED = "researcher_inferred"
    MODEL_PROPOSED = "model_proposed"
    EXTERNAL_METADATA = "external_metadata"


#: Origins whose acceptance is an interpretive judgement and therefore human-only.
INTERPRETIVE_ORIGINS: frozenset[EvidenceOrigin] = frozenset(
    {
        EvidenceOrigin.AUTHOR_INTERPRETED,
        EvidenceOrigin.RESEARCHER_INFERRED,
        EvidenceOrigin.MODEL_PROPOSED,
    }
)


class EvidenceType(StrEnum):
    """What kind of statement the evidence carries (Product 9.2)."""

    METHOD_DESCRIPTION = "method_description"
    REPRESENTATION_DESCRIPTION = "representation_description"
    EXPERIMENTAL_SETUP = "experimental_setup"
    EXPERIMENTAL_RESULT = "experimental_result"
    ABLATION_RESULT = "ablation_result"
    DATASET_DESCRIPTION = "dataset_description"
    BASELINE_DESCRIPTION = "baseline_description"
    LIMITATION = "limitation"
    AUTHOR_CONCLUSION = "author_conclusion"
    DEFINITION = "definition"
    THEORETICAL_RESULT = "theoretical_result"
    IMPLEMENTATION_DETAIL = "implementation_detail"
    DEPLOYMENT_ASSUMPTION = "deployment_assumption"
    BIBLIOGRAPHIC_METADATA = "bibliographic_metadata"


class EvidenceStrength(StrEnum):
    """How directly the source supports the evidence (Product 9.3)."""

    DIRECT = "direct"
    INDIRECT = "indirect"
    DERIVED = "derived"


class NegativeEvidenceState(StrEnum):
    """Absence states, deliberately distinct (Product 11, principle P5).

    A missing lexical hit is `not_found`; `absent` is an audited conclusion.
    """

    ABSENT = "absent"
    NOT_FOUND = "not_found"
    NOT_REPORTED = "not_reported"
    NOT_APPLICABLE = "not_applicable"
    UNCLEAR = "unclear"


#: States an audited decision may promote to `absent`.
PROMOTABLE_NEGATIVE_STATES: frozenset[NegativeEvidenceState] = frozenset(
    {NegativeEvidenceState.NOT_FOUND, NegativeEvidenceState.NOT_REPORTED}
)


class EvidenceStatus(StrEnum):
    """Evidence/Interpretation lifecycle status (Product 8.3, 24)."""

    PROPOSED = "proposed"
    VERIFIED = "verified"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    STALE = "stale"
    SUPERSEDED = "superseded"


class VerificationVerdict(StrEnum):
    """Outcome reported by a verifier role (Product 20.4)."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ClaimType(StrEnum):
    """Claim types (Product 10.1)."""

    DESCRIPTIVE = "descriptive"
    COMPARATIVE = "comparative"
    PREVALENCE = "prevalence"
    ABSENCE = "absence"
    CAUSAL = "causal"
    TAXONOMIC = "taxonomic"
    METHODOLOGICAL = "methodological"
    SYNTHESIS = "synthesis"
    RECOMMENDATION = "recommendation"


class ClaimScope(StrEnum):
    """Claim scope ladder L0-L4 (Product 10.2), ordered by `level`.

    Comparison operators compare the ladder level, not alphabetical string order, so
    `ClaimScope.CORPUS_PATTERN < ClaimScope.FIELD_GENERALIZATION` is True.
    """

    INDIVIDUAL = "individual"
    OBSERVED_SUBSET = "observed_subset"
    CORPUS_PATTERN = "corpus_pattern"
    FIELD_GENERALIZATION = "field_generalization"
    UNIVERSAL_OR_ABSENCE = "universal_or_absence"

    @property
    def level(self) -> int:
        """Ladder level, 0 (individual) through 4 (universal/absence)."""
        return _CLAIM_SCOPE_LEVELS[self]

    @property
    def label(self) -> str:
        """Ladder label as written in Product 10.2, e.g. ``L2 corpus_pattern``."""
        return f"L{self.level} {self.value}"

    @classmethod
    def from_level(cls, level: int) -> ClaimScope:
        """Scope for a ladder level; raises ``ValueError`` outside L0-L4."""
        for scope, value in _CLAIM_SCOPE_LEVELS.items():
            if value == level:
                return scope
        raise ValueError(f"claim scope level out of range: {level}")

    def __lt__(self, other: object) -> bool:
        if isinstance(other, ClaimScope):
            return self.level < other.level
        return NotImplemented

    def __le__(self, other: object) -> bool:
        if isinstance(other, ClaimScope):
            return self.level <= other.level
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        if isinstance(other, ClaimScope):
            return self.level > other.level
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, ClaimScope):
            return self.level >= other.level
        return NotImplemented


_CLAIM_SCOPE_LEVELS: dict[ClaimScope, int] = {
    ClaimScope.INDIVIDUAL: 0,
    ClaimScope.OBSERVED_SUBSET: 1,
    ClaimScope.CORPUS_PATTERN: 2,
    ClaimScope.FIELD_GENERALIZATION: 3,
    ClaimScope.UNIVERSAL_OR_ABSENCE: 4,
}


class ClaimStatus(StrEnum):
    """Claim status (Product 10.3)."""

    UNVERIFIED = "unverified"
    SUPPORTED = "supported"
    QUALIFIED = "qualified"
    CONTESTED = "contested"
    UNSUPPORTED = "unsupported"
    SUPERSEDED = "superseded"


class ClaimEvidenceRelationType(StrEnum):
    """How one evidence object relates to a claim (Product 10.4)."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"
    CONTEXTUALIZES = "contextualizes"
    EXEMPLIFIES = "exemplifies"
    INCOMPARABLE_UNDER_CURRENT_EVIDENCE = "incomparable_under_current_evidence"


class ScreeningState(StrEnum):
    """Discovery-to-corpus screening state (Product 14)."""

    DISCOVERED = "discovered"
    SCREENED = "screened"
    INCLUDED = "included"
    EXCLUDED = "excluded"


class IdentityResolutionOutcome(StrEnum):
    """Result of resolving a candidate against the corpus (Product 13, Roadmap 2.2)."""

    SAME_ARTIFACT = "same_artifact"
    SAME_VERSION = "same_version"
    SAME_WORK = "same_work"
    DISTINCT_WORK = "distinct_work"
    UNRESOLVED = "unresolved"


class QuestionStatus(StrEnum):
    """Research question status (Product 31)."""

    OPEN = "open"
    PARTIALLY_ANSWERED = "partially_answered"
    ANSWERED = "answered"
    BLOCKED = "blocked"


class NoteStatus(StrEnum):
    """Research note status (Product 31). Notes are captured, never accepted."""

    CAPTURED = "captured"
    PROMOTED = "promoted"
    DISCARDED = "discarded"


class ReviewAction(StrEnum):
    """Human review actions (Product 24.3)."""

    ACCEPT = "accept"
    ACCEPT_WITH_QUALIFICATION = "accept_with_qualification"
    EDIT = "edit"
    REJECT = "reject"
    DEFER = "defer"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"


#: Review actions that may result in accepted state.
ACCEPTING_REVIEW_ACTIONS: frozenset[ReviewAction] = frozenset(
    {ReviewAction.ACCEPT, ReviewAction.ACCEPT_WITH_QUALIFICATION}
)


class ReviewTier(IntEnum):
    """Review tier (Product 24.1). Ordered: 0 mechanical, 1 triage, 2 deep review."""

    TIER_0 = 0
    TIER_1 = 1
    TIER_2 = 2


class ReviewPolicy(StrEnum):
    """Project review policy. `strict` is the product default (Product 24)."""

    STRICT = "strict"
    POLICY_BATCH = "policy_batch"


class DecisionType(StrEnum):
    """Researcher decision types (Product 19.2, 38)."""

    TAXONOMY_REVISION = "taxonomy_revision"
    EPISTEMIC_OVERRIDE = "epistemic_override"
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"
    METHODOLOGY = "methodology"
    OTHER = "other"


class DecisionStatus(StrEnum):
    """Decision lifecycle status."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"


class StaleState(StrEnum):
    """Dependency freshness (Product 37). Stale objects are never silently rewritten."""

    FRESH = "fresh"
    STALE = "stale"


class DocumentBlockKind(StrEnum):
    """Structural block kinds produced by the parser (Product 16)."""

    SECTION = "section"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    TABLE_CELL = "table_cell"
    FIGURE_CAPTION = "figure_caption"
    TABLE_CAPTION = "table_caption"
    EQUATION = "equation"
    REFERENCE = "reference"
    FOOTNOTE = "footnote"
    OTHER = "other"


class VersionKind(StrEnum):
    """Version kinds (Product 13)."""

    ARXIV = "arxiv"
    CAMERA_READY = "camera_ready"
    PUBLISHER = "publisher"
    AUTHOR_MANUSCRIPT = "author_manuscript"
    PREPRINT = "preprint"
    OTHER = "other"


class ArtifactKind(StrEnum):
    """Artifact kinds (Product 13)."""

    PDF = "pdf"
    HTML = "html"
    SUPPLEMENT = "supplement"
    CODE = "code"
    DATASET_DOCUMENT = "dataset_document"
    OTHER = "other"


class OverturnRisk(StrEnum):
    """Estimated risk that new evidence overturns a claim (Product 18)."""

    LOW = "low"
    LOW_MODERATE = "low_moderate"
    MODERATE = "moderate"
    HIGH = "high"
    UNKNOWN = "unknown"


class ManuscriptAnchorStatus(StrEnum):
    """Whether a manuscript anchor still resolves to its sentence (Product 30.3)."""

    VALID = "valid"
    STALE = "stale"
    MISSING = "missing"


class ManuscriptFindingKind(StrEnum):
    """Manuscript audit finding kinds (Product 30.3)."""

    UNREGISTERED_CLAIM = "unregistered_claim"
    OVER_STRONG_WORDING = "over_strong_wording"
    CITATION_MISMATCH = "citation_mismatch"
    UNSUPPORTED_NUMERIC = "unsupported_numeric"
    STALE_CLAIM = "stale_claim"
    INVALID_EVIDENCE_ANCHOR = "invalid_evidence_anchor"


class FindingSeverity(StrEnum):
    """Severity of an audit finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ResearchEventType(StrEnum):
    """Semantic events persisted in the Git-visible event log (Product 19.3).

    Prompts, latency, retrieval traces, and tool output belong in disposable
    `.research/traces/`, never here.
    """

    WORK_INGESTED = "work.ingested"
    EVIDENCE_PROPOSED = "evidence.proposed"
    EVIDENCE_ACCEPTED = "evidence.accepted"
    EVIDENCE_REJECTED = "evidence.rejected"
    CLAIM_CREATED = "claim.created"
    CLAIM_AUDITED = "claim.audited"
    CLAIM_QUALIFIED = "claim.qualified"
    TAXONOMY_REVISED = "taxonomy.revised"
    DECISION_ACCEPTED = "decision.accepted"
    DECISION_SUPERSEDED = "decision.superseded"
    MANUSCRIPT_CLAIM_ATTACHED = "manuscript.claim_attached"
    # Additional state-changing semantics used by the capability layer.
    PROJECT_INITIALIZED = "project.initialized"
    VERSION_REGISTERED = "version.registered"
    ARTIFACT_REGISTERED = "artifact.registered"
    WORK_PARSED = "work.parsed"
    EVIDENCE_VERIFIED = "evidence.verified"
    EVIDENCE_STALE = "evidence.stale"
    EVIDENCE_SUPERSEDED = "evidence.superseded"
    CLAIM_SUPERSEDED = "claim.superseded"
    CLAIM_OVERRIDDEN = "claim.overridden"
    CLAIM_RELATION_CHANGED = "claim.relation_changed"
    QUESTION_CREATED = "question.created"
    QUESTION_UPDATED = "question.updated"
    NOTE_CAPTURED = "note.captured"
    NOTE_PROMOTED = "note.promoted"
    NOTE_DISCARDED = "note.discarded"
    SEARCH_RUN_RECORDED = "search_run.recorded"
    MATRIX_BUILT = "matrix.built"
    MANUSCRIPT_ANCHOR_REVALIDATED = "manuscript.anchor_revalidated"
    MANUSCRIPT_AUDITED = "manuscript.audited"
    OBJECTS_MARKED_STALE = "state.marked_stale"
    WORK_METADATA_UPDATED = "work.metadata_updated"
    CLAIM_COVERAGE_RECORDED = "claim.coverage_recorded"


class TransitionKind(StrEnum):
    """Object kinds that have an explicit transition table in `domain.transitions`."""

    EVIDENCE = "evidence"
    CLAIM = "claim"
    DECISION = "decision"
    NOTE = "note"
    QUESTION = "question"
