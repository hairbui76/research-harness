"""The Review Inbox: what a researcher is asked to look at, and in which order.

Product §24.2 fixes the order — conflicts, then high-risk scientific claims, then stale
high-impact objects, then ambiguous extractions, then routine verified candidates — because
researcher attention is the scarce resource (§5 P8) and review fatigue is the named risk
(§43). Ordering by anything else spends that attention on the items least likely to change
a conclusion.

Every classification here is deterministic and reconstructible from staging plus canonical
state: a verdict, an anchor replay, a competing candidate, an accepted object with the same
anchor, a recorded rejection, a provider conflict. **Model confidence appears nowhere** —
not as a field, not as a tie-break, not as a reason (§24.4, §43). Nothing in this module
writes anything: building an inbox is a read, and acceptance happens in `evidence/service.py`
through the capability layer.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from research_harness.domain.document import BoundingBox, DocumentBlock, ParsedDocument
from research_harness.domain.enums import (
    EvidenceStatus,
    NoteStatus,
    QuestionStatus,
    ResearchEventType,
    ReviewTier,
    StaleState,
    VerificationVerdict,
)
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import ArtifactId, EvidenceId, WorkId
from research_harness.evidence.conflicts import (
    ConflictKind,
    ConflictRecord,
    inferred_field,
    load_conflict_records,
    values_conflict,
)
from research_harness.evidence.interrogation import (
    InterrogationField,
    InterrogationSchema,
    UnknownFieldError,
)
from research_harness.evidence.staging import CandidateStatus, EvidenceCandidate, StagingStore
from research_harness.evidence.verification import DEFAULT_NEIGHBOURS, context_blocks
from research_harness.parsing.anchors import (
    AnchorValidationStatus,
    anchor_fingerprint,
    validate_anchor,
)
from research_harness.parsing.text import normalize_text
from research_harness.providers.models.cross_verify import ProviderConflict
from research_harness.workspace.rejections import RejectionRecord
from research_harness.workspace.repository import WorkspaceRepository

logger = logging.getLogger(__name__)

__all__ = [
    "CATEGORY_ORDER",
    "CONFLICTS_DIRNAME",
    "REVIEWABLE_STATUSES",
    "ReviewCategory",
    "ReviewItem",
    "ReviewQueue",
    "SessionSummary",
    "SourceContext",
    "build_inbox",
    "load_conflict_records",
    "load_provider_conflicts",
    "session_summary",
    "stored_document",
    "stored_documents",
]

CONFLICTS_DIRNAME = "staging/conflicts"
"""Where cross-model verification drops `ProviderConflict` JSON, under `.research/`."""

#: Candidate states the inbox asks about. A `reviewed` candidate has had its answer and a
#: candidate marked `invalid` has no usable anchor; both stay on disk as history.
REVIEWABLE_STATUSES: frozenset[CandidateStatus] = frozenset(
    {CandidateStatus.PROPOSED, CandidateStatus.VERIFIED}
)

_AMBIGUOUS_VERDICTS: frozenset[VerificationVerdict] = frozenset(
    {VerificationVerdict.PARTIALLY_SUPPORTED, VerificationVerdict.INSUFFICIENT_EVIDENCE}
)

_CLAIM_EVENTS: frozenset[ResearchEventType] = frozenset(
    {
        ResearchEventType.CLAIM_CREATED,
        ResearchEventType.CLAIM_AUDITED,
        ResearchEventType.CLAIM_QUALIFIED,
        ResearchEventType.CLAIM_OVERRIDDEN,
        ResearchEventType.CLAIM_SUPERSEDED,
    }
)

_OPEN_QUESTION_STATES: frozenset[QuestionStatus] = frozenset(
    {QuestionStatus.OPEN, QuestionStatus.PARTIALLY_ANSWERED, QuestionStatus.BLOCKED}
)


class ReviewCategory(StrEnum):
    """Why an item is in the queue, in the priority order of Product §24.2."""

    CONFLICT = "conflict"
    HIGH_RISK = "high_risk"
    STALE = "stale"
    AMBIGUOUS = "ambiguous"
    ROUTINE = "routine"


CATEGORY_ORDER: tuple[ReviewCategory, ...] = (
    ReviewCategory.CONFLICT,
    ReviewCategory.HIGH_RISK,
    ReviewCategory.STALE,
    ReviewCategory.AMBIGUOUS,
    ReviewCategory.ROUTINE,
)
"""The queue order itself; an item's `priority` is its index here."""

