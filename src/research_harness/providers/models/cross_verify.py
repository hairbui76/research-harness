"""Selective cross-provider verification: two models where disagreement is worth paying for.

Running every job twice doubles cost and buys nothing (Product 20.4): routine extraction is
not eligible here, and :data:`DEFAULT_POLICY` enables exactly the five high-value gates the
ROADMAP names — an absence/gap claim, a numeric high-impact claim, a counter-evidence
reading, a submission-ready field-level claim, and a high-consequence manuscript sentence.

Two rules make the result honest.

**Disagreement is one conflict, never a merge.** When providers answer differently on the
compared decision fields the call returns a single :class:`ProviderConflict` listing every
position and the fields they differ on. No position is preferred, averaged, or written over
another: provider A versus provider B is a conflict the researcher resolves (Product 25,
ROADMAP Gate P13).

**Agreement is not acceptance.** :class:`CrossVerification` records ``agreement`` and stops
there. It has no ``accepted`` field, no verdict, and no authority, because agreeing models
are still models: a Tier-2 scientific judgement reaches accepted state only through human
review (ADR-003, ADR-007, Product 24.4, ROADMAP Task 13.2). Nothing downstream may read
``agreement`` as permission to accept.

Comparison looks only at the named ``decision_fields`` of the validated structured outputs.
Rationale prose is recorded on each position and never compared: two models phrasing the
same decision differently is not a scientific disagreement.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from research_harness.domain.claim import Claim
from research_harness.domain.enums import ClaimScope, ClaimType
from research_harness.domain.evidence import Evidence
from research_harness.providers.models.base import (
    ModelProvider,
    ModelRequest,
    ProviderError,
    TraceSink,
    canonical_json,
)
from research_harness.providers.models.router import ProviderEntry

logger = logging.getLogger(__name__)

__all__ = [
    "CONFLICT_KIND",
    "DEFAULT_POLICY",
    "PROVIDER_ERROR_PREFIX",
    "CrossVerification",
    "CrossVerificationGate",
    "CrossVerifyPolicy",
    "Eligibility",
    "ProviderCandidate",
    "ProviderConflict",
    "ProviderPosition",
    "cross_verify",
    "decision_of",
    "effective_scope",
    "is_eligible",
    "provider_label",
]

CONFLICT_KIND: Literal["provider_disagreement"] = "provider_disagreement"
"""The one conflict kind this module produces; the Review Inbox materializes it (13.2)."""

PROVIDER_ERROR_PREFIX = "provider_error:"
"""Prefix of the skip reason recorded for a provider whose call failed."""


class CrossVerificationGate(StrEnum):
    """High-value gates where a second provider is scientifically worth its cost (20.4)."""

    ABSENCE_CLAIM = "absence_claim"
    NUMERIC_HIGH_IMPACT = "numeric_high_impact"
    COUNTER_EVIDENCE_INTERPRETATION = "counter_evidence_interpretation"
    SUBMISSION_FIELD_CLAIM = "submission_field_claim"
    MANUSCRIPT_HIGH_CONSEQUENCE = "manuscript_high_consequence"


ProviderCandidate = tuple[ModelProvider, str] | ProviderEntry
"""A provider to run the request through: a ``(provider, model)`` pair or a router entry."""


class CrossVerifyPolicy(BaseModel):
    """Which gates cross-verify, how many providers it takes, and the call budget.

    A gate that is not listed in ``enabled_gates`` is never cross-verified, which is how
    "do not double every routine task" is expressed as configuration rather than a branch.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled_gates: frozenset[CrossVerificationGate] = frozenset()
    min_providers: int = Field(default=2, ge=2)
    """Two independent answers is the minimum that can disagree; one never can."""

    require_distinct_vendors: bool = True
    """Count distinct provider names: the same vendor twice is one vendor's blind spots."""

    max_extra_calls_per_object: int = Field(default=1, ge=0)
    """Calls beyond the first for one object, so a gate cannot fan out without a budget."""

    @property
    def max_providers(self) -> int:
        """Providers one verification may call: the first plus its extra-call budget."""
        return 1 + self.max_extra_calls_per_object

    def enables(self, gate: CrossVerificationGate) -> bool:
        """True when this policy cross-verifies that gate at all."""
        return gate in self.enabled_gates


