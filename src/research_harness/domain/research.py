"""Questions, decisions, taxonomy, search runs, matrices, notes, and events.

Product 18 (search provenance), 19.3 (semantic events), 31 (notes/questions), 37
(staleness), and 38 (researcher overrides).
"""

from __future__ import annotations

from datetime import date

from pydantic import Field, model_validator

from research_harness.domain.base import (
    CanonicalObject,
    DomainModel,
    NonEmptyStr,
    Sha256,
    TrackedObject,
    UtcDatetime,
    utc_now,
)
from research_harness.domain.enums import (
    ClaimScope,
    DecisionStatus,
    DecisionType,
    IdentityResolutionOutcome,
    NoteStatus,
    QuestionStatus,
    ResearchEventType,
    ScreeningState,
    StaleState,
)
from research_harness.domain.ids import (
    ClaimId,
    DecisionId,
    EvidenceId,
    QuestionId,
    ResearchId,
    SearchRunId,
    SynthesisId,
    WorkId,
)
from research_harness.domain.work import WorkCandidate

__all__ = [
    "EVENT_PAYLOAD_FORBIDDEN_KEYS",
    "IDENTIFIED_WORK_OUTCOMES",
    "MAX_EVENT_OBJECT_KEYS",
    "MAX_EVENT_OBJECT_KEY_CHARS",
    "MAX_EVENT_PAYLOAD_KEYS",
    "MAX_EVENT_PAYLOAD_VALUE_CHARS",
    "Decision",
    "MatrixCell",
    "ResearchEvent",
    "ResearchNote",
    "ResearchQuestion",
    "SearchCandidate",
    "SearchResultCounts",
    "SearchRun",
    "SourceCursor",
    "SourceFailure",
    "SynthesisMatrix",
    "Taxonomy",
    "TaxonomyTerm",
]


class ResearchQuestion(CanonicalObject):
    """An active research question and everything currently bearing on it (Product 31)."""

    id: QuestionId
    question: NonEmptyStr
    status: QuestionStatus = QuestionStatus.OPEN
    claims: tuple[ClaimId, ...] = ()
    search_runs: tuple[SearchRunId, ...] = ()
    supporting_evidence: tuple[EvidenceId, ...] = ()
    counter_evidence: tuple[EvidenceId, ...] = ()
    remaining_uncertainty: str | None = None
    stale: StaleState = StaleState.FRESH


class Decision(CanonicalObject):
    """An explicit researcher choice, including taxonomy changes and overrides.

    A researcher may always overrule the auditor, but Product 38 requires the override to
    exist as a visible decision rather than an invisible edit of claim strength.
    """

    id: DecisionId
    type: DecisionType
    status: DecisionStatus = DecisionStatus.PROPOSED
    title: str | None = None
    rationale: NonEmptyStr
    claim: ClaimId | None = None
    auditor_recommendation: ClaimScope | None = None
    researcher_selected: ClaimScope | None = None
    taxonomy_terms: tuple[str, ...] = ()
    supersedes: DecisionId | None = None

    @model_validator(mode="after")
    def _type_specific_fields(self) -> Decision:
        override = self.type is DecisionType.EPISTEMIC_OVERRIDE
        scope_fields = (self.auditor_recommendation, self.researcher_selected)
        if override:
            if self.claim is None:
                raise ValueError("an epistemic_override decision must reference a claim")
            if any(value is None for value in scope_fields):
                raise ValueError(
                    "an epistemic_override decision must record auditor_recommendation "
                    "and researcher_selected"
                )
        elif any(value is not None for value in scope_fields):
            raise ValueError(
                "auditor_recommendation/researcher_selected belong to epistemic_override"
            )
        if self.type is DecisionType.TAXONOMY_REVISION and not self.taxonomy_terms:
            raise ValueError("a taxonomy_revision decision must name the taxonomy terms")
        return self


class TaxonomyTerm(DomainModel):
    """One project-approved term, and the decision that approved it."""

    term: NonEmptyStr
    parent: str | None = None
    definition: str | None = None
    decision: DecisionId | None = None