_PRIORITY: Mapping[ReviewCategory, int] = {
    category: index for index, category in enumerate(CATEGORY_ORDER)
}


@dataclass(frozen=True, slots=True)
class SourceContext:
    """What the reviewer needs beside the decision: the span and the text around it.

    Product §25 asks for source context, candidate values, and competing interpretations on
    the same screen, so a Tier-1 judgement costs a glance rather than a document hunt.
    """

    page: int | None
    section_path: tuple[str, ...]
    block_text: str
    exact_text: str
    bbox: BoundingBox | None = None
    neighbors: tuple[str, ...] = ()
    """Text of the blocks either side of the anchored one, in reading order."""

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "page": self.page,
            "section_path": list(self.section_path),
            "block_text": self.block_text,
            "exact_text": self.exact_text,
            "bbox": None if self.bbox is None else list(self.bbox.as_tuple()),
            "neighbors": list(self.neighbors),
        }


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """One staged candidate as the inbox presents it, with every reason it is here."""

    candidate: EvidenceCandidate
    category: ReviewCategory
    priority: int
    reasons: tuple[str, ...]
    source_context: SourceContext
    anchor_status: AnchorValidationStatus
    competing: tuple[str, ...] = ()
    """Other staged candidate ids answering the same field for the same Work."""

    previously_rejected: bool = False
    accepted_conflict: EvidenceId | None = None
    """Accepted Evidence anchored at the same span that says something else."""

    provider_conflict: ProviderConflict | None = None
    conflict_records: tuple[ConflictRecord, ...] = ()
    """Open `ConflictRecord`s materialized about this candidate, oldest first (Task 13.2)."""

    proposed_changes: tuple[dict[str, Any], ...] = ()
    """The diff Product §25 asks for: what each competing position would change."""

    @property
    def candidate_id(self) -> str:
        return self.candidate.candidate_id

    @property
    def work(self) -> WorkId:
        return self.candidate.work

    @property
    def tier(self) -> ReviewTier:
        return ReviewTier(self.candidate.review_tier)

    @property
    def verdict(self) -> str | None:
        """The verifier's verdict, or None while unverified."""
        return self.candidate.verdict

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form for `--json` and for transports."""
        content = self.candidate.evidence.content
        return {
            "candidate_id": self.candidate_id,
            "work": str(self.work),
            "artifact": str(self.candidate.artifact),
            "field": self.candidate.field,
            "category": self.category.value,
            "priority": self.priority,
            "reasons": list(self.reasons),
            "tier": int(self.tier),
            "origin": self.candidate.evidence.origin.value,
            "evidence_type": self.candidate.evidence.evidence_type.value,
            "verdict": self.verdict,
            "anchor_status": self.anchor_status.value,
            "exact_text": content.exact_text,
            "numeric": None if content.numeric is None else content.numeric.model_dump(mode="json"),
            "negative_state": None
            if content.negative_state is None
            else content.negative_state.value,
            "review_action": None
            if self.candidate.review_action is None
            else self.candidate.review_action.value,
            "competing": list(self.competing),
            "previously_rejected": self.previously_rejected,
            "accepted_conflict": None
            if self.accepted_conflict is None
            else str(self.accepted_conflict),
            "provider_conflict": None
            if self.provider_conflict is None
            else self.provider_conflict.model_dump(mode="json"),
            "conflicts": [record.as_dict() for record in self.conflict_records],
            "proposed_changes": [dict(change) for change in self.proposed_changes],
            "source_context": self.source_context.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class ReviewQueue:
    """The inbox: items already in priority order, plus the counts a session view needs."""

    items: tuple[ReviewItem, ...] = ()
    conflicts: tuple[ConflictRecord, ...] = ()
    """Every open `ConflictRecord`, including those about a claim with no staged candidate."""

    @property
    def counts(self) -> dict[ReviewCategory, int]:
        """How many items sit in each category, zeros included, in queue order."""
        tally = dict.fromkeys(CATEGORY_ORDER, 0)
        for item in self.items:
            tally[item.category] += 1
        return tally

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[ReviewItem]:
        return iter(self.items)

    def next(self) -> ReviewItem | None:
        """The item to review now: the highest-priority one, or None when the queue is empty."""
        return self.items[0] if self.items else None

    def by_id(self, candidate_id: str) -> ReviewItem | None:
        """One item by staging id, or None when it is not in the queue."""
        return next((item for item in self.items if item.candidate_id == candidate_id), None)

    def by_category(self, category: ReviewCategory) -> tuple[ReviewItem, ...]:
        """Every item in one category, in queue order."""
        return tuple(item for item in self.items if item.category is category)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "count": len(self.items),
            "counts": {category.value: count for category, count in self.counts.items()},
            "items": [item.as_dict() for item in self.items],
            "conflicts": [record.as_dict() for record in self.conflicts],
        }


# --------------------------------------------------------------------------- parses


def stored_document(
    repo: WorkspaceRepository, work: WorkId, artifact: ArtifactId
) -> ParsedDocument | None:
    """Rebuild a document from the Work's stored blocks so anchors replay without a parser.

    The repository owns the reconstruction (`WorkspaceRepository.get_parsed_document`); this
    stays as the name the review code has always called, in the argument order it uses.
    """
    return repo.get_parsed_document(artifact, work=work)


def stored_documents(
    repo: WorkspaceRepository, works: Iterable[WorkId]
) -> dict[ArtifactId, ParsedDocument]:
    """Every artifact of every named Work, rebuilt from stored blocks."""
    documents: dict[ArtifactId, ParsedDocument] = {}
    for work in works:
        for artifact in repo.list_artifacts(work):
            document = stored_document(repo, work, artifact.id)
            if document is not None:
                documents[artifact.id] = document
    return documents


def load_provider_conflicts(directory: Path) -> list[ProviderConflict]:
    """Read `ProviderConflict` JSON files a cross-verification run left behind.

    Unreadable files are logged and skipped rather than raising: a disposable file under
    `.research/` must never stop a researcher from seeing the rest of their queue.
    """
    if not directory.is_dir():
        return []
    conflicts: list[ProviderConflict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            conflicts.append(ProviderConflict.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, ValidationError, ValueError) as exc:
            logger.warning("ignoring unreadable provider conflict %s: %s", path, exc)
    return conflicts


# ------------------------------------------------------------------------ the inbox


def build_inbox(
    staging: StagingStore,
    repo: WorkspaceRepository,
    *,
    work: WorkId | None = None,
    parsed: Mapping[ArtifactId, ParsedDocument] | None = None,
    conflicts_dir: Path | None = None,
    schema: InterrogationSchema | None = None,
) -> ReviewQueue:
    """The review queue for one Work or the whole workspace, in Product §24.2 order.

    `parsed` supplies documents to replay anchors against; without it an item keeps the
    anchor status extraction recorded, which is the status at proposal time rather than now.
    Passing :func:`stored_documents` is the cheap way to get the current one.

    `schema` is the interrogation contract the candidates were extracted against, used to
    decide whether two answers to one field compete. A staged candidate records the field's
    name but not the schema that asked it, so without one the contract is reconstructed from
    the candidate (`conflicts.inferred_field`) — a caller that knows the schema should pass
    it, because a plugin's multi-label categorical field cannot be recognised otherwise.
    """
    candidates = [
        candidate
        for candidate in staging.list(work=work)
        if candidate.status in REVIEWABLE_STATUSES
    ]
    documents = dict(parsed or {})
    directory = (
        conflicts_dir
        if conflicts_dir is not None
        else staging.research_dir / Path(CONFLICTS_DIRNAME)
    )
    conflicts = load_provider_conflicts(directory)
    records = load_conflict_records(directory, status="open")
    works = {candidate.work for candidate in candidates}
    accepted = {name: _accepted_by_anchor(repo, name) for name in works}
    rejected = {name: tuple(_rejections(repo, name)) for name in works}

    peers = _PeerIndex.build(candidates)
    items = [
        _build_item(
            candidate,
            peers=peers,
            position=position,
            document=documents.get(candidate.artifact),
            accepted=accepted[candidate.work],
            rejected=rejected[candidate.work],
            conflicts=conflicts,
            records=records,
            schema=schema,
        )
        for position, candidate in enumerate(candidates)
    ]
    return ReviewQueue(items=tuple(sorted(items, key=_queue_key)), conflicts=tuple(records))


def _queue_key(item: ReviewItem) -> tuple[int, int, str, str]:
    """Category first, then the deeper review, then the older candidate."""
    return (
        item.priority,
        -int(item.tier),
        item.candidate.created_at.isoformat(),
        item.candidate_id,
    )


@dataclass(frozen=True, slots=True)
class _PeerIndex:
    """The peer relations `_build_item` needs, computed once for the whole candidate list.

    Both relations a candidate has with its peers — *competing* (same work and field) and
    *disagreeing* (competing, and reading the span differently) — used to be recomputed by
    scanning every peer for every candidate, which made the inbox quadratic and normalized
    each candidate's text once per peer. Bucketing by `(work, field)` and keying the
    normalized value once per candidate answers both in the order the scan produced,
    which is the order Product §24.2 sorting then consumes.
    """

    ids: tuple[str, ...]
    value_keys: tuple[tuple[str, str, str], ...]
    buckets: Mapping[tuple[str, str], tuple[int, ...]]
    positions_by_id: Mapping[str, tuple[int, ...]]
    candidates: tuple[EvidenceCandidate, ...] = ()
    """The candidates themselves, so a peer that differs can be *judged* and not only named."""

    @classmethod
    def build(cls, candidates: Sequence[EvidenceCandidate]) -> _PeerIndex:
        buckets: dict[tuple[str, str], list[int]] = {}
        positions: dict[str, list[int]] = {}
        for position, candidate in enumerate(candidates):
            buckets.setdefault((str(candidate.work), candidate.field), []).append(position)
            positions.setdefault(candidate.candidate_id, []).append(position)
        return cls(
            ids=tuple(candidate.candidate_id for candidate in candidates),
            value_keys=tuple(_value_key(candidate) for candidate in candidates),
            buckets={key: tuple(value) for key, value in buckets.items()},
            positions_by_id={key: tuple(value) for key, value in positions.items()},
            candidates=tuple(candidates),
        )

    def candidate_for(self, candidate_id: str) -> EvidenceCandidate:
        """The candidate behind a peer id, for the value judgement `_build_item` makes."""
        return self.candidates[self.positions_by_id[candidate_id][0]]

    def relations(
        self, position: int, key: tuple[str, str]
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """``(competing, disagreeing)`` candidate ids for the candidate at ``position``.

        ``disagreeing`` is resolved through `positions_by_id` rather than the bucket, because
        two Works may stage the same content-addressed candidate id and the original scan
        matched peers by id alone.
        """
        own_id = self.ids[position]
        bucket = self.buckets[key]
        competing = tuple(self.ids[peer] for peer in bucket if self.ids[peer] != own_id)
        if not competing:
            return (), ()
        own_value = self.value_keys[position]
        matching = {peer for name in set(competing) for peer in self.positions_by_id[name]}
        disagreeing = tuple(
            self.ids[peer] for peer in sorted(matching) if self.value_keys[peer] != own_value
        )
        return competing, disagreeing


def _build_item(
    candidate: EvidenceCandidate,
    *,
    peers: _PeerIndex,
    position: int,
    document: ParsedDocument | None,
    accepted: Mapping[str, Evidence],
    rejected: Sequence[RejectionRecord],
    conflicts: Sequence[ProviderConflict],
    records: Sequence[ConflictRecord] = (),
    schema: InterrogationSchema | None = None,
) -> ReviewItem:
    anchor_status, anchor_reason = _anchor_state(candidate, document)
    value_key = peers.value_keys[position]
    competing, differing = peers.relations(position, (str(candidate.work), candidate.field))
    disagreeing, judgement = _judged_peers(candidate, differing, peers=peers, schema=schema)
    accepted_conflict = _accepted_conflict(candidate, accepted, value_key=value_key)
    previous = _previous_rejection(candidate, rejected)
    mine = _records_for(candidate, records)
    conflict = _provider_conflict(candidate, conflicts) or _first_provider_record(mine)
    category, reasons = _classify(
        candidate,
        anchor_status=anchor_status,
        anchor_reason=anchor_reason,
        disagreeing=disagreeing,
        differing=differing,
        judgement=judgement,
        competing=competing,
        accepted_conflict=accepted_conflict,
        provider_conflict=conflict,
        records=mine,
    )
    if previous is not None:
        reasons = (*reasons, f"an identical span was previously rejected: {previous.reason}")
    return ReviewItem(
        candidate=candidate,
        category=category,
        priority=_PRIORITY[category],
        reasons=reasons,
        source_context=_source_context(candidate, document),
        anchor_status=anchor_status,
        competing=competing,
        previously_rejected=previous is not None,
        accepted_conflict=accepted_conflict,
        provider_conflict=conflict,
        conflict_records=mine,
        proposed_changes=tuple(change for record in mine for change in record.proposed_changes),
    )


def _judged_peers(
    candidate: EvidenceCandidate,
    differing: Sequence[str],
    *,
    peers: _PeerIndex,
    schema: InterrogationSchema | None,
) -> tuple[tuple[str, ...], str]:
    """Which peers with another value actually compete, and the reason the judge gave.

    Answering a field twice is not a disagreement by itself:
    :func:`~research_harness.evidence.conflicts.values_conflict` decides, and the reason it
    returns is carried into the item so a researcher reads *why* rather than a count. The
    contract is only reconstructed when there is something to judge, so a queue of items with
    no peers costs nothing (dogfood F7).
    """
    if not differing:
        return (), ""
    contract = _field_contract(candidate, schema)
    conflicting: list[str] = []
    competing_reasons: list[str] = []
    benign_reasons: list[str] = []
    for peer_id in differing:
        judgement = values_conflict(contract, candidate, peers.candidate_for(peer_id))
        if judgement.conflict:
            conflicting.append(peer_id)
            competing_reasons.append(judgement.reason)
        else:
            benign_reasons.append(judgement.reason)
    spoken = competing_reasons if conflicting else benign_reasons
    return tuple(conflicting), "; ".join(dict.fromkeys(spoken))


def _field_contract(
    candidate: EvidenceCandidate, schema: InterrogationSchema | None
) -> InterrogationField:
    """The interrogation field this candidate answers: the schema's, or one inferred."""
    if schema is not None:
        try:
            return schema.field(candidate.field)
        except UnknownFieldError:
            logger.debug("schema %s does not ask %r", schema.name, candidate.field)
    return inferred_field(candidate)


