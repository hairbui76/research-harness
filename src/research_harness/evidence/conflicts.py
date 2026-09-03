"""Conflicts as objects: what the system disagrees about, kept until a person decides.

Product §25 puts disagreement first, and names six kinds of it — extractor versus verifier,
provider A versus provider B, candidate versus accepted state, new evidence versus an
existing Claim, a revised paper version versus an existing anchor, and a taxonomy revision
versus the classifications that depend on it. :class:`ConflictKind` is that list, and
:class:`ConflictRecord` is one of them made durable enough to route, review, and resolve.

Three rules hold for every record here.

**Nothing is merged and nothing wins by default.** A record keeps every position side by
side, names the fields they differ on, and carries the diff of the state changes each
position would make. It records no winner, and no code in this module or downstream of it
picks one (ROADMAP Gate P13).

**Resolution is a human act.** :meth:`ConflictStore.resolve` refuses any actor that is not
the researcher, and :class:`ConflictResolution` refuses to be constructed with one. A
verdict, a majority of providers, or a later run cannot close a conflict.

**A conflict record is regenerable runtime state.** Records live under
``.research/staging/conflicts/<subject>/<conflict_id>.json``, are written atomically, and
carry no scientific authority: deleting the tree loses the queue, never a conclusion
(ADR-001, ADR-003). Conflict ids are content-addressed, so re-running the workflow that
found a disagreement re-derives the same id and produces one conflict rather than a pile of
duplicates — and :meth:`ConflictStore.open_or_put` will not reopen one already resolved.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from research_harness.domain.base import DomainModel, NonEmptyStr, UtcDatetime, utc_now
from research_harness.domain.enums import ReviewTier, VerificationVerdict
from research_harness.domain.errors import AuthorityError, ResearchHarnessError
from research_harness.domain.evidence import Evidence, NumericValue
from research_harness.domain.transitions import is_human_actor
from research_harness.evidence.interrogation import InterrogationField, ValueKind
from research_harness.evidence.staging import EvidenceCandidate
from research_harness.parsing.anchors import anchor_fingerprint
from research_harness.parsing.text import normalize_text
from research_harness.providers.models.base import canonical_json
from research_harness.providers.models.cross_verify import (
    CrossVerification,
    CrossVerificationGate,
    ProviderConflict,
    ProviderPosition,
)
from research_harness.workspace.atomic import atomic_write_text, clean_partials

logger = logging.getLogger(__name__)

__all__ = [
    "CONFLICT_ID_PATTERN",
    "LIST_LIKE_FIELD_WORDS",
    "SEVERAL_ANSWERS_PHRASES",
    "STAGING_CONFLICTS_DIRNAME",
    "ConflictChoice",
    "ConflictError",
    "ConflictJudgement",
    "ConflictKind",
    "ConflictNotFoundError",
    "ConflictRecord",
    "ConflictResolution",
    "ConflictStatus",
    "ConflictStore",
    "conflict_id_for",
    "inferred_field",
    "is_multi_valued",
    "load_conflict_records",
    "materialize_candidate_vs_accepted_conflict",
    "materialize_extractor_verifier_conflict",
    "materialize_provider_conflict",
    "new_conflict_id",
    "proposed_change_diff",
    "subject_segment",
    "values_conflict",
]

STAGING_CONFLICTS_DIRNAME = "staging/conflicts"
"""Where conflict records live under `.research/`; the same tree `review.py` reads."""

CONFLICT_ID_PATTERN = r"^conf_[0-9a-f]{16}$"
_CONFLICT_ID = re.compile(CONFLICT_ID_PATTERN)
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

ConflictStatus = Literal["open", "resolved"]
ConflictChoice = Literal["accept", "reject", "defer"]

ConflictList = list["ConflictRecord"]
"""Alias used inside `ConflictStore`, whose `list` method shadows the builtin in class scope."""

PathList = list[Path]
StrList = list[str]

_EXTRACTOR_VERDICT = "asserted"
"""What the extractor's position says: it proposed this candidate as read from the span."""


class ConflictError(ResearchHarnessError):
    """A conflict record could not be read, written, or resolved."""


class ConflictNotFoundError(ConflictError):
    """No conflict with that id exists in this store."""


