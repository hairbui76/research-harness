"""Drafting a manuscript section from accepted state - as a candidate, and only that.

Product 30 fixes the writer's inputs: a section purpose, the approved taxonomy, the
accepted Claims, their supporting Evidence, the qualifying and counter Evidence, the
project Decisions, and the style constraints. It fixes the output just as tightly: the
writer may not invent a scientific fact to improve prose, and an assertion it cannot
support is listed as ``NEEDS SOURCE`` rather than given a fabricated citation (30.2).

Everything here obeys that boundary mechanically rather than by prompt. The draft is
written to ``.research/staging/drafts/<run>.tex.json`` - regenerable state with no
scientific authority - and never into ``manuscript/``; the path is checked before the
bytes are written, so a mis-set project root cannot turn a candidate into accepted text.
No Claim, Evidence, or anchor is created: this module opens no transaction and calls no
capability handler, so a draft cannot promote its own references into the graph
(ADR-003, ADR-007). An id the writer returns that was not in its inputs is a refusal,
not a warning: invalid model output does not reach staging (ADR-005).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from research_harness.capabilities.context import CapabilityContext
from research_harness.domain.base import Provenance
from research_harness.domain.claim import Claim
from research_harness.domain.enums import DecisionStatus, EvidenceStatus, StaleState
from research_harness.domain.errors import CapabilityError
from research_harness.domain.evidence import Evidence
from research_harness.domain.ids import ClaimId, EvidenceId
from research_harness.domain.research import Decision
from research_harness.manuscript.protected import ProtectedSpan, find_protected_spans
from research_harness.providers.models.base import ModelProvider
from research_harness.providers.models.router import ModelRouter
from research_harness.roles import WRITER, InputKind, RoleInput, WriterOutput, build_request
from research_harness.workflows.models import new_run_id
from research_harness.workspace.atomic import atomic_write_text
from research_harness.workspace.repository import ObjectNotFoundError

__all__ = [
    "DRAFT_SUFFIX",
    "NEEDS_SOURCE",
    "STAGING_DRAFTS_DIRNAME",
    "DraftCandidate",
    "ModelClient",
    "draft_section",
    "staged_draft",
]

logger = logging.getLogger(__name__)

ModelClient = ModelProvider | ModelRouter
"""What a draft may run on: one provider, or the workspace's router (Product 20.2)."""

STAGING_DRAFTS_DIRNAME = "staging/drafts"
"""Where candidates live: under `.research/`, deletable, and never scientific authority."""

DRAFT_SUFFIX = ".tex.json"
"""A candidate is LaTeX plus its provenance, so it is stored as JSON carrying the text."""

NEEDS_SOURCE = "NEEDS SOURCE"
"""The visible marker Product 30.2 requires in place of a fabricated citation."""