def _classify(
    candidate: EvidenceCandidate,
    *,
    anchor_status: AnchorValidationStatus,
    anchor_reason: str,
    disagreeing: Sequence[str],
    competing: Sequence[str],
    accepted_conflict: EvidenceId | None,
    provider_conflict: ProviderConflict | None,
    records: Sequence[ConflictRecord] = (),
    differing: Sequence[str] = (),
    judgement: str = "",
) -> tuple[ReviewCategory, tuple[str, ...]]:
    """The highest-priority category this candidate falls in, and why.

    Categories are tested in queue order, so a conflicted Tier-2 numeric candidate is a
    conflict rather than a high-risk item: the disagreement is the thing to look at first.

    `differing` is every peer answering the same field with another value; `disagreeing` is
    the subset :func:`~research_harness.evidence.conflicts.values_conflict` judged to be
    competing. The two are not the same set, and treating them as one is what made 89% of a
    real conflict queue noise (dogfood F7): several answers to a multi-valued field are
    additional answers, and the item stays at the priority its own tier earns.
    """
    evidence = candidate.evidence
    content = evidence.content
    verdict = None if candidate.verification is None else candidate.verification.verdict

    conflict: list[str] = []
    if verdict is VerificationVerdict.CONTRADICTED:
        conflict.append("the verifier contradicted this candidate")
    if accepted_conflict is not None:
        conflict.append(f"accepted evidence {accepted_conflict} reads the same span differently")
    if provider_conflict is not None:
        fields = ", ".join(provider_conflict.differing_fields)
        conflict.append(f"providers disagree on {fields}")
    conflict.extend(
        f"open {record.kind.value} conflict {record.conflict_id}"
        for record in records
        if record.kind is not ConflictKind.PROVIDER_DISAGREEMENT
    )
    if disagreeing:
        detail = f": {judgement}" if judgement else ""
        conflict.append(
            f"{len(disagreeing)} competing candidate(s) propose a different value for "
            f"field {candidate.field!r}{detail}"
        )
    if conflict:
        return ReviewCategory.CONFLICT, tuple(conflict)

    high_risk: list[str] = []
    if evidence.review_tier is ReviewTier.TIER_2:
        high_risk.append("tier 2: an interpretive judgement needs deep review")
    if content.numeric is not None:
        high_risk.append(
            f"numeric evidence: {content.numeric.metric} carries unit, dataset, and condition"
        )
    if content.negative_state is not None:
        high_risk.append(f"records absence as {content.negative_state.value!r}")
    if evidence.is_interpretive and evidence.review_tier is not ReviewTier.TIER_2:
        high_risk.append(f"origin {evidence.origin.value!r} is interpretive")
    if high_risk:
        return ReviewCategory.HIGH_RISK, tuple(high_risk)

    if anchor_status is not AnchorValidationStatus.VALID:
        return ReviewCategory.STALE, (f"anchor is {anchor_status.value}: {anchor_reason}",)

    ambiguous: list[str] = []
    if verdict is None:
        ambiguous.append("no independent verification result yet")
    elif verdict in _AMBIGUOUS_VERDICTS:
        ambiguous.append(f"the verifier reported {verdict.value}")
    if ambiguous:
        return ReviewCategory.AMBIGUOUS, tuple(ambiguous)

    reasons = [
        f"verified {VerificationVerdict.SUPPORTED.value}, tier {int(evidence.review_tier)}, "
        "anchor valid"
    ]
    if differing:
        detail = f": {judgement}" if judgement else ""
        reasons.append(
            f"{len(differing)} other candidate(s) answer field {candidate.field!r} "
            f"without competing{detail}"
        )
    agreeing = len(competing) - len(differing)
    if agreeing > 0:
        reasons.append(f"{agreeing} candidate(s) agree on field {candidate.field!r}")
    return ReviewCategory.ROUTINE, tuple(reasons)