class ConflictKind(StrEnum):
    """The kinds of disagreement Product §25 asks the queue to be built around.

    ``provider_disagreement`` and ``extractor_verifier`` are materialized today by
    :func:`materialize_provider_conflict` and
    :func:`materialize_extractor_verifier_conflict`, and ``candidate_vs_accepted`` by
    :func:`materialize_candidate_vs_accepted_conflict`, because the inputs for all three
    already exist in staging and canonical evidence.

    The remaining three have no materializer yet, deliberately: ``new_evidence_vs_claim``
    needs the claim-evidence relation pass, ``version_vs_anchor`` needs version supersession
    to re-anchor against, and ``taxonomy_vs_classification`` needs the taxonomy dependency
    set. Until those exist, a caller that has the two sides in hand builds the record
    through :class:`ConflictRecord` directly — one position per side, the fields they differ
    on in ``differing_fields``, and the state changes each side proposes in
    ``proposed_changes``.
    """

    PROVIDER_DISAGREEMENT = "provider_disagreement"
    EXTRACTOR_VERIFIER = "extractor_verifier"
    CANDIDATE_VS_ACCEPTED = "candidate_vs_accepted"
    NEW_EVIDENCE_VS_CLAIM = "new_evidence_vs_claim"
    VERSION_VS_ANCHOR = "version_vs_anchor"
    TAXONOMY_VS_CLASSIFICATION = "taxonomy_vs_classification"


def new_conflict_id() -> str:
    """A fresh `conf_<16 hex>` id, for a conflict with no content to derive one from."""
    return f"conf_{secrets.token_hex(8)}"


def conflict_id_for(*parts: object) -> str:
    """A content-addressed `conf_<16 hex>` id: the same disagreement always gets the same id.

    Re-running a workflow that found a disagreement must produce one conflict, not one per
    run, so identity follows what the sides said rather than when they were asked.
    """
    digest = hashlib.sha256("\x1f".join(str(part) for part in parts).encode("utf-8"))
    return f"conf_{digest.hexdigest()[:16]}"


def subject_segment(subject: str) -> str:
    """Directory name for a subject: the subject itself when path-safe, else a digest of it.

    Candidate, claim, and evidence ids are already safe segments and stay readable on disk;
    anything else (a `work/field` pair, say) is hashed rather than rejected, because a
    disagreement must never be lost to a naming rule.
    """
    if _SAFE_SEGMENT.match(subject):
        return subject
    return f"subj_{hashlib.sha256(subject.encode('utf-8')).hexdigest()[:16]}"


class ConflictResolution(DomainModel):
    """The researcher's answer to a conflict, with the reason it was given.

    ``actor`` must be a human: a model, a workflow, or the system cannot resolve a
    disagreement about scientific state (ADR-007, Product §42 H).
    """

    choice: ConflictChoice
    reason: NonEmptyStr
    actor: NonEmptyStr
    resolved_at: UtcDatetime = Field(default_factory=utc_now)

    @field_validator("actor")
    @classmethod
    def _only_a_researcher_resolves(cls, value: str) -> str:
        if not is_human_actor(value):
            raise ValueError(
                f"{value!r} is not a human actor; a conflict is a question for a researcher "
                "and only 'human' or 'human:<name>' may answer it"
            )
        return value


