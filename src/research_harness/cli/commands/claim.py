"""`research claim`: create, relate, audit, override, list, show, and retire claims.

A transport and nothing more (ADR-004): it parses arguments, calls
:class:`~research_harness.claims.service.ClaimService`, and prints. Nothing here decides
what evidence defends - `research claim audit` prints the ceiling the audit computed and the
reasons behind it, and the only way past that ceiling is `research claim override`, which
writes a Decision the record keeps (Product 38).

Scope is written the way Product 10.2 writes it: `L0`-`L4`, or the level's name
(`corpus_pattern`). `--scope` on `claim create` sets both where the claim is asserted to hold
and the strength the researcher is asking for; the strength the evidence allows starts at L0
and is earned by `claim audit`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from research_harness.capabilities.context import CapabilityContext
from research_harness.claims.audit import ClaimAuditResult
from research_harness.claims.service import ClaimService, ClaimView
from research_harness.cli.context import JsonOption, WorkspaceOption, cli_errors, context_for, emit
from research_harness.cli.providers import SCRIPTED_PROVIDER as SCRIPTED_PROVIDER
from research_harness.cli.providers import optional_model_client
from research_harness.domain.claim import ClaimEvidenceRelation, ClaimScopeSpec, ClaimSemantics
from research_harness.domain.enums import (
    ClaimEvidenceRelationType,
    ClaimScope,
    ClaimStatus,
    ClaimType,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import ClaimId, EvidenceId
from research_harness.projection.schema import create_engine_for
from research_harness.retrieval.counter import RetrievalCounterEvidenceFinder
from research_harness.retrieval.service import RetrievalService

__all__ = ["SCRIPTED_PROVIDER", "register"]

RELATIONS = ", ".join(member.value for member in ClaimEvidenceRelationType)

claim_app = typer.Typer(
    name="claim",
    help="Structured claims: scope, evidence relations, audit, and overrides.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Add the `research claim ...` family to ``app``."""
    app.add_typer(claim_app, name="claim")


# -- options -----------------------------------------------------------------

ScopeOption = Annotated[
    str,
    typer.Option(
        "--scope",
        help="Claim scope ladder level: L0-L4, or its name (e.g. corpus_pattern).",
    ),
]

ProviderOption = Annotated[
    str | None,
    typer.Option(
        "--provider",
        help="Provider entry from `providers:` in research.yaml, or 'scripted' with --script.",
        show_default=False,
    ),
]

ScriptOption = Annotated[
    Path | None,
    typer.Option(
        "--script",
        help="JSON responses for the scripted provider: a list, or an object keyed by role.",
        show_default=False,
    ),
]


# -- commands ----------------------------------------------------------------