# --------------------------------------------------------------------------- signals


def _anchor_state(
    candidate: EvidenceCandidate, document: ParsedDocument | None
) -> tuple[AnchorValidationStatus, str]:
    """The anchor's status now, replayed against the document when one is available."""
    if document is None:
        return candidate.anchor_status, "anchor status recorded when the candidate was proposed"
    result = validate_anchor(candidate.evidence.source, document)
    return result.status, result.reason


def _value_key(candidate: EvidenceCandidate) -> tuple[str, str, str]:
    """What two candidates for one field have to agree on to not be a conflict.

    Compared on normalized text so a line break is not a disagreement, and on the parsed
    number rather than its raw string so `94.32` and `94.320` are the same measurement.
    """
    content = candidate.evidence.content
    numeric = (
        ""
        if content.numeric is None
        else f"{content.numeric.metric}:{content.numeric.parsed!r}:{content.numeric.dataset or ''}"
    )
    negative = "" if content.negative_state is None else content.negative_state.value
    return (normalize_text(content.exact_text), numeric, negative)


def _accepted_by_anchor(repo: WorkspaceRepository, work: WorkId) -> dict[str, Evidence]:
    """Accepted Evidence for a Work, keyed by anchor fingerprint."""
    return {
        anchor_fingerprint(record.source): record
        for record in repo.iter_evidence(work)
        if record.status is EvidenceStatus.ACCEPTED
    }