class DraftCandidate(BaseModel):
    """One drafted section, everything it leaned on, and everything it could not support.

    ``text`` is the writer's draft verbatim - a candidate is evidence of what the model
    said, so it is never silently edited. ``marked_text`` is the same draft with one
    ``% NEEDS SOURCE: ...`` line per unsupported statement appended, which is the form a
    researcher reads and the form written to staging.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run: str
    purpose: str
    style: str | None = None
    text: str
    claim_refs: tuple[ClaimId, ...] = ()
    evidence_refs: tuple[EvidenceId, ...] = ()
    unsupported_statements: tuple[str, ...] = ()
    needs_source: tuple[str, ...] = ()
    """Every statement the draft cannot source, including all ``unsupported_statements``."""
    protected_spans: tuple[ProtectedSpan, ...] = ()
    """Citations, numbers, identifiers, and quotations a later style pass may not touch."""
    provenance: Provenance
    path: Path | None = None

    @property
    def marked_text(self) -> str:
        """The draft with a ``NEEDS SOURCE`` comment for every statement it could not back."""
        if not self.needs_source:
            return self.text
        marks = "\n".join(f"% {NEEDS_SOURCE}: {item}" for item in self.needs_source)
        return f"{self.text.rstrip()}\n\n{marks}\n"

    @property
    def is_complete(self) -> bool:
        """True when every statement in the draft traces to accepted support."""
        return not self.needs_source

    def as_dict(self) -> dict[str, object]:
        """JSON-ready form; the staged file and ``--json`` output share it."""
        payload = self.model_dump(mode="json")
        payload["marked_text"] = self.marked_text
        return payload


def draft_section(
    ctx: CapabilityContext,
    purpose: str,
    *,
    claims: Sequence[ClaimId],
    provider: ModelClient,
    style: str | None = None,
) -> DraftCandidate:
    """Draft one section from accepted Claims and stage it for review (Product 30).

    The writer is shown exactly the Product 30 drafting input: the named Claims, the
    accepted Evidence they are related to (supporting, qualifying, and contradicting
    alike, each labelled with its relation so counter-evidence cannot read as support),
    and the project's accepted Decisions. It is shown nothing else, and it writes nothing:
    the returned candidate is a file under `.research/staging/drafts/`, and the accepted
    graph is exactly as it was.
    """
    if not purpose.strip():
        raise CapabilityError("manuscript.draft: a section purpose is required")
    if not claims:
        raise CapabilityError(
            "manuscript.draft: name at least one accepted Claim to draft from; the writer "
            "may not invent scientific facts to fill a section (Product 30)"
        )
    selected = _claims(ctx, claims)
    evidence = _related_evidence(ctx, selected)
    decisions = _accepted_decisions(ctx)

    built = build_request(
        WRITER,
        [
            *(
                RoleInput(InputKind.ACCEPTED_CLAIMS, str(claim.id), _claim_payload(claim))
                for claim in selected
            ),
            *(
                RoleInput(InputKind.ACCEPTED_EVIDENCE, str(item.id), _evidence_payload(item))
                for item in evidence.values()
            ),
            *(
                RoleInput(
                    InputKind.ACCEPTED_DECISIONS, str(decision.id), _decision_payload(decision)
                )
                for decision in decisions
            ),
        ],
        extra_instructions=_instructions(purpose, style),
    )
    if built.stripped_fields:  # pragma: no cover - accepted state carries no reasoning
        logger.warning(
            "dropped reasoning-shaped fields from the writer request: %s", built.stripped_fields
        )

    response = provider.complete(built.request)
    output = response.parsed
    if not isinstance(output, WriterOutput):  # pragma: no cover - schema-enforced
        raise CapabilityError(
            f"manuscript.draft: the writer role returned {type(output).__name__}, not WriterOutput"
        )
    claim_refs = _checked_ids(output.claim_refs, ClaimId, set(selected_ids(selected)), "claim")
    evidence_refs = _checked_ids(output.evidence_refs, EvidenceId, set(evidence), "evidence")

    run = new_run_id()
    candidate = DraftCandidate(
        run=run,
        purpose=purpose.strip(),
        style=style,
        text=output.draft,
        claim_refs=claim_refs,
        evidence_refs=evidence_refs,
        unsupported_statements=tuple(output.unsupported_statements),
        needs_source=_needs_source(output),
        protected_spans=find_protected_spans(output.draft),
        provenance=Provenance.model(
            f"{response.provider}/{response.model}",
            workflow="manuscript.draft",
            run_id=run,
            template_version=WRITER.template_version,
        ),
    )
    staged = candidate.model_copy(update={"path": _stage(ctx, candidate)})
    logger.info(
        "drafted %s: %d claim refs, %d needs-source statements",
        staged.path,
        len(staged.claim_refs),
        len(staged.needs_source),
    )
    return staged


def staged_draft(ctx: CapabilityContext, run: str) -> DraftCandidate | None:
    """Read back one staged candidate, or ``None`` when that run staged nothing."""
    path = drafts_dir(ctx) / f"{run}{DRAFT_SUFFIX}"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.pop("marked_text", None)
    return DraftCandidate.model_validate(payload)


def drafts_dir(ctx: CapabilityContext) -> Path:
    """`.research/staging/drafts/` of this workspace; created on first write."""
    return ctx.repo.layout.research_dir / STAGING_DRAFTS_DIRNAME


def selected_ids(claims: Sequence[Claim]) -> tuple[ClaimId, ...]:
    """Ids of the claims a draft was built from, in the order they were given."""
    return tuple(claim.id for claim in claims)


# ------------------------------------------------------------------------------ staging


def _stage(ctx: CapabilityContext, candidate: DraftCandidate) -> Path:
    """Write ``candidate`` under `.research/staging/drafts/`, refusing any other location."""
    directory = drafts_dir(ctx)
    path = (directory / f"{candidate.run}{DRAFT_SUFFIX}").resolve()
    staging = (ctx.repo.layout.research_dir / "staging").resolve()
    if not path.is_relative_to(staging):  # pragma: no cover - guards a misconfigured layout
        raise CapabilityError(
            f"manuscript.draft: a candidate belongs under {staging}, never at {path}; "
            "accepted manuscript text is only replaced after audit and human review "
            "(Product 30.4)"
        )
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path, json.dumps(candidate.as_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    return path


# ------------------------------------------------------------------------------- inputs


def _instructions(purpose: str, style: str | None) -> str:
    lines = [
        f"Section purpose: {purpose.strip()}",
        "Draft only this section. Every substantive sentence must trace to one of the "
        "claims you were given, and every number must be copied from the evidence.",
    ]
    if style and style.strip():
        lines.append(f"Style constraints: {style.strip()}")
    lines.append(
        f"List any sentence the section needs but the accepted state does not support in "
        f"`unsupported_statements` and `needs_source`; it will be marked {NEEDS_SOURCE!r} "
        "for the researcher."
    )
    return "\n".join(lines)


def _claims(ctx: CapabilityContext, claims: Sequence[ClaimId]) -> tuple[Claim, ...]:
    """The named claims, in the caller's order, refusing an id this workspace does not hold."""
    found: list[Claim] = []
    missing: list[str] = []
    seen: set[ClaimId] = set()
    for claim_id in claims:
        if claim_id in seen:
            continue
        seen.add(claim_id)
        try:
            found.append(ctx.repo.get_claim(claim_id))
        except ObjectNotFoundError:
            missing.append(str(claim_id))
    if missing:
        raise CapabilityError(
            f"manuscript.draft: no claim {', '.join(missing)} in this workspace; a draft is "
            "written from accepted state, never from an id the writer was handed"
        )
    return tuple(found)