class Taxonomy(TrackedObject):
    """A project taxonomy: researcher-approved classification, not a universal fact."""

    name: NonEmptyStr
    terms: tuple[TaxonomyTerm, ...] = ()

    @model_validator(mode="after")
    def _terms_are_unique_and_rooted(self) -> Taxonomy:
        names = [term.term for term in self.terms]
        if len(names) != len(set(names)):
            raise ValueError("taxonomy terms must be unique")
        known = set(names)
        for term in self.terms:
            if term.parent is not None and term.parent not in known:
                raise ValueError(f"taxonomy term {term.term!r} has unknown parent {term.parent!r}")
        return self


class SearchResultCounts(DomainModel):
    """Discovery funnel counts for one search run (Product 18)."""

    discovered: int = Field(default=0, ge=0)
    screened: int = Field(default=0, ge=0)
    included: int = Field(default=0, ge=0)


class SourceCursor(DomainModel):
    """Where paging stopped for one source, so coverage claims stay honest."""

    source: NonEmptyStr
    query: str | None = None
    last_cursor: str | None = None
    pages_fetched: int = Field(default=0, ge=0)
    exhausted: bool = False


class SourceFailure(DomainModel):
    """A failed or incomplete source query.

    A failure is never a zero-result search: `incomplete` marks a query that returned
    some results but could not be finished.
    """

    source: NonEmptyStr
    query: str | None = None
    reason: NonEmptyStr
    incomplete: bool = False


#: Resolution outcomes that definitely identify one corpus Work (ADR-002).
IDENTIFIED_WORK_OUTCOMES: frozenset[IdentityResolutionOutcome] = frozenset(
    {
        IdentityResolutionOutcome.SAME_ARTIFACT,
        IdentityResolutionOutcome.SAME_VERSION,
        IdentityResolutionOutcome.SAME_WORK,
    }
)


class SearchCandidate(DomainModel):
    """One discovered work inside a `SearchRun`, with its screening record (Product 14).

    A candidate is discovery space, never corpus state: including one records a decision
    and nothing else, and only source acquisition followed by identity verification turns
    it into a `Work`. Two candidates that resolve to the same Work therefore stay two
    entries -- each keeps the source, rank, and provenance that reported it, and ADR-002
    keeps their Version and Artifact records separate rather than merging them into one
    paper row.
    """

    key: NonEmptyStr
    """Citation-graph node key: `doi:<doi>`, `arxiv:<base id>`, or `title:<title>|<year>`."""
    candidate: WorkCandidate
    sources: tuple[str, ...] = ()
    """Every source that reported this work, in the order they were searched."""
    ranks: dict[str, int] = Field(default_factory=dict)
    """Source -> the 1-based rank that source gave it; kept per source, never averaged."""
    screening: ScreeningState = ScreeningState.DISCOVERED
    exclusion_reason: str | None = None
    """Why this candidate was excluded. Kept for readers written before `screening_reason`."""
    screening_reason: str | None = None
    """Why this candidate was screened the way it was, whatever the decision.

    PRISMA provenance needs both halves: an inclusion is the decision a reviewer is most
    often asked to defend, and it had nowhere to be recorded (dogfood F9). An exclusion
    writes the same text into `exclusion_reason` as well, so every existing reader keeps
    working.
    """
    screened_by: str | None = None
    screened_at: UtcDatetime | None = None
    identity: IdentityResolutionOutcome | None = None
    """Outcome of resolving this candidate against the corpus; `None` before resolution."""
    matched_work: WorkId | None = None
    full_text_available: bool | None = None
    """`None` while unknown; `False` is what `SearchRun.full_text_unavailable_keys` counts."""

    @model_validator(mode="after")
    def _screening_and_identity_are_recorded(self) -> SearchCandidate:
        """Product 14: an exclusion persists its reason, and every screening names its author."""
        if self.screening is ScreeningState.EXCLUDED and not (
            self.exclusion_reason or self.screening_reason
        ):
            raise ValueError("an excluded candidate must persist a reason")
        if self.screening is not ScreeningState.EXCLUDED and self.exclusion_reason:
            raise ValueError(
                "exclusion_reason is only valid for excluded candidates; record any other "
                "screening decision's reason in screening_reason"
            )
        if self.screening is ScreeningState.DISCOVERED and self.screening_reason:
            raise ValueError("a candidate that has not been screened has no screening reason")
        if self.screening is not ScreeningState.DISCOVERED and (
            self.screened_by is None or self.screened_at is None
        ):
            raise ValueError(
                f"screening state {self.screening.value!r} must record screened_by and "
                "screened_at; a screening decision without an author is not auditable"
            )
        identity = self.identity
        if identity in IDENTIFIED_WORK_OUTCOMES and self.matched_work is None:
            raise ValueError(f"identity {identity!s} requires matched_work")
        unknown = sorted(set(self.ranks) - set(self.sources))
        if unknown:
            raise ValueError(f"ranks name sources that did not report this candidate: {unknown}")
        return self

    @property
    def reason(self) -> str | None:
        """The recorded reason for this candidate's screening decision, whichever field holds it."""
        return self.screening_reason or self.exclusion_reason

    @property
    def screened(self) -> bool:
        """True once the candidate has left `discovered` for a screening decision."""
        return self.screening is not ScreeningState.DISCOVERED

    @property
    def included(self) -> bool:
        """True when the researcher included this candidate in the corpus."""
        return self.screening is ScreeningState.INCLUDED