def _accepted_conflict(
    candidate: EvidenceCandidate,
    accepted: Mapping[str, Evidence],
    *,
    value_key: tuple[str, str, str] | None = None,
) -> EvidenceId | None:
    """Accepted Evidence at the same span whose content differs (Product §25).

    ``value_key`` lets a caller that already normalized the candidate's text pass it in
    rather than paying for the normalization a second time.
    """
    existing = accepted.get(anchor_fingerprint(candidate.evidence.source))
    if existing is None:
        return None
    if _content_key(existing) == (_value_key(candidate) if value_key is None else value_key):
        return None
    return existing.id


def _content_key(evidence: Evidence) -> tuple[str, str, str]:
    content = evidence.content
    numeric = (
        ""
        if content.numeric is None
        else f"{content.numeric.metric}:{content.numeric.parsed!r}:{content.numeric.dataset or ''}"
    )
    negative = "" if content.negative_state is None else content.negative_state.value
    return (normalize_text(content.exact_text), numeric, negative)


def _rejections(repo: WorkspaceRepository, work: WorkId) -> Iterator[RejectionRecord]:
    try:
        yield from repo.iter_rejections(work)
    except OSError as exc:  # pragma: no cover - an unreadable file is reported, not fatal
        logger.warning("cannot read rejections for %s: %s", work, exc)