DEFAULT_POLICY = CrossVerifyPolicy(enabled_gates=frozenset(CrossVerificationGate))
"""The five ROADMAP default gates, two distinct vendors, one extra call per object."""


class Eligibility(BaseModel):
    """Whether one gate applies to one object, and every reason it does or does not."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eligible: bool
    gate: CrossVerificationGate
    reasons: tuple[str, ...] = ()


class ProviderPosition(BaseModel):
    """What one provider answered, reduced to the fields a disagreement is measured on.

    ``decision`` holds only the comparable fields of the validated structured output.
    ``rationale`` is recorded for the reviewer and is never compared.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str
    fingerprint: str
    decision: dict[str, str] = Field(default_factory=dict)
    rationale: str | None = None

    @property
    def label(self) -> str:
        """``provider/model``, how a position is named in a conflict summary."""
        return f"{self.provider}/{self.model}"


class ProviderConflict(BaseModel):
    """Provider A versus provider B, as one reviewable object (Product 25, Task 13.2).

    Every position is kept side by side and none is preferred: resolving the conflict is a
    researcher act, and nothing in this module or downstream of it may pick a winner.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["provider_disagreement"] = CONFLICT_KIND
    subject: str
    """The object under verification, e.g. a claim id, so the inbox can route it."""

    gate: CrossVerificationGate
    positions: tuple[ProviderPosition, ...] = Field(min_length=2)
    differing_fields: tuple[str, ...] = Field(min_length=1)
    summary: str


class CrossVerification(BaseModel):
    """The outcome of running one request through several providers.

    There is deliberately no ``accepted`` field and no winning position: ``agreement`` says
    the compared decisions matched, and that is all it may ever mean (ADR-007, Task 13.2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate: CrossVerificationGate
    eligible: bool
    skipped_reason: str | None = None
    """Why nothing ran, or which providers failed (``provider_error:<name>``)."""

    positions: tuple[ProviderPosition, ...] = ()
    agreement: bool = False
    """True only when at least two providers answered and their decisions matched."""

    incomplete: bool = False
    """True when a provider that should have answered did not."""

    conflict: ProviderConflict | None = None

    @property
    def ran(self) -> bool:
        """True when at least one provider was actually called."""
        return bool(self.positions) or self.incomplete


# --------------------------------------------------------------------------- eligibility


def effective_scope(claim: Claim) -> ClaimScope:
    """The more ambitious of a claim's declared scope level and its requested strength.

    A gate asks how much the claim is reaching for, and either field can carry that reach,
    so the stronger one decides. Neither is treated as a permission: eligibility only says
    a second opinion is worth buying.
    """
    return max(claim.scope.level, claim.assessment.requested_strength)


def is_eligible(
    policy: CrossVerifyPolicy,
    gate: CrossVerificationGate,
    *,
    claim: Claim | None = None,
    evidence: Evidence | None = None,
    manuscript_attached: bool = False,
    submission_ready: bool = False,
) -> Eligibility:
    """Whether ``gate`` applies here under ``policy``, with the reasons either way.

    Routine work is ineligible by default: every gate needs a specific reason to spend a
    second provider, and a missing object is a reason to refuse rather than to guess.
    """
    if not policy.enables(gate):
        return Eligibility(
            eligible=False,
            gate=gate,
            reasons=(
                f"gate {gate.value!r} is not enabled by this policy; routine work is not "
                "cross-verified (Product 20.4)",
            ),
        )
    context = _GateContext(
        claim=claim,
        evidence=evidence,
        manuscript_attached=manuscript_attached,
        submission_ready=submission_ready,
    )
    checks: dict[CrossVerificationGate, Callable[[_GateContext], _Verdict]] = {
        CrossVerificationGate.ABSENCE_CLAIM: _absence_claim,
        CrossVerificationGate.NUMERIC_HIGH_IMPACT: _numeric_high_impact,
        CrossVerificationGate.COUNTER_EVIDENCE_INTERPRETATION: _counter_evidence,
        CrossVerificationGate.SUBMISSION_FIELD_CLAIM: _submission_field_claim,
        CrossVerificationGate.MANUSCRIPT_HIGH_CONSEQUENCE: _manuscript_high_consequence,
    }
    eligible, reasons = checks[gate](context)
    return Eligibility(eligible=eligible, gate=gate, reasons=tuple(reasons))


@dataclass(frozen=True, slots=True)
class _GateContext:
    """Everything a gate check may look at about the object under review."""

    claim: Claim | None
    evidence: Evidence | None
    manuscript_attached: bool
    submission_ready: bool

    @property
    def numeric(self) -> bool:
        """True when the supplied evidence carries a measured value (Product 12)."""
        return self.evidence is not None and self.evidence.content.numeric is not None

    def scope_at_least(self, level: ClaimScope) -> bool:
        """True when a claim was supplied and reaches at least ``level``."""
        return self.claim is not None and effective_scope(self.claim) >= level


_Verdict = tuple[bool, list[str]]
"""Whether a gate applies, plus every reason for and against, in reading order."""


def _absence_claim(context: _GateContext) -> _Verdict:
    """Absence and universal wording is the claim most easily wrong, so it gets two readers."""
    claim = context.claim
    if claim is None:
        return False, ["no claim was supplied to judge an absence gate against"]
    if claim.type is ClaimType.ABSENCE:
        return True, [f"claim {claim.id} is an absence claim"]
    if effective_scope(claim) is ClaimScope.UNIVERSAL_OR_ABSENCE:
        return True, [f"claim {claim.id} reaches {ClaimScope.UNIVERSAL_OR_ABSENCE.label}"]
    return False, [
        f"claim {claim.id} is {claim.type.value} at {effective_scope(claim).label}, neither an "
        "absence claim nor universal wording"
    ]


def _numeric_high_impact(context: _GateContext) -> _Verdict:
    """A measured value that carries a corpus-level statement or reaches the manuscript."""
    reasons: list[str] = []
    if context.numeric:
        reasons.append("the evidence carries a measured value (Product 12)")
    else:
        reasons.append("no numeric evidence was supplied; there is no measured value to check")
    if context.manuscript_attached:
        reasons.append("the number is attached to manuscript text")
    elif context.scope_at_least(ClaimScope.CORPUS_PATTERN):
        reasons.append(f"the claim reaches {ClaimScope.CORPUS_PATTERN.label} or above")
    else:
        reasons.append(
            "the number carries no manuscript text and no claim at "
            f"{ClaimScope.CORPUS_PATTERN.label} or above"
        )
        return False, reasons
    return context.numeric, reasons


def _counter_evidence(context: _GateContext) -> _Verdict:
    """Reading a result as counter-evidence is a Tier-2 interpretation (Product 24.1)."""
    claim = context.claim
    if claim is None:
        return False, ["no claim was supplied to look for contradicting relations on"]
    contradicting = claim.contradicting
    if not contradicting:
        return False, [f"claim {claim.id} records no contradicting evidence to interpret"]
    return True, [
        f"claim {claim.id} records {len(contradicting)} contradicting relation(s), whose "
        "reading is an interpretive judgement"
    ]


def _submission_field_claim(context: _GateContext) -> _Verdict:
    """A field-level statement about to be submitted is the most expensive kind to get wrong."""
    reasons: list[str] = []
    ready = context.submission_ready
    reasons.append(
        "the work is marked submission ready"
        if ready
        else "the work is not marked submission ready"
    )
    if context.claim is None:
        reasons.append("no claim was supplied to check the scope of")
        return False, reasons
    if context.scope_at_least(ClaimScope.FIELD_GENERALIZATION):
        reasons.append(f"the claim reaches {ClaimScope.FIELD_GENERALIZATION.label} or above")
        return ready, reasons
    reasons.append(f"the claim does not reach {ClaimScope.FIELD_GENERALIZATION.label}")
    return False, reasons


def _manuscript_high_consequence(context: _GateContext) -> _Verdict:
    """A manuscript sentence carrying a number or a field-level generalization."""
    reasons: list[str] = []
    attached = context.manuscript_attached
    reasons.append(
        "the statement is attached to manuscript text"
        if attached
        else "no manuscript text is attached"
    )
    if context.numeric:
        reasons.append("it carries a measured value")
        return attached, reasons
    if context.scope_at_least(ClaimScope.FIELD_GENERALIZATION):
        reasons.append(f"it reaches {ClaimScope.FIELD_GENERALIZATION.label} or above")
        return attached, reasons
    reasons.append(
        f"it carries no measured value and does not reach {ClaimScope.FIELD_GENERALIZATION.label}"
    )
    return False, reasons


# ------------------------------------------------------------------------- verification


def provider_label(candidate: ProviderCandidate) -> str:
    """``provider/model`` for a candidate, whichever form the caller offered it in."""
    if isinstance(candidate, ProviderEntry):
        return candidate.label
    provider, model = candidate
    return f"{provider.name}/{model}"


def decision_of(output: BaseModel, fields: Sequence[str]) -> dict[str, str]:
    """The comparable decision of one structured output: the named fields, as text.

    Everything outside ``fields`` — rationale, prose, list ordering, provider identity —
    is left out, because a disagreement must be about the decision and nothing else.
    """
    data = output.model_dump(mode="json")
    return {name: _as_text(data[name]) for name in fields if name in data}


def _as_text(value: Any) -> str:
    """A stable text form for a decision value, so comparison is exact and order-free."""
    return value if isinstance(value, str) else canonical_json(value)


def cross_verify(
    request: ModelRequest[Any],
    providers: Sequence[ProviderCandidate],
    *,
    gate: CrossVerificationGate,
    policy: CrossVerifyPolicy = DEFAULT_POLICY,
    eligibility: Eligibility | None = None,
    decision_fields: Sequence[str],
    subject: str | None = None,
    force: bool = False,
    trace: TraceSink | None = None,
) -> CrossVerification:
    """Run the same request through several providers and report agreement or one conflict.

    ``eligibility`` is normally computed by :func:`is_eligible` against the object under
    review and passed in; without it only the policy's gate list can be consulted, which
    refuses every object-specific gate. ``force`` runs an ineligible gate anyway and still
    reports ``eligible=False``, so a forced run is visible as one.

    ``trace`` is the caller's disposable trace sink. Cross-verification calls each provider
    directly rather than through the router that selected it, so the sink a
    :class:`~research_harness.privacy.traces.TracingRouter` would have attached has to be
    passed in; without it the second opinion is the one call in a run that leaves no record.

    A provider whose call fails is recorded as ``provider_error:<name>`` in
    ``skipped_reason`` and the verification is ``incomplete``; the providers that answered
    are kept. A single surviving position is never agreement — one answer cannot agree
    with itself — and agreement never accepts anything.
    """
    fields = tuple(decision_fields)
    _require_comparable_fields(request, fields)
    verdict = eligibility if eligibility is not None else is_eligible(policy, gate)
    if verdict.gate is not gate:
        raise ValueError(f"eligibility was computed for {verdict.gate.value!r}, not {gate.value!r}")

    if not verdict.eligible and not force:
        return CrossVerification(
            gate=gate,
            eligible=False,
            skipped_reason="; ".join(verdict.reasons) or f"gate {gate.value!r} does not apply",
        )

    selected = _select(providers, policy)
    shortfall = _provider_shortfall(selected, policy)
    if shortfall is not None:
        return CrossVerification(gate=gate, eligible=verdict.eligible, skipped_reason=shortfall)

    positions: list[ProviderPosition] = []
    failures: list[str] = []
    for provider, model in selected:
        try:
            response = provider.complete(request, trace=trace)
        except ProviderError as error:
            logger.info("cross-verification lost %s: %s", provider.name, error)
            failures.append(f"{PROVIDER_ERROR_PREFIX}{provider.name}")
            continue
        positions.append(
            ProviderPosition(
                provider=response.provider or provider.name,
                model=response.model or model,
                fingerprint=response.request_fingerprint,
                decision=decision_of(response.parsed, fields),
                rationale=_rationale_of(response.parsed),
            )
        )

    return _outcome(
        gate=gate,
        eligible=verdict.eligible,
        positions=tuple(positions),
        failures=tuple(failures),
        fields=fields,
        subject=subject if subject is not None else _default_subject(request),
    )


# ----------------------------------------------------------------------------- internals


def _require_comparable_fields(request: ModelRequest[Any], fields: Sequence[str]) -> None:
    """Refuse a comparison that would compare nothing, before any provider is called."""
    if not fields:
        raise ValueError("cross-verification needs at least one decision field to compare")
    declared = request.response_schema.model_fields
    unknown = [name for name in fields if name not in declared]
    if unknown:
        raise ValueError(
            f"{request.response_schema.__name__} has no field(s) {', '.join(sorted(unknown))}; "
            "a decision field must exist on the schema both providers answer with"
        )


def _select(
    providers: Sequence[ProviderCandidate], policy: CrossVerifyPolicy
) -> tuple[tuple[ModelProvider, str], ...]:
    """The providers this policy's call budget allows, in the order they were offered."""
    pairs = [
        (item.provider, item.model) if isinstance(item, ProviderEntry) else (item[0], item[1])
        for item in providers
    ]
    if len(pairs) > policy.max_providers:
        logger.debug(
            "cross-verification budget keeps %d of %d providers", policy.max_providers, len(pairs)
        )
    return tuple(pairs[: policy.max_providers])


def _provider_shortfall(
    selected: Sequence[tuple[ModelProvider, str]], policy: CrossVerifyPolicy
) -> str | None:
    """The reason there are too few independent providers, or ``None`` when there are enough."""
    if policy.require_distinct_vendors:
        available = len({provider.name for provider, _ in selected})
        kind = "distinct providers"
    else:
        available = len(selected)
        kind = "providers"
    if available >= policy.min_providers:
        return None
    offered = ", ".join(f"{provider.name}/{model}" for provider, model in selected) or "none"
    return (
        f"cross-verification needs {policy.min_providers} {kind} within a budget of "
        f"{policy.max_providers} calls; got {available} ({offered})"
    )


def _rationale_of(output: BaseModel) -> str | None:
    """A model-authored rationale when the schema has one; it is recorded, never compared."""
    value = getattr(output, "rationale", None)
    return value if isinstance(value, str) else None


def _default_subject(request: ModelRequest[Any]) -> str:
    """What the request is about when the caller names no subject."""
    subject = request.metadata.get("subject")
    if subject:
        return subject
    for envelope in request.inputs:
        if envelope.object_id:
            return envelope.object_id
    return request.role


def _outcome(
    *,
    gate: CrossVerificationGate,
    eligible: bool,
    positions: tuple[ProviderPosition, ...],
    failures: tuple[str, ...],
    fields: tuple[str, ...],
    subject: str,
) -> CrossVerification:
    """Turn the collected positions into agreement, one conflict, or an incomplete result."""
    skipped = "; ".join(failures) or None
    if len(positions) < 2:
        return CrossVerification(
            gate=gate,
            eligible=eligible,
            skipped_reason=skipped,
            positions=positions,
            agreement=False,
            incomplete=bool(failures),
        )
    differing = tuple(
        name for name in fields if len({position.decision.get(name) for position in positions}) > 1
    )
    if not differing:
        return CrossVerification(
            gate=gate,
            eligible=eligible,
            skipped_reason=skipped,
            positions=positions,
            agreement=True,
            incomplete=bool(failures),
        )
    return CrossVerification(
        gate=gate,
        eligible=eligible,
        skipped_reason=skipped,
        positions=positions,
        agreement=False,
        incomplete=bool(failures),
        conflict=ProviderConflict(
            subject=subject,
            gate=gate,
            positions=positions,
            differing_fields=differing,
            summary=_conflict_summary(subject, gate, positions, differing),
        ),
    )


def _conflict_summary(
    subject: str,
    gate: CrossVerificationGate,
    positions: tuple[ProviderPosition, ...],
    differing: tuple[str, ...],
) -> str:
    """One sentence a reviewer can act on: who said what, and that nobody wins by default."""
    stated = "; ".join(
        f"{position.label} says "
        + ", ".join(f"{name}={position.decision.get(name, '')!r}" for name in differing)
        for position in positions
    )
    return (
        f"{len(positions)} providers disagree on {', '.join(differing)} for {subject} at gate "
        f"{gate.value}: {stated}. No position is preferred and none overwrites another; a "
        "researcher resolves this."
    )