@claim_app.command("create")
def claim_create(
    statement: Annotated[str, typer.Argument(help="The claim as it would be written.")],
    workspace: WorkspaceOption = None,
    claim_type: Annotated[
        str, typer.Option("--type", help=f"Claim type: {_names(ClaimType)}.")
    ] = ClaimType.DESCRIPTIVE.value,
    scope: ScopeOption = "L0",
    corpus: Annotated[
        str | None, typer.Option("--corpus", help="Corpus the claim is asserted over.")
    ] = None,
    until: Annotated[
        str | None, typer.Option("--until", help="Publication cutoff as YYYY-MM.")
    ] = None,
    subject: Annotated[str, typer.Option("--subject", help="Proposition subject.")] = "",
    predicate: Annotated[str, typer.Option("--predicate", help="Proposition predicate.")] = "",
    obj: Annotated[str, typer.Option("--object", help="Proposition object.")] = "",
    qualifier: Annotated[
        list[str] | None,
        typer.Option("--qualifier", help="Proposition qualifier as key=value; repeatable."),
    ] = None,
    supports: Annotated[
        list[str] | None,
        typer.Option("--supports", help="Supporting evidence E####[:aspect]; repeatable."),
    ] = None,
    qualifies: Annotated[
        list[str] | None,
        typer.Option("--qualifies", help="Qualifying evidence E####[:aspect]; repeatable."),
    ] = None,
    contradicts: Annotated[
        list[str] | None,
        typer.Option("--contradicts", help="Counter-evidence E####[:aspect]; repeatable."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Register a structured claim (`claim.create`).

    The claim is created `unverified` at L0 whatever `--scope` asks for: the requested scope
    is the researcher's ask and the allowed scope is what an audit earns (Product 42.G).
    """
    with cli_errors():
        ctx = context_for(workspace)
        level = _scope(scope)
        relations = [
            *_relations(supports, ClaimEvidenceRelationType.SUPPORTS),
            *_relations(qualifies, ClaimEvidenceRelationType.QUALIFIES),
            *_relations(contradicts, ClaimEvidenceRelationType.CONTRADICTS),
        ]
        claim, mutation = _service(ctx).create(
            statement,
            type=_enum(ClaimType, claim_type, "claim type"),
            semantics=ClaimSemantics(
                subject=subject or statement,
                predicate=predicate or "asserts",
                object=obj or statement,
                qualifier=_qualifiers(qualifier),
            ),
            scope=ClaimScopeSpec(level=level, corpus=corpus, publication_until=until),
            requested_strength=level,
            relations=relations,
        )
        payload = {"claim": str(claim.id), "mutation": mutation.as_dict(), **_claim_payload(claim)}
        emit(payload, _create_lines(claim), as_json=as_json)


@claim_app.command("relate")
def claim_relate(
    claim: Annotated[str, typer.Argument(help="Claim to link (C####).")],
    evidence: Annotated[str, typer.Argument(help="Evidence to link (E####).")],
    relation: Annotated[str, typer.Argument(help=f"Relation: {RELATIONS}.")],
    workspace: WorkspaceOption = None,
    aspect: Annotated[
        str | None,
        typer.Option("--aspect", help="Aspect of the claim this relation is about."),
    ] = None,
    note: Annotated[
        str | None, typer.Option("--note", help="Why the evidence relates this way.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Link evidence to a claim (`claim.relate`).

    Relations are many-to-many: the same evidence may support one aspect of a claim and
    qualify another, and both edges stand at once (Product 10.4).
    """
    with cli_errors():
        ctx = context_for(workspace)
        record, mutation = _service(ctx).relate(
            ClaimId(claim),
            EvidenceId(evidence),
            _enum(ClaimEvidenceRelationType, relation, "relation"),
            aspect=aspect,
            note=note,
        )
        payload = {
            "claim": str(record.id),
            "relations": [_relation_payload(link) for link in record.relations],
            "mutation": mutation.as_dict(),
        }
        emit(payload, _relate_lines(record.id, mutation.event.summary), as_json=as_json)


@claim_app.command("unrelate")
def claim_unrelate(
    claim: Annotated[str, typer.Argument(help="Claim to unlink (C####).")],
    evidence: Annotated[str, typer.Argument(help="Evidence to unlink (E####).")],
    relation: Annotated[str, typer.Argument(help=f"Relation: {RELATIONS}.")],
    workspace: WorkspaceOption = None,
    aspect: Annotated[
        str | None, typer.Option("--aspect", help="Aspect the relation was recorded under.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Remove one claim-evidence edge (`claim.unrelate`); the claim's other edges stay."""
    with cli_errors():
        ctx = context_for(workspace)
        record, mutation = _service(ctx).unrelate(
            ClaimId(claim),
            EvidenceId(evidence),
            _enum(ClaimEvidenceRelationType, relation, "relation"),
            aspect=aspect,
        )
        payload = {
            "claim": str(record.id),
            "relations": [_relation_payload(link) for link in record.relations],
            "mutation": mutation.as_dict(),
        }
        emit(payload, _relate_lines(record.id, mutation.event.summary), as_json=as_json)


@claim_app.command("audit")
def claim_audit(
    claim: Annotated[str, typer.Argument(help="Claim to audit (C####).")],
    workspace: WorkspaceOption = None,
    provider: ProviderOption = None,
    script: ScriptOption = None,
    durable: Annotated[
        bool,
        typer.Option("--durable", help="Run the audit as a resumable, checkpointed workflow."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Audit a claim and record what the evidence allows (`claim.audit`).

    Prints the maximum defensible wording, the allowed scope beside the requested one, the
    support, qualifiers and counter-evidence the audit read, the relations it proposes
    reclassifying, its independence and coverage doubts, and any provider disagreement. An
    audit can only lower the ceiling; raising it takes `research claim override`.
    """
    with cli_errors():
        ctx = context_for(workspace)
        client = optional_model_client(ctx, provider, script)
        with _auditing_service(ctx) as service:
            record, result, mutation = service.audit(
                ClaimId(claim), skeptic=client, auditor=client, durable=durable
            )
        payload = {
            **_audit_payload(result),
            **_claim_payload(record),
            "mutation": mutation.as_dict(),
        }
        emit(payload, _audit_lines(record.id, result, payload), as_json=as_json)


@claim_app.command("override")
def claim_override(
    claim: Annotated[str, typer.Argument(help="Claim to override (C####).")],
    workspace: WorkspaceOption = None,
    scope: ScopeOption = "L0",
    rationale: Annotated[
        str, typer.Option("--rationale", help="Why the auditor's ceiling is being overruled.")
    ] = "",
    as_json: JsonOption = False,
) -> None:
    """Overrule the claim auditor, visibly (`claim.override_strength`).

    The override is a Decision first: the recommendation it overrides, the scope chosen
    instead, and the reason are recorded and accepted before the claim moves, and everything
    resting on the old ceiling is marked stale rather than rewritten (Product 38, ADR-008).
    """
    with cli_errors():
        ctx = context_for(workspace)
        record, decision, mutation = _service(ctx).override(
            ClaimId(claim), selected=_scope(scope), rationale=rationale
        )
        payload = {
            "decision": str(decision.id),
            "auditor_recommendation": _scope_value(decision.auditor_recommendation),
            "researcher_selected": _scope_value(decision.researcher_selected),
            "rationale": decision.rationale,
            "mutation": mutation.as_dict(),
            **_claim_payload(record),
        }
        emit(payload, _override_lines(payload, mutation.stale), as_json=as_json)


@claim_app.command("supersede")
def claim_supersede(
    claim: Annotated[str, typer.Argument(help="Claim to retire (C####).")],
    workspace: WorkspaceOption = None,
    by: Annotated[str | None, typer.Option("--by", help="Claim that replaces it (C####).")] = None,
    reason: Annotated[str, typer.Option("--reason", help="Why the claim is retired.")] = "",
    as_json: JsonOption = False,
) -> None:
    """Retire a claim (`claim.supersede`); superseded is terminal."""
    with cli_errors():
        ctx = context_for(workspace)
        record, mutation = _service(ctx).supersede(
            ClaimId(claim), ClaimId(by) if by else None, reason
        )
        payload = {"superseded_by": by, "mutation": mutation.as_dict(), **_claim_payload(record)}
        emit(payload, [f"{record.id} superseded"], as_json=as_json)


@claim_app.command("list")
def claim_list(
    workspace: WorkspaceOption = None,
    status: Annotated[
        str | None, typer.Option("--status", help=f"Only this status: {_names(ClaimStatus)}.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """List claims with their status and the gap between requested and allowed scope."""
    with cli_errors():
        ctx = context_for(workspace)
        selected = _enum(ClaimStatus, status, "claim status") if status else None
        claims = [_claim_payload(claim) for claim in _service(ctx).list(selected)]
        emit({"claims": claims}, _list_lines(claims), as_json=as_json)


@claim_app.command("show")
def claim_show(
    claim: Annotated[str, typer.Argument(help="Claim to show (C####).")],
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Show one claim: relations by kind, decisions, coverage, and what depends on it."""
    with cli_errors():
        ctx = context_for(workspace)
        view = _service(ctx).show(ClaimId(claim))
        emit(view.as_dict(), _show_lines(view), as_json=as_json)


# -- payloads ----------------------------------------------------------------


def _claim_payload(claim: Any) -> dict[str, Any]:
    return {
        "id": str(claim.id),
        "statement": claim.statement,
        "type": claim.type.value,
        "status": claim.status.value,
        "requested_strength": claim.requested_strength.value,
        "allowed_strength": claim.allowed_strength.value,
        "requested_level": claim.requested_strength.level,
        "allowed_level": claim.allowed_strength.level,
        "escalation_prevented": claim.allowed_strength < claim.requested_strength,
        "maximum_defensible_wording": claim.assessment.maximum_defensible_wording,
        "relations": [_relation_payload(link) for link in claim.relations],
        "decisions": [str(decision) for decision in claim.decisions],
        "stale": claim.stale.value,
    }


def _relation_payload(link: ClaimEvidenceRelation) -> dict[str, Any]:
    return {
        "evidence": str(link.evidence),
        "relation": link.relation.value,
        "aspect": link.aspect,
        "note": link.note,
    }


def _audit_payload(result: ClaimAuditResult) -> dict[str, Any]:
    return {
        "maximum_defensible_wording": result.maximum_defensible_wording,
        "recommended_scope": result.recommended_scope.value,
        "support": [str(item) for item in result.support],
        "qualifiers": [str(item) for item in result.qualifiers],
        "qualifier_notes": list(result.qualifier_notes),
        "counter_evidence": [str(item) for item in result.counter_evidence],
        "counter_candidates": [item.model_dump(mode="json") for item in result.counter_candidates],
        "incomparable": [item.model_dump(mode="json") for item in result.incomparable],
        "independence_warnings": list(result.independence.warnings),
        "coverage_state": result.coverage_state,
        "warnings": list(result.warnings),
        "reasons": list(result.assessment.reasons),
        "blocked_by": list(result.assessment.blocked_by),
        "conflict": result.conflict.model_dump(mode="json") if result.conflict else None,
        "cross_verification": (
            result.cross_verification.model_dump(mode="json") if result.cross_verification else None
        ),
    }


# -- lines -------------------------------------------------------------------


def _create_lines(claim: Any) -> list[str]:
    return [
        f"created {claim.id} ({claim.type.value}, {claim.status.value})",
        f"  requested {claim.requested_strength.label}; "
        f"allowed {claim.allowed_strength.label} until audited",
        f"  relations: {len(claim.relations)}",
    ]


def _relate_lines(claim_id: ClaimId, summary: str) -> list[str]:
    return [f"{claim_id}: {summary}"]


def _audit_lines(claim_id: ClaimId, result: ClaimAuditResult, payload: dict[str, Any]) -> list[str]:
    allowed = ClaimScope(payload["allowed_strength"])
    requested = ClaimScope(payload["requested_strength"])
    lines = [
        f"audited {claim_id}: {payload['status']}",
        f"  maximum defensible wording: {result.maximum_defensible_wording}",
        f"  allowed {allowed.label}; requested {requested.label}",
    ]
    if payload["escalation_prevented"]:
        lines.append("  escalation prevented: the evidence does not defend the requested scope")
    lines.extend(_bullets("support", payload["support"]))
    lines.extend(_bullets("qualifiers", payload["qualifiers"]))
    lines.extend(_bullets("qualifier notes", payload["qualifier_notes"]))
    lines.extend(_bullets("counter-evidence", payload["counter_evidence"]))
    candidates = [
        f"{item['ref']} ({item['source']}) {item['location']}".strip()
        for item in payload["counter_candidates"]
    ]
    proposals = [
        f"{item['evidence']}: {item['current']} -> {item['proposed']}"
        for item in payload["incomparable"]
    ]
    lines.extend(_bullets("counter-evidence candidates", candidates))
    lines.extend(_bullets("proposed reclassifications", proposals))
    lines.extend(_bullets("independence warnings", payload["independence_warnings"]))
    lines.append(f"  coverage: {payload['coverage_state']}")
    lines.extend(_bullets("reasons", payload["reasons"]))
    lines.extend(_bullets("warnings", payload["warnings"]))
    if payload["conflict"] is not None:
        lines.append("  cross-verification conflict: providers disagree; resolve it in review")
    return lines


def _override_lines(payload: dict[str, Any], stale: tuple[Any, ...]) -> list[str]:
    lines = [
        f"{payload['id']}: override accepted as {payload['decision']}",
        f"  auditor recommended {payload['auditor_recommendation']}; "
        f"researcher selected {payload['researcher_selected']}",
        f"  rationale: {payload['rationale']}",
    ]
    lines.extend(_bullets("marked stale", [mark.object_id for mark in stale]))
    return lines


def _list_lines(claims: list[dict[str, Any]]) -> list[str]:
    if not claims:
        return ["no claims yet"]
    width = max(len(claim["id"]) for claim in claims)
    return [
        f"{claim['id'].ljust(width)}  {claim['status']:<12} "
        f"allowed L{claim['allowed_level']} / requested L{claim['requested_level']}  "
        f"{claim['statement']}"
        for claim in claims
    ]


def _show_lines(view: ClaimView) -> list[str]:
    claim = view.claim
    lines = [
        f"{claim.id}  {claim.type.value}  {claim.status.value}",
        f"  {claim.statement}",
        f"  allowed {claim.allowed_strength.label}; requested {claim.requested_strength.label}",
        f"  wording: {view.wording or '(not audited)'}",
        f"  coverage: {view.coverage}",
    ]
    if view.audit_is_older_than_relations:
        lines.append("  the relations changed after the last audit; re-audit this claim")
    lines.extend(_relation_lines("support", view.support))
    lines.extend(_relation_lines("qualifiers", view.qualifiers))
    lines.extend(_relation_lines("counter-evidence", view.contradictions))
    lines.extend(_relation_lines("incomparable", view.incomparable))
    lines.extend(_relation_lines("context", view.context))
    lines.extend(
        _bullets(
            "decisions",
            [
                f"{item.id} {item.type.value} ({item.status.value}): {item.rationale}"
                for item in view.decisions
            ],
        )
    )
    lines.extend(_bullets("depends on this claim", [mark.object_id for mark in view.stale]))
    history = [f"{event.occurred_at:%Y-%m-%d} {event.summary}" for event in view.history]
    lines.extend(_bullets("history", history))
    return lines


def _relation_lines(label: str, links: tuple[ClaimEvidenceRelation, ...]) -> list[str]:
    return _bullets(
        label,
        [
            f"{link.evidence}{'' if link.aspect is None else f' [{link.aspect}]'}"
            f"{'' if link.note is None else f' - {link.note}'}"
            for link in links
        ],
    )


def _bullets(label: str, values: list[str]) -> list[str]:
    if not values:
        return []
    return [f"  {label}:", *(f"    - {value}" for value in values)]


# -- parsing -----------------------------------------------------------------


def _service(ctx: CapabilityContext) -> ClaimService:
    return ClaimService(ctx)


@contextmanager
def _auditing_service(ctx: CapabilityContext) -> Iterator[ClaimService]:
    """The service with counter-evidence retrieval attached, when there is an index to search.

    A missing projection is not an error: the audit still computes its ceiling, its
    independence accounting and its coverage state, and simply reports no retrieval
    candidates. `research rebuild` is what turns the search back on (ADR-006).
    """
    database = ctx.repo.layout.database_file
    if not database.is_file():
        yield ClaimService(ctx)
        return
    engine = create_engine_for(database)
    try:
        finder = RetrievalCounterEvidenceFinder(RetrievalService(engine, ctx.repo))
        yield ClaimService(ctx, counter_finder=finder)
    finally:
        engine.dispose()


def _names(enum_type: type[ClaimType] | type[ClaimStatus]) -> str:
    return ", ".join(member.value for member in enum_type)


def _enum[T: (ClaimType, ClaimStatus, ClaimEvidenceRelationType)](
    enum_type: type[T], value: str, label: str
) -> T:
    try:
        return enum_type(value)
    except ValueError:
        known = ", ".join(member.value for member in enum_type)
        raise CapabilityError(f"unknown {label} {value!r}; known: {known}") from None


def _scope(value: str) -> ClaimScope:
    """`L0`-`L4`, or a ladder level's own name."""
    text = value.strip()
    if len(text) == 2 and text[0] in "Ll" and text[1].isdigit():
        try:
            return ClaimScope.from_level(int(text[1]))
        except ValueError:
            pass
    try:
        return ClaimScope(text.lower())
    except ValueError:
        known = ", ".join(f"L{member.level} {member.value}" for member in ClaimScope)
        raise CapabilityError(f"unknown scope {value!r}; known: {known}") from None


def _scope_value(scope: ClaimScope | None) -> str | None:
    return None if scope is None else scope.label


def _qualifiers(values: list[str] | None) -> dict[str, str]:
    qualifiers: dict[str, str] = {}
    for item in values or []:
        key, separator, value = item.partition("=")
        if not separator or not key.strip():
            raise CapabilityError(f"--qualifier expects key=value, got {item!r}")
        qualifiers[key.strip()] = value.strip()
    return qualifiers


def _relations(
    values: list[str] | None, relation: ClaimEvidenceRelationType
) -> list[ClaimEvidenceRelation]:
    """`E0132` or `E0132:tokenizer granularity`, repeated once per edge."""
    links: list[ClaimEvidenceRelation] = []
    for item in values or []:
        reference, separator, aspect = item.partition(":")
        links.append(
            ClaimEvidenceRelation(
                evidence=EvidenceId(reference.strip()),
                relation=relation,
                aspect=aspect.strip() if separator and aspect.strip() else None,
            )
        )
    return links


# -- provider selection ------------------------------------------------------
#
# `cli/providers.py` owns it. `optional_model_client` returns `None` when the caller named
# neither a provider nor a script, because the deterministic audit *is* the audit
# (ROADMAP 7.4): the ladder, the independence accounting, and the coverage state still
# produce a ceiling, and the model passes are simply not run.