def _previous_rejection(
    candidate: EvidenceCandidate, rejected: Sequence[RejectionRecord]
) -> RejectionRecord | None:
    """The newest rejection of this same proposal, matched by staging id or by anchor.

    Staging is disposable, so the id alone is not enough: after a rebuild the same span comes
    back with the same content-addressed id, but an edited schema or a re-parse can change it
    while the span stays the same. The anchor is the durable identity.
    """
    fingerprint = anchor_fingerprint(candidate.evidence.source)
    text_hash = candidate.evidence.source.text_hash
    matches = [
        record
        for record in rejected
        if record.candidate_id == candidate.candidate_id
        or anchor_fingerprint(record.anchor) == fingerprint
        or (record.text_hash == text_hash and record.field == candidate.field)
    ]
    return max(matches, key=lambda record: record.rejected_at) if matches else None


def _subjects_of(candidate: EvidenceCandidate) -> frozenset[str]:
    """Every name a conflict may have been recorded against this candidate under."""
    return frozenset(
        {
            candidate.candidate_id,
            str(candidate.evidence.id),
            candidate.field,
            f"{candidate.work}/{candidate.field}",
        }
    )


def _provider_conflict(
    candidate: EvidenceCandidate, conflicts: Sequence[ProviderConflict]
) -> ProviderConflict | None:
    """The recorded provider disagreement about this candidate, if one exists."""
    subjects = _subjects_of(candidate)
    return next((conflict for conflict in conflicts if conflict.subject in subjects), None)