class SearchRun(CanonicalObject):
    """A reproducible discovery operation (Product 18, Roadmap 12.2)."""

    id: SearchRunId
    question: NonEmptyStr
    research_question: QuestionId | None = None
    sources: tuple[str, ...] = ()
    queries: tuple[str, ...] = ()
    filters: dict[str, str] = Field(default_factory=dict)
    results: SearchResultCounts = SearchResultCounts()
    executed_at: UtcDatetime = Field(default_factory=utc_now)
    cutoff: date | None = None
    cursors: tuple[SourceCursor, ...] = ()
    failures: tuple[SourceFailure, ...] = ()
    unresolved_identities: tuple[str, ...] = ()
    unavailable_full_text: tuple[WorkId, ...] = ()
    candidates: tuple[SearchCandidate, ...] = ()
    """The discovery space this run produced, deduplicated by node key across sources."""
    unresolved_keys: tuple[str, ...] = ()
    """Candidate keys identity resolution could not decide; they stay separate works."""
    full_text_unavailable_keys: tuple[str, ...] = ()
    """Candidate keys with no full text to read, so only existence can be read from them."""
    reproduces: SearchRunId | None = None
    """The run this one re-executed; a rerun is a new record, never an edit of the old one."""

    @model_validator(mode="after")
    def _counts_follow_the_recorded_candidates(self) -> SearchRun:
        """Product 18: the funnel counts are the candidates, not a number typed beside them."""
        if self.reproduces is not None and self.reproduces == self.id:
            raise ValueError("a search run cannot reproduce itself")
        if not self.candidates:
            return self
        keys = [candidate.key for candidate in self.candidates]
        if len(set(keys)) != len(keys):
            raise ValueError("a search run must not record the same candidate key twice")
        tally = SearchResultCounts(
            discovered=len(self.candidates),
            screened=sum(1 for candidate in self.candidates if candidate.screened),
            included=sum(1 for candidate in self.candidates if candidate.included),
        )
        if self.results != tally:
            raise ValueError(
                f"results {self.results.discovered}/{self.results.screened}/"
                f"{self.results.included} do not match the recorded candidates "
                f"{tally.discovered}/{tally.screened}/{tally.included} "
                "(discovered/screened/included)"
            )
        known = set(keys)
        for name, values in (
            ("unresolved_keys", self.unresolved_keys),
            ("full_text_unavailable_keys", self.full_text_unavailable_keys),
        ):
            unknown = sorted(set(values) - known)
            if unknown:
                raise ValueError(f"{name} names candidates this run did not record: {unknown}")
        return self

    def candidate(self, key: str) -> SearchCandidate | None:
        """The recorded candidate with this node key, or ``None``."""
        for candidate in self.candidates:
            if candidate.key == key:
                return candidate
        return None

    def included_candidates(self) -> tuple[SearchCandidate, ...]:
        """Candidates the researcher included, in discovery order."""
        return tuple(candidate for candidate in self.candidates if candidate.included)


class MatrixCell(DomainModel):
    """One work/field cell. Labels are multi-valued; an empty cell is not an absence."""

    work: WorkId
    field: NonEmptyStr
    labels: tuple[str, ...] = ()
    evidence: tuple[EvidenceId, ...] = ()