def _related_evidence(
    ctx: CapabilityContext, claims: Sequence[Claim]
) -> dict[EvidenceId, Evidence]:
    """Accepted, non-stale evidence related to any of ``claims``, in claim/relation order.

    Only accepted evidence is shown: a proposed candidate is not project knowledge, and a
    stale one is a question rather than a fact (ADR-003, ADR-008).
    """
    wanted: list[EvidenceId] = []
    for claim in claims:
        for link in claim.relations:
            if link.evidence not in wanted:
                wanted.append(link.evidence)
    if not wanted:
        return {}
    available = _evidence_index(ctx)
    return {
        evidence_id: available[evidence_id]
        for evidence_id in wanted
        if evidence_id in available and _usable(available[evidence_id])
    }


def _evidence_index(ctx: CapabilityContext) -> dict[EvidenceId, Evidence]:
    return {
        item.id: item for work in ctx.repo.list_works() for item in ctx.repo.iter_evidence(work.id)
    }


def _usable(item: Evidence) -> bool:
    return item.status is EvidenceStatus.ACCEPTED and item.stale is StaleState.FRESH


def _accepted_decisions(ctx: CapabilityContext) -> tuple[Decision, ...]:
    """Accepted project Decisions, in id order; a proposed one binds nobody yet."""
    return tuple(
        decision
        for decision in ctx.repo.list_decisions()
        if decision.status is DecisionStatus.ACCEPTED
    )


def _claim_payload(claim: Claim) -> dict[str, object]:
    """What the writer needs about a claim, including the ceiling it may not exceed."""
    return {
        "id": str(claim.id),
        "statement": claim.statement,
        "type": claim.type.value,
        "scope": claim.scope.level.label,
        "status": claim.status.value,
        "allowed_strength": claim.allowed_strength.label,
        "maximum_defensible_wording": claim.assessment.maximum_defensible_wording,
        "corpus": claim.scope.corpus,
        "stale": claim.stale.value,
        "relations": [
            {"evidence": str(link.evidence), "relation": link.relation.value, "aspect": link.aspect}
            for link in claim.relations
        ],
    }


def _evidence_payload(item: Evidence) -> dict[str, object]:
    """What the writer needs about one evidence object: what it says and where it came from."""
    numeric = item.content.numeric
    return {
        "id": str(item.id),
        "work": str(item.source.work),
        "page": item.source.page,
        "origin": item.origin.value,
        "evidence_type": item.evidence_type.value,
        "strength": item.strength.value,
        "exact_text": item.content.exact_text,
        "qualification": item.qualification,
        "numeric": (
            None
            if numeric is None
            else {
                "raw": numeric.raw,
                "metric": numeric.metric,
                "unit": numeric.unit,
                "dataset": numeric.dataset,
                "condition": dict(numeric.condition),
                "source_table": numeric.source_table,
            }
        ),
    }


def _decision_payload(decision: Decision) -> dict[str, object]:
    return {
        "id": str(decision.id),
        "type": decision.type.value,
        "title": decision.title,
        "rationale": decision.rationale,
        "claim": None if decision.claim is None else str(decision.claim),
        "taxonomy_terms": list(decision.taxonomy_terms),
    }


# ------------------------------------------------------------------------------ output


def _needs_source(output: WriterOutput) -> tuple[str, ...]:
    """Every unsupported statement, marked once, with the writer's own list folded in."""
    marked: list[str] = []
    for statement in (*output.unsupported_statements, *output.needs_source):
        text = statement.strip()
        if text and text not in marked:
            marked.append(text)
    return tuple(marked)


def _checked_ids[T: (ClaimId, EvidenceId)](
    values: Sequence[str],
    id_type: type[T],
    allowed: set[T],
    label: str,
) -> tuple[T, ...]:
    """Parse the ids the writer cited, refusing any it was not given (Product 30, 30.2)."""
    parsed = [id_type(value) for value in values]
    unknown = sorted({str(value) for value in parsed if value not in allowed})
    if unknown:
        raise CapabilityError(
            f"manuscript.draft: the writer cited {label} {', '.join(unknown)}, which it was "
            "not given; a draft may not reach past the accepted state it was handed"
        )
    seen: list[T] = []
    for value in parsed:
        if value not in seen:
            seen.append(value)
    return tuple(seen)