def _records_for(
    candidate: EvidenceCandidate, records: Sequence[ConflictRecord]
) -> tuple[ConflictRecord, ...]:
    """The open conflict records materialized about this candidate, oldest first."""
    subjects = _subjects_of(candidate)
    return tuple(record for record in records if record.subject in subjects)


def _first_provider_record(records: Sequence[ConflictRecord]) -> ProviderConflict | None:
    """The `ProviderConflict` view of the first provider disagreement among these records.

    Lets a materialized record reach every reader that already speaks `ProviderConflict` —
    the inbox reasons, the CLI, the transports — without any of them learning a new type.
    """
    for record in records:
        conflict = record.as_provider_conflict()
        if conflict is not None:
            return conflict
    return None


def _source_context(candidate: EvidenceCandidate, document: ParsedDocument | None) -> SourceContext:
    """The span and its neighbours; anchor coordinates alone when there is no parse."""
    anchor = candidate.evidence.source
    exact_text = candidate.evidence.content.exact_text
    if document is None:
        return SourceContext(
            page=anchor.page,
            section_path=anchor.section_path,
            block_text="",
            exact_text=exact_text,
            bbox=anchor.bbox,
        )
    blocks = context_blocks(document, candidate, neighbors=DEFAULT_NEIGHBOURS)
    anchored = next((block for block in blocks if block.id == anchor.block), None)
    return SourceContext(
        page=anchored.page if anchored else anchor.page,
        section_path=anchored.section_path if anchored else anchor.section_path,
        block_text=anchored.text if anchored else "",
        exact_text=exact_text,
        bbox=(anchored.bbox if anchored else None) or anchor.bbox,
        neighbors=tuple(_block_text(block) for block in blocks if block.id != anchor.block),
    )