class SynthesisMatrix(CanonicalObject):
    """A cross-paper comparison derived from accepted state (Product 7.1, 37).

    An empty cell means "not recorded", never "the work lacks the property": novelty and
    absence claims need their own coverage and evidence.
    """

    id: SynthesisId
    name: NonEmptyStr
    taxonomy: str | None = None
    works: tuple[WorkId, ...] = ()
    fields: tuple[str, ...] = ()
    cells: tuple[MatrixCell, ...] = ()
    stale: StaleState = StaleState.FRESH

    @model_validator(mode="after")
    def _cells_reference_declared_rows(self) -> SynthesisMatrix:
        rows = set(self.works)
        seen: set[tuple[WorkId, str]] = set()
        for cell in self.cells:
            if cell.work not in rows:
                raise ValueError(f"matrix cell references undeclared work {cell.work}")
            if self.fields and cell.field not in self.fields:
                raise ValueError(f"matrix cell references undeclared field {cell.field!r}")
            key = (cell.work, cell.field)
            if key in seen:
                raise ValueError(f"duplicate matrix cell for {cell.work}/{cell.field}")
            seen.add(key)
        return self


class ResearchNote(TrackedObject):
    """Low-authority capture that may later be promoted (Product 31).

    A note has no stable research ID, no evidence relations, and no acceptance fields: it
    can never be cited as support. Promotion records the object it became.
    """

    key: str | None = None
    text: NonEmptyStr
    status: NoteStatus = NoteStatus.CAPTURED
    promoted_to: ClaimId | QuestionId | DecisionId | None = None

    @model_validator(mode="after")
    def _promotion_is_recorded(self) -> ResearchNote:
        if self.status is NoteStatus.PROMOTED and self.promoted_to is None:
            raise ValueError("a promoted note must record what it was promoted to")
        if self.status is not NoteStatus.PROMOTED and self.promoted_to is not None:
            raise ValueError("promoted_to is only valid for promoted notes")
        return self


MAX_EVENT_PAYLOAD_KEYS = 32
MAX_EVENT_PAYLOAD_VALUE_CHARS = 512
MAX_EVENT_OBJECT_KEYS = 10_000
MAX_EVENT_OBJECT_KEY_CHARS = 200
EVENT_PAYLOAD_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "chain_of_thought",
        "completion",
        "messages",
        "prompt",
        "prompts",
        "raw_response",
        "reasoning",
        "system_prompt",
        "thinking",
        "tool_output",
        "trace",
    }
)


class ResearchEvent(DomainModel):
    """A semantic state change for the Git-visible event log (Product 19.3).

    Events are an audit companion, not a second scientific authority. The payload holds
    ids and small scalar values only: prompts, hidden reasoning, and raw tool output
    belong in disposable `.research/traces/`.

    `objects` is the event's account of what it wrote: object key -> digest of that
    object's canonical YAML *after* the mutation. It is a field of its own rather than
    payload entries so that recording a large mutation never competes with the payload
    budget the audit narrative needs.
    """

    schema_version: int = Field(default=1, ge=1)
    event: ResearchEventType
    subjects: tuple[ResearchId, ...] = ()
    actor: NonEmptyStr
    occurred_at: UtcDatetime = Field(default_factory=utc_now)
    summary: NonEmptyStr
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    objects: dict[str, Sha256] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _payload_is_small_and_not_a_trace(self) -> ResearchEvent:
        if len(self.payload) > MAX_EVENT_PAYLOAD_KEYS:
            raise ValueError(f"event payload holds at most {MAX_EVENT_PAYLOAD_KEYS} keys")
        for key, value in self.payload.items():
            if key.lower() in EVENT_PAYLOAD_FORBIDDEN_KEYS:
                raise ValueError(f"event payload must not carry {key!r}; use .research/traces/")
            if isinstance(value, str) and len(value) > MAX_EVENT_PAYLOAD_VALUE_CHARS:
                raise ValueError(
                    f"event payload value {key!r} exceeds "
                    f"{MAX_EVENT_PAYLOAD_VALUE_CHARS} characters"
                )
        return self

    @model_validator(mode="after")
    def _object_digests_stay_a_bounded_index(self) -> ResearchEvent:
        if len(self.objects) > MAX_EVENT_OBJECT_KEYS:
            raise ValueError(f"an event records at most {MAX_EVENT_OBJECT_KEYS} object digests")
        for key in self.objects:
            if not key:
                raise ValueError("an object digest key must not be empty")
            if len(key) > MAX_EVENT_OBJECT_KEY_CHARS:
                raise ValueError(
                    f"object digest key {key[:40]!r} exceeds "
                    f"{MAX_EVENT_OBJECT_KEY_CHARS} characters"
                )
        return self