class ConflictRecord(DomainModel):
    """One disagreement, with every position kept and no winner recorded.

    ``positions`` are the sides, ``differing_fields`` the fields they actually disagree on,
    and ``proposed_changes`` the diff of state changes each side would make — the three
    things Product §25 asks a reviewer to be shown. ``tier`` is 2 by default because a
    disagreement about scientific state is an interpretive judgement (Product §24.1).
    """

    conflict_id: str = Field(default_factory=new_conflict_id, pattern=CONFLICT_ID_PATTERN)
    kind: ConflictKind
    subject: NonEmptyStr
    """The object under dispute: a candidate id, a claim id, or an evidence id."""

    gate: CrossVerificationGate | None = None
    """The cross-verification gate that bought the second opinion, when one did."""

    positions: tuple[ProviderPosition, ...] = ()
    differing_fields: tuple[str, ...] = ()
    summary: NonEmptyStr
    proposed_changes: tuple[dict[str, Any], ...] = ()
    """Per position and field, what accepting that side would change; JSON-ready."""

    tier: ReviewTier = ReviewTier.TIER_2
    status: ConflictStatus = "open"
    resolution: ConflictResolution | None = None
    created_at: UtcDatetime = Field(default_factory=utc_now)
    run_id: str | None = None

    @model_validator(mode="after")
    def _resolution_and_status_agree(self) -> ConflictRecord:
        if (self.status == "resolved") != (self.resolution is not None):
            raise ValueError(
                f"conflict {self.conflict_id} is {self.status!r} with "
                f"{'a' if self.resolution else 'no'} resolution; a resolved conflict records "
                "who resolved it and why, and an open one records nothing"
            )
        return self

    @model_validator(mode="after")
    def _a_disagreement_names_its_sides(self) -> ConflictRecord:
        if self.kind is ConflictKind.PROVIDER_DISAGREEMENT and len(self.positions) < 2:
            raise ValueError(
                f"conflict {self.conflict_id} is a provider disagreement with "
                f"{len(self.positions)} position(s); two answers are the minimum that can differ"
            )
        if self.positions and not self.differing_fields:
            raise ValueError(
                f"conflict {self.conflict_id} records positions but no differing field; a "
                "conflict names what the sides disagree about"
            )
        return self

    @property
    def is_open(self) -> bool:
        """True while the conflict is still waiting for a researcher."""
        return self.status == "open"

    @property
    def labels(self) -> tuple[str, ...]:
        """`provider/model` for each side, in the order they answered."""
        return tuple(position.label for position in self.positions)

    def as_provider_conflict(self) -> ProviderConflict | None:
        """The `ProviderConflict` view of this record, when it is one.

        The Review Inbox and the transports already speak `ProviderConflict`; a record of
        another kind, or one without the gate that bought it, has no such view.
        """
        if self.kind is not ConflictKind.PROVIDER_DISAGREEMENT or self.gate is None:
            return None
        return ProviderConflict(
            subject=self.subject,
            gate=self.gate,
            positions=self.positions,
            differing_fields=self.differing_fields,
            summary=self.summary,
        )

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form for `--json` and for transports."""
        return self.model_dump(mode="json")


# ------------------------------------------------------------------------ materialization


def proposed_change_diff(
    positions: Sequence[ProviderPosition],
    differing_fields: Sequence[str],
    *,
    current: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], ...]:
    """The diff Product §25 asks for: per side and field, what accepting it would change.

    ``current`` is the state on record now — the engine's own recommendation, or the verdict
    already staged — so a reviewer sees `from` and `to` rather than two bare values. It is
    left out when nothing is on record yet, which is honest rather than tidy.
    """
    now = dict(current or {})
    return tuple(
        {
            "position": position.label,
            "provider": position.provider,
            "model": position.model,
            "field": name,
            "from": now.get(name),
            "to": position.decision.get(name),
        }
        for position in positions
        for name in differing_fields
    )


def materialize_provider_conflict(
    verification: CrossVerification,
    *,
    subject: str | None = None,
    run_id: str | None = None,
    current: Mapping[str, str] | None = None,
) -> ConflictRecord | None:
    """One `ConflictRecord` when two providers disagreed, and ``None`` when they did not.

    Agreement materializes nothing, and materializing nothing is the whole point: an
    agreement record would be read sooner or later as permission to accept, and agreeing
    models are still models (ADR-005, ADR-007, Task 13.2).
    """
    conflict = verification.conflict
    if conflict is None:
        return None
    named = subject if subject is not None else conflict.subject
    return ConflictRecord(
        conflict_id=conflict_id_for(
            ConflictKind.PROVIDER_DISAGREEMENT.value,
            named,
            conflict.gate.value,
            canonical_json(list(conflict.differing_fields)),
            canonical_json(
                [[position.label, position.decision] for position in conflict.positions]
            ),
        ),
        kind=ConflictKind.PROVIDER_DISAGREEMENT,
        subject=named,
        gate=conflict.gate,
        positions=conflict.positions,
        differing_fields=conflict.differing_fields,
        summary=conflict.summary,
        proposed_changes=proposed_change_diff(
            conflict.positions, conflict.differing_fields, current=current
        ),
        run_id=run_id,
    )


def materialize_extractor_verifier_conflict(
    candidate: EvidenceCandidate, *, run_id: str | None = None
) -> ConflictRecord | None:
    """One `ConflictRecord` when the verifier contradicted what the extractor proposed.

    Any other verdict returns ``None``: `partially_supported` and `insufficient_evidence`
    are an ambiguous reading rather than a disagreement, and the inbox already routes them
    that way (Product §24.2).
    """
    verification = candidate.verification
    if verification is None or verification.verdict is not VerificationVerdict.CONTRADICTED:
        return None
    extracted = candidate.evidence.content.exact_text
    extractor = ProviderPosition(
        provider=candidate.extraction.provider,
        model=candidate.extraction.model,
        fingerprint=candidate.extraction.request_fingerprint,
        decision={"verdict": _EXTRACTOR_VERDICT, "field": candidate.field, "value": extracted},
        rationale=candidate.extraction.rationale,
    )
    provider, model = _split_backend(candidate.verifier)
    verifier = ProviderPosition(
        provider=provider,
        model=model,
        fingerprint=_answer_fingerprint(verification.model_dump(mode="json")),
        decision={
            "verdict": verification.verdict.value,
            "field": candidate.field,
            "value": extracted,
        },
        rationale=verification.rationale,
    )
    discrepancies = "; ".join(verification.discrepancies) or verification.rationale
    return ConflictRecord(
        conflict_id=conflict_id_for(
            ConflictKind.EXTRACTOR_VERIFIER.value,
            candidate.candidate_id,
            candidate.field,
            extracted,
            verification.verdict.value,
        ),
        kind=ConflictKind.EXTRACTOR_VERIFIER,
        subject=candidate.candidate_id,
        positions=(extractor, verifier),
        differing_fields=("verdict",),
        summary=(
            f"{extractor.label} proposed {candidate.field!r} from the span and "
            f"{verifier.label} contradicted it: {discrepancies}. Neither reading wins by "
            "default; a researcher decides."
        ),
        proposed_changes=proposed_change_diff(
            (extractor, verifier), ("verdict",), current={"verdict": _EXTRACTOR_VERDICT}
        ),
        run_id=run_id,
    )


def materialize_candidate_vs_accepted_conflict(
    candidate: EvidenceCandidate, accepted: Evidence, *, run_id: str | None = None
) -> ConflictRecord | None:
    """One `ConflictRecord` when a candidate reads an already-accepted span differently.

    ``None`` when the two say the same thing, or when they are not anchored at the same
    span: a different span is different evidence, not a contradiction (Product §25).
    """
    if anchor_fingerprint(candidate.evidence.source) != anchor_fingerprint(accepted.source):
        return None
    proposed = candidate.evidence.content.exact_text
    established = accepted.content.exact_text
    if proposed == established:
        return None
    staged = ProviderPosition(
        provider=candidate.extraction.provider,
        model=candidate.extraction.model,
        fingerprint=candidate.extraction.request_fingerprint,
        decision={"exact_text": proposed, "field": candidate.field},
        rationale=candidate.extraction.rationale,
    )
    accepted_side = ProviderPosition(
        provider="accepted",
        model=str(accepted.id),
        fingerprint=anchor_fingerprint(accepted.source),
        decision={"exact_text": established, "field": accepted.content.field or candidate.field},
    )
    return ConflictRecord(
        conflict_id=conflict_id_for(
            ConflictKind.CANDIDATE_VS_ACCEPTED.value,
            candidate.candidate_id,
            str(accepted.id),
            proposed,
            established,
        ),
        kind=ConflictKind.CANDIDATE_VS_ACCEPTED,
        subject=candidate.candidate_id,
        positions=(staged, accepted_side),
        differing_fields=("exact_text",),
        summary=(
            f"candidate {candidate.candidate_id} reads the span accepted as {accepted.id} "
            "differently; accepted state is not overwritten by a proposal."
        ),
        proposed_changes=proposed_change_diff(
            (staged,), ("exact_text",), current={"exact_text": established}
        ),
        run_id=run_id,
    )


# ------------------------------------------------------------------- competing values


@dataclass(frozen=True, slots=True)
class ConflictJudgement:
    """Whether two answers to one field actually disagree, and the reason either way.

    `reason` is written for the researcher and reaches the Review Inbox, so it says what was
    compared rather than which branch fired.
    """

    conflict: bool
    reason: str


#: Head nouns that name a question a Work answers several times over. Read only when the
#: schema does not declare `multi_label` -- which is the case for a candidate judged without
#: its schema (:func:`inferred_field`), where the head noun of the field name and the wording
#: of the question are the only declarations left. Singular and plural are both listed
#: because a schema may call the same question `dataset` or `datasets` (dogfood F7).
LIST_LIKE_FIELD_WORDS: frozenset[str] = frozenset(
    {
        "ablation",
        "ablations",
        "assumption",
        "assumptions",
        "baseline",
        "baselines",
        "corpora",
        "corpus",
        "dataset",
        "datasets",
        "limitation",
        "limitations",
        "metric",
        "metrics",
    }
)

#: Question wordings that ask for every value that applies. The fallback for a schema that
#: predates `InterrogationField.multi_label`, and the reason
#: `plugins/structured-traffic/interrogation/paper.yaml` was readable before it had the
#: flag: every field whose question says "list every value that applies" now also declares
#: `multi_label: true`, and the wording and the flag say the same thing.
SEVERAL_ANSWERS_PHRASES: tuple[str, ...] = (
    "list every",
    "list all",
    "every value that applies",
    "values that apply",
    "all that apply",
    "one or more",
)

#: Words ending in `s` that are not plurals, so a head noun like `encryption_status` is not
#: read as a list. Endings in `ss`, `us`, and `is` are excluded by rule instead.
_SINGULAR_S_WORDS: frozenset[str] = frozenset({"alias", "atlas", "bias", "canvas", "gas", "lens"})


def is_multi_valued(field: InterrogationField) -> bool:
    """True when one Work may answer this field several times without contradicting itself.

    Two stated limitations of the same paper, three datasets it evaluates on, and six
    baselines it compares against are additional answers, not competing values. Reporting
    them as conflicts made 89% of a real review queue noise (dogfood F7), and conflict-first
    review is only worth its place at the top of Product §24.2 if the conflicts are real.

    **The declaration wins.** `InterrogationField.multi_label` is the schema saying so
    itself, and it is read first: a field that declares the flag is multi-valued whatever
    its name reads like, which is what closes the case the inference cannot see — a
    multi-label *categorical* field named in the singular, `traffic.representation_family`.
    Inference is the fallback for the two cases with no declaration to read: a schema
    written before the flag existed, and a staged candidate judged without its schema
    (:func:`inferred_field`). It reads the two things such a field still says: the head noun
    of the name, and whether the question asks for every value that applies.

    A declared `False` therefore does not *refuse* multi-valuedness — the flag defaults to
    `False`, so refusing on it would read "not stated" as "single-valued" for every schema
    that predates it. A single-valued field is stated by leaving the flag alone and not
    naming the question in the plural, which is what `traffic.encryption_status` does.

    `numeric` is not consulted: several measurements are told apart by their metric,
    dataset, and condition in :func:`values_conflict`, which tests that first.
    """
    if field.multi_label:
        return True
    return _asks_for_several(field.question) or _list_like_name(field.name)


def values_conflict(
    field: InterrogationField, a: EvidenceCandidate, b: EvidenceCandidate
) -> ConflictJudgement:
    """Whether two staged answers to `field` for one Work are competing values.

    The rules, in the order they are tested (Product §25, dogfood F7):

    * answers about different Works never compete;
    * a verifier that contradicted one reading while supporting the other is a disagreement;
    * an absence state against a positive value is a disagreement — `not_reported` against a
      quoted number is exactly the conflict review exists for — and so are two different
      absence states;
    * two numbers conflict when metric, dataset, and condition match and the parsed values
      differ; a different measurement is another answer, not a competing one;
    * two readings of the same span that say different things conflict whatever the field
      is, because only one of them can be what that sentence says;
    * on a multi-valued field (:func:`is_multi_valued`, declared or inferred) nothing else
      is a conflict;
    * on a single-valued field, differing normalized values are.
    """
    if a.work != b.work:
        return ConflictJudgement(False, "the answers are about different Works")

    for judgement in (_verdict_clash(a, b), _absence_clash(a, b), _numeric_clash(a, b)):
        if judgement is not None:
            return judgement

    left = normalize_text(a.evidence.content.exact_text)
    right = normalize_text(b.evidence.content.exact_text)
    if left == right:
        return ConflictJudgement(False, "both candidates read the same value")
    if _spans_overlap(a, b):
        return ConflictJudgement(
            True, "both candidates read the same span and report different values"
        )
    if is_multi_valued(field):
        return ConflictJudgement(
            False,
            f"field {field.name!r} takes several values; another answer is not a competing one",
        )
    return ConflictJudgement(
        True, f"field {field.name!r} takes one value and the two candidates differ"
    )


def inferred_field(candidate: EvidenceCandidate) -> InterrogationField:
    """A best-effort `InterrogationField` for a staged candidate, when no schema is at hand.

    The Review Inbox reads staging, and a staged candidate records the field's *name* but not
    the schema that asked it, so the contract has to be reconstructed before a disagreement
    can be judged. Only what the candidate itself proves is asserted: the value kind from the
    content it carries, the tier from its evidence, and a question that deliberately asks for
    nothing in particular — which leaves the name as the only signal :func:`is_multi_valued`
    has. `multi_label` is left at its default for the same reason: the candidate does not
    record it, and asserting a declaration nobody made would turn a real disagreement into a
    routine item. Pass the schema to `build_inbox` and the declaration is read instead.
    """
    content = candidate.evidence.content
    if content.numeric is not None:
        kind = ValueKind.NUMERIC
    elif content.negative_state is not None:
        kind = ValueKind.NEGATIVE
    else:
        kind = ValueKind.TEXT
    return InterrogationField(
        name=candidate.field,
        question=f"What does this Work answer for {candidate.field}?",
        evidence_types=(candidate.evidence.evidence_type,),
        value_kind=kind,
        risk=candidate.evidence.review_tier,
    )


def _verdict_clash(a: EvidenceCandidate, b: EvidenceCandidate) -> ConflictJudgement | None:
    """A disagreement when one reading was contradicted and the other was supported."""
    verdicts = {
        None if a.verification is None else a.verification.verdict,
        None if b.verification is None else b.verification.verdict,
    }
    if VerificationVerdict.CONTRADICTED not in verdicts:
        return None
    if verdicts & {VerificationVerdict.SUPPORTED, VerificationVerdict.PARTIALLY_SUPPORTED}:
        return ConflictJudgement(
            True, "the verifier contradicted one of the two answers and supported the other"
        )
    return None


def _absence_clash(a: EvidenceCandidate, b: EvidenceCandidate) -> ConflictJudgement | None:
    """An absence claim against a positive answer, or two different absence claims."""
    left = a.evidence.content.negative_state
    right = b.evidence.content.negative_state
    if left is None and right is None:
        return None
    if left is not None and right is None:
        return ConflictJudgement(
            True, f"one candidate records {left.value!r} where the other reports a value"
        )
    if right is not None and left is None:
        return ConflictJudgement(
            True, f"one candidate records {right.value!r} where the other reports a value"
        )
    if left is not right:
        return ConflictJudgement(
            True,
            f"the two candidates record different absence states: "
            f"{left.value if left else ''}, {right.value if right else ''}",
        )
    return ConflictJudgement(False, "both candidates record the same absence state")


def _numeric_clash(a: EvidenceCandidate, b: EvidenceCandidate) -> ConflictJudgement | None:
    """Two measurements conflict only when they measure the same thing and disagree."""
    left = a.evidence.content.numeric
    right = b.evidence.content.numeric
    if left is None or right is None:
        return None
    if _measurement_key(left) != _measurement_key(right):
        return ConflictJudgement(
            False,
            f"different measurements: {_measurement_label(left)} and {_measurement_label(right)}",
        )
    if left.parsed == right.parsed:
        return ConflictJudgement(False, f"the same measured value for {_measurement_label(left)}")
    return ConflictJudgement(
        True, f"{_measurement_label(left)} is reported as {left.parsed} and as {right.parsed}"
    )


def _measurement_key(value: NumericValue) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    """What two numbers must share to be the same measurement: metric, dataset, condition."""
    return (
        value.metric.strip().casefold(),
        (value.dataset or "").strip().casefold(),
        tuple(sorted(value.condition.items())),
    )


def _measurement_label(value: NumericValue) -> str:
    return f"{value.metric} on {value.dataset}" if value.dataset else value.metric


def _spans_overlap(a: EvidenceCandidate, b: EvidenceCandidate) -> bool:
    """True when both candidates quote the same block and their character ranges overlap."""
    left = a.evidence.source
    right = b.evidence.source
    if left.artifact != right.artifact or left.block != right.block:
        return False
    if (
        left.char_start is None
        or left.char_end is None
        or right.char_start is None
        or right.char_end is None
    ):
        return True
    return left.char_start < right.char_end and right.char_start < left.char_end


def _asks_for_several(question: str) -> bool:
    folded = question.casefold()
    return any(phrase in folded for phrase in SEVERAL_ANSWERS_PHRASES)


def _list_like_name(name: str) -> bool:
    """True when the head noun of a field name names a list of answers."""
    head = name.rpartition(".")[2].rpartition("_")[2].casefold()
    if head in LIST_LIKE_FIELD_WORDS:
        return True
    return (
        len(head) > 3
        and head.endswith("s")
        and not head.endswith(("ss", "us", "is"))
        and head not in _SINGULAR_S_WORDS
    )


# -------------------------------------------------------------------------------- store


class ConflictStore:
    """Conflict files under `<research_dir>/staging/conflicts/<subject>/<conflict_id>.json`.

    The subject directory *is* the index: every conflict about one candidate, claim, or
    evidence object is one `open_for` call away, and no side table has to be kept in sync
    with a frozen staging schema. Regenerable by construction, like every other tree under
    `.research/` (ADR-001).
    """

    def __init__(self, research_dir: Path) -> None:
        self._research_dir = Path(research_dir)

    def __repr__(self) -> str:
        return f"ConflictStore({str(self._research_dir)!r})"

    @property
    def research_dir(self) -> Path:
        """Root of regenerable runtime state; nothing is written outside it."""
        return self._research_dir

    @property
    def root(self) -> Path:
        """`<research_dir>/staging/conflicts` — the whole conflict tree."""
        return self._research_dir / Path(STAGING_CONFLICTS_DIRNAME)

    def subject_dir(self, subject: str) -> Path:
        return self.root / subject_segment(subject)

    def path_for(self, subject: str, conflict_id: str) -> Path:
        return self.subject_dir(subject) / f"{_conflict_id(conflict_id)}.json"

    # -- writes --------------------------------------------------------------

    def put(self, record: ConflictRecord) -> Path:
        """Write (or replace) one conflict atomically; returns its path."""
        path = self.path_for(record.subject, record.conflict_id)
        atomic_write_text(path, _dump(record))
        return path

    def open_or_put(self, record: ConflictRecord) -> ConflictRecord:
        """Record a conflict once; an already-stored one is returned untouched.

        Conflict ids are content-addressed, so a re-run re-derives the same id. Returning
        the stored record rather than overwriting it means a re-run neither duplicates a
        disagreement nor reopens one a researcher has already answered.
        """
        existing = self._read_at(self.path_for(record.subject, record.conflict_id))
        if existing is not None:
            return existing
        self.put(record)
        return record

    def resolve(
        self, conflict_id: str, choice: ConflictChoice, reason: str, actor: str
    ) -> ConflictRecord:
        """Close one conflict the researcher's way, recording who decided and why.

        A non-human actor raises `AuthorityError` before anything is written: no verdict,
        no majority of providers, and no later run closes a conflict (ADR-007, §42 H).
        """
        if not is_human_actor(actor):
            raise AuthorityError(
                f"actor {actor!r} cannot resolve conflict {conflict_id}; resolving a "
                "disagreement about scientific state requires a human actor"
            )
        if not reason.strip():
            raise ConflictError(f"resolving conflict {conflict_id} requires a reason")
        record = self.get(conflict_id)
        if not record.is_open:
            raise ConflictError(
                f"conflict {conflict_id} was already resolved by "
                f"{record.resolution.actor if record.resolution else 'someone'}"
            )
        resolved = record.touch(
            status="resolved",
            resolution=ConflictResolution(choice=choice, reason=reason, actor=actor),
        )
        self.put(resolved)
        logger.info("conflict %s resolved as %s by %s", conflict_id, choice, actor)
        return resolved

    def delete(self, conflict_id: str) -> bool:
        """Remove one conflict; True when one was there. Canonical state is untouched."""
        for path in self._paths():
            if path.stem == conflict_id:
                path.unlink(missing_ok=True)
                return True
        return False

    # -- reads ---------------------------------------------------------------

    def get(self, conflict_id: str, *, subject: str | None = None) -> ConflictRecord:
        """One conflict by id; raises `ConflictNotFoundError` when absent."""
        wanted = _conflict_id(conflict_id)
        if subject is not None:
            return _read(self.path_for(subject, wanted))
        for path in self._paths():
            if path.stem == wanted:
                return _read(path)
        raise ConflictNotFoundError(f"no conflict {conflict_id} under {self.root}")

    def list(
        self, subject: str | None = None, status: ConflictStatus | None = None
    ) -> ConflictList:
        """Conflicts, oldest first, filtered as asked."""
        records = [
            record
            for record in self._iter(subject)
            if (subject is None or record.subject == subject)
            and (status is None or record.status == status)
        ]
        return sorted(records, key=lambda record: (record.created_at, record.conflict_id))

    def open_for(self, subject: str) -> ConflictList:
        """Every unresolved conflict about one candidate, claim, or evidence object."""
        return self.list(subject=subject, status="open")

    def subjects(self) -> StrList:
        """Subjects that currently have conflict records, in directory order."""
        return sorted({record.subject for record in self._iter(None)})

    # -- internals -----------------------------------------------------------

    def _iter(self, subject: str | None) -> Iterator[ConflictRecord]:
        for path in self._paths(subject):
            record = self._read_at(path)
            if record is not None:
                yield record

    def _paths(self, subject: str | None = None) -> PathList:
        directories = (
            [self.subject_dir(subject)] if subject is not None else _subdirectories(self.root)
        )
        paths: PathList = []
        for directory in directories:
            clean_partials(directory)
            paths.extend(sorted(directory.glob("conf_*.json")))
        return paths

    def _read_at(self, path: Path) -> ConflictRecord | None:
        """One record, or None when it is absent or unreadable; a bad file never raises here."""
        if not path.is_file():
            return None
        try:
            return _read(path)
        except ConflictError:
            logger.warning("ignoring unreadable conflict record %s", path)
            return None


def load_conflict_records(directory: Path, *, status: ConflictStatus | None = None) -> ConflictList:
    """Read conflict records out of a `staging/conflicts` tree, unreadable files skipped.

    Used by the Review Inbox, which must show the rest of the queue even when one
    disposable file under `.research/` is corrupt.
    """
    root = Path(directory)
    if not root.is_dir():
        return []
    records: ConflictList = []
    for subdirectory in _subdirectories(root):
        clean_partials(subdirectory)
        for path in sorted(subdirectory.glob("conf_*.json")):
            try:
                record = _read(path)
            except ConflictError as exc:
                logger.warning("ignoring unreadable conflict record %s: %s", path, exc)
                continue
            if status is None or record.status == status:
                records.append(record)
    return sorted(records, key=lambda record: (record.created_at, record.conflict_id))


# ------------------------------------------------------------------------------ helpers


def _subdirectories(root: Path) -> PathList:
    if not root.is_dir():
        return []
    return [path for path in sorted(root.iterdir()) if path.is_dir()]


def _dump(record: ConflictRecord) -> str:
    return (
        json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )


def _read(path: Path) -> ConflictRecord:
    if not path.is_file():
        raise ConflictNotFoundError(f"no conflict record at {path}")
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConflictError(f"cannot read conflict record {path}: {exc}") from exc
    try:
        return ConflictRecord.model_validate(payload)
    except ValidationError as exc:
        raise ConflictError(f"invalid conflict record {path}: {exc}") from exc


def _conflict_id(value: str) -> str:
    if not _CONFLICT_ID.match(value):
        raise ConflictError(f"{value!r} is not a conflict id ({CONFLICT_ID_PATTERN})")
    return value


def _split_backend(label: str | None) -> tuple[str, str]:
    """`provider/model` split of a recorded backend label, tolerating a bare provider name."""
    if not label:
        return ("unknown", "unknown")
    provider, _, model = label.partition("/")
    return (provider or "unknown", model or "unknown")


def _answer_fingerprint(payload: Any) -> str:
    """A digest of what a side answered.

    A verified candidate records the verifier's *answer* but not the request fingerprint it
    came from, so a position built from staging is fingerprinted by its answer instead. It
    is still stable and still identifies the reading being disputed.
    """
    return f"sha256:{hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()}"