def _block_text(block: DocumentBlock) -> str:
    return f"{block.text}\n{block.caption}" if block.caption else block.text


# -------------------------------------------------------------------- session summary


@dataclass(frozen=True, slots=True)
class SessionSummary:
    """What a working session left behind (Product §39).

    Counted from the event log, staging, and canonical state, so it is honest about the
    whole workspace rather than about one process: the harness has no session boundary and
    inventing one would make the numbers depend on when the CLI happened to be started.
    """

    added: int
    """Candidates currently staged — what interrogation put in front of the researcher."""

    unreviewed: int
    conflicts: int
    stale: int
    """Inbox items whose anchor no longer replays, plus accepted Evidence flagged stale."""

    claims_changed: int
    open_questions: int
    notes: int = 0
    accepted: int = 0
    rejected: int = 0

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "added": self.added,
            "unreviewed": self.unreviewed,
            "conflicts": self.conflicts,
            "stale": self.stale,
            "claims_changed": self.claims_changed,
            "open_questions": self.open_questions,
            "notes": self.notes,
            "accepted": self.accepted,
            "rejected": self.rejected,
        }


def session_summary(repo: WorkspaceRepository, staging: StagingStore) -> SessionSummary:
    """The end-of-session view Product §39 asks for: added, unreviewed, conflicts, stale.

    Best effort by construction — the event log is an audit companion, not a state machine —
    and cheap enough to print after every command that changes something.
    """
    queue = build_inbox(staging, repo, parsed=stored_documents(repo, staging.works()))
    counts = queue.counts
    works = repo.list_works()
    accepted_stale = sum(
        1
        for work in works
        for record in repo.iter_evidence(work.id)
        if record.stale is StaleState.STALE
    )
    accepted = sum(
        1
        for work in works
        for record in repo.iter_evidence(work.id)
        if record.status is EvidenceStatus.ACCEPTED
    )
    rejected = sum(1 for work in works for _ in repo.iter_rejections(work.id))
    claims_changed = sum(1 for event in repo.iter_events() if event.event in _CLAIM_EVENTS)
    return SessionSummary(
        added=len(staging.list()),
        unreviewed=len(queue),
        conflicts=counts[ReviewCategory.CONFLICT],
        stale=counts[ReviewCategory.STALE] + accepted_stale,
        claims_changed=claims_changed,
        open_questions=sum(
            1 for question in repo.list_questions() if question.status in _OPEN_QUESTION_STATES
        ),
        notes=sum(1 for note in repo.iter_notes() if note.status is NoteStatus.CAPTURED),
        accepted=accepted,
        rejected=rejected,
    )
