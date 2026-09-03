"""The evidence loop on the command line: interrogate, verify, inbox, review, session.

This is the v0.1 daily loop of Product §27 and ROADMAP Task 6.4. It is a transport and
nothing more: every accepted-state change goes through `EvidenceReviewService`, which goes
through `capabilities/` (ADR-004). Interrogation and verification write only to
`.research/` — a run that hallucinates, fails, or is cancelled leaves the scientific record
byte-identical, which is the property Gate P6 checks by deleting `.research/` and rebuilding.

Providers are configuration, never code (Product §20.2). `--provider NAME` selects an entry
of the `providers:` list in `research.yaml`; `--provider scripted --script FILE` runs the
in-process scripted adapter, so the whole loop is demonstrable and testable offline with no
key and no network.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any

import typer
from typer.core import TyperGroup

from research_harness.capabilities.context import CapabilityContext
from research_harness.cli.context import (
    JsonOption,
    WorkspaceOption,
    cli_errors,
    context_for,
    emit,
)
from research_harness.cli.plugins import PLUGIN_SCHEMA_PREFIX, plugin_interrogation_schema
from research_harness.cli.providers import SCRIPTED_PROVIDER as SCRIPTED_PROVIDER
from research_harness.cli.providers import load_router as load_router
from research_harness.cli.providers import resolve_model_client
from research_harness.domain.enums import ReviewAction, StaleState
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.evidence import Evidence, NumericValue
from research_harness.domain.ids import ArtifactId, WorkId
from research_harness.evidence.interrogation import DEFAULT_SCHEMA, InterrogationSchema
from research_harness.evidence.review import (
    ReviewCategory,
    ReviewItem,
    ReviewQueue,
    SessionSummary,
    session_summary,
)
from research_harness.evidence.service import BatchResult, EvidenceReviewService
from research_harness.evidence.staging import StagingStore
from research_harness.workflows.engine import WorkflowEngine
from research_harness.workflows.interrogate import InterrogationReport, run_interrogation
from research_harness.workflows.verify import VerificationReport, run_verification
from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.runs import RunStore

__all__ = ["SCRIPTED_PROVIDER", "load_router", "register"]

_WORK_ID = re.compile(WorkId.pattern())

#: Interrogation schemas reachable by name. `--schema` also accepts `plugin:<name>[:<schema>]`
#: for a domain plugin's questions, or a path to a JSON file (Product §32.2).
SCHEMAS: Mapping[str, InterrogationSchema] = {DEFAULT_SCHEMA.name: DEFAULT_SCHEMA}


class _ReviewGroup(TyperGroup):
    """Routes `research review <candidate_id>` to the review command, `batch` to the batch.

    A candidate id is an argument, not a subcommand, but `research review batch` has to keep
    working: an unknown first token is handed to the `candidate` command with the token
    still in place, and everything else resolves normally.
    """

    def resolve_command(
        self, ctx: Any, args: list[str]
    ) -> tuple[str | None, Any | None, list[str]]:
        if args and not args[0].startswith("-") and args[0] not in self.commands:
            command = self.commands["candidate"]
            return command.name, command, args
        return super().resolve_command(ctx, args)


review_app = typer.Typer(
    name="review",
    cls=_ReviewGroup,
    help="Answer the review queue: accept, qualify, edit, split, reject, defer, request more.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Add the evidence loop commands to ``app``."""
    app.command("interrogate")(interrogate)
    app.command("verify")(verify)
    app.command("inbox")(inbox)
    app.command("conflicts")(conflicts)
    app.command("stale")(stale)
    app.command("session")(session)
    app.add_typer(review_app, name="review")


# -- options -----------------------------------------------------------------

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


def interrogate(
    work: Annotated[str, typer.Argument(help="Work to interrogate (W####).")],
    workspace: WorkspaceOption = None,
    provider: ProviderOption = None,
    script: ScriptOption = None,
    fields: Annotated[
        list[str] | None,
        typer.Option(
            "--field",
            help="Field(s) to ask: repeatable, and comma-separated (`--field dataset,baseline`).",
            show_default=False,
        ),
    ] = None,
    except_fields: Annotated[
        list[str] | None,
        typer.Option(
            "--except-field",
            help="Ask every field of the schema except these; repeatable and comma-separated.",
            show_default=False,
        ),
    ] = None,
    schema: Annotated[
        str | None,
        typer.Option(
            "--schema",
            help=(
                "Interrogation schema: a built-in name, `plugin:<plugin-name>[:<schema>]` "
                "for a domain plugin's questions, or a path to a JSON file."
            ),
            show_default=False,
        ),
    ] = None,
    artifact: Annotated[
        str | None,
        typer.Option("--artifact", help="Interrogate this artifact (A####)."),
    ] = None,
    rerun: Annotated[
        bool,
        typer.Option("--rerun", help="Re-run every stage instead of reusing checkpoints."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Ask a Work the interrogation schema's questions; every answer lands in staging.

    Nothing here can change accepted state: candidates are proposals with a source anchor
    and no authority until a researcher accepts them (Product §8.3).
    """
    with cli_errors():
        ctx = context_for(workspace)
        staging, engine = _runtime(ctx.repo)
        contract = _schema(ctx, schema)
        # Which questions to ask is settled before a backend is chosen: a mistyped field
        # should be refused by name, not by "no model providers configured" (dogfood F19).
        selected = _selected_fields(contract, fields, except_fields)
        report = run_interrogation(
            engine,
            staging,
            ctx.repo,
            WorkId(work),
            resolve_model_client(ctx, provider, script),
            contract,
            fields=selected,
            artifact=ArtifactId(artifact) if artifact else None,
            force=rerun,
        )
        emit(_interrogate_payload(report), _interrogate_lines(report), as_json=as_json)


def verify(
    target: Annotated[str, typer.Argument(help="Work (W####) or one candidate id.")],
    workspace: WorkspaceOption = None,
    provider: ProviderOption = None,
    script: ScriptOption = None,
    rerun: Annotated[
        bool,
        typer.Option("--rerun", help="Verify again even when a verdict already exists."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Check staged candidates against their source spans with an independent reader.

    The verifier sees the span and the assertion, never the extractor's reasoning: agreement
    between two readers only carries information when the second did not read the first
    (ADR-003).
    """
    with cli_errors():
        ctx = context_for(workspace)
        staging, engine = _runtime(ctx.repo)
        work, candidates = _verify_target(staging, target)
        report = run_verification(
            engine,
            staging,
            ctx.repo,
            work,
            resolve_model_client(ctx, provider, script),
            candidate_ids=candidates,
            force=rerun,
        )
        emit(_verify_payload(report), _verify_lines(report), as_json=as_json)


def inbox(
    workspace: WorkspaceOption = None,
    work: Annotated[str | None, typer.Option("--work", help="Only this Work (W####).")] = None,
    category: Annotated[
        str | None,
        typer.Option("--category", help="Only one category: conflict, high_risk, stale, ..."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=0, help="Show at most this many items; 0 shows all of them."),
    ] = 20,
    as_json: JsonOption = False,
) -> None:
    """The review queue in Product §24.2 order: conflicts first, routine last.

    Only the first `--limit` items are printed. The header says how many of how many, and
    `--limit 0` prints the whole queue: a researcher working the list top to bottom must
    never be able to believe they cleared it when they cleared a page of it (dogfood F8).
    """
    with cli_errors():
        ctx = context_for(workspace)
        queue = _service(ctx).inbox(WorkId(work) if work else None)
        items = _filtered(queue, category)
        shown = _shown(items, limit)
        payload = {
            "count": len(items),
            # `shown` and `limit` beside `count`, because `--json` carried `count: 39` with
            # 20 items in it and nothing said so (dogfood F8).
            "shown": len(shown),
            "limit": limit,
            "counts": {name.value: count for name, count in queue.counts.items()},
            "items": [item.as_dict() for item in shown],
        }
        emit(payload, _inbox_lines(items, shown, queue.counts), as_json=as_json)


@review_app.command("candidate")
def review_candidate(
    candidate_id: Annotated[str, typer.Argument(help="Staged candidate id (cand_<16 hex>).")],
    workspace: WorkspaceOption = None,
    accept: Annotated[bool, typer.Option("--accept", help="Accept as canonical Evidence.")] = False,
    qualify: Annotated[
        str | None,
        typer.Option("--qualify", help="Accept with an explicit qualification."),
    ] = None,
    edit: Annotated[
        Path | None,
        typer.Option("--edit", help="Accept a corrected Evidence read from this JSON file."),
    ] = None,
    reject: Annotated[
        str | None, typer.Option("--reject", help="Refuse the candidate, with a reason.")
    ] = None,
    defer: Annotated[str | None, typer.Option("--defer", help="Put it aside, with a note.")] = None,
    request_more: Annotated[
        str | None,
        typer.Option("--request-more", help="Ask for more evidence; captured as a note."),
    ] = None,
    split: Annotated[
        bool,
        typer.Option(
            "--split",
            help="Accept the source fact and deal with its interpretation separately.",
        ),
    ] = False,
    interpretation: Annotated[
        str | None,
        typer.Option(
            "--interpretation", help="With --split: stage this reading for its own review."
        ),
    ] = None,
    reject_interpretation: Annotated[
        str | None,
        typer.Option(
            "--reject-interpretation", help="With --split: refuse the reading, with a reason."
        ),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Show one review item, or answer it. Exactly one action, and the researcher takes it.

    **With no action flag this prints the item** — its verdict, the discrepancies the
    verifier recorded, the competing answers, and the source span with the text around it —
    so an honest rejection costs one command rather than a JSON blob in another window
    (dogfood F12).

    **This command is the human gate.** It is the researcher acting in person, so it accepts
    any tier, an interpretive candidate included; that is what a review gate is *for*. The
    conditions live on `research review batch`, which is refused outright unless the project
    declares `review_policy: policy_batch` and which never accepts a Tier-2 candidate
    (Product §24.4, ADR-007, §42 H). What is refused here is an actor that is not the
    researcher — a model or an agent host reaching the same capability over MCP.

    `--split` is partial acceptance (Product §24.3): the source fact is accepted with the
    candidate's own anchor, and the reading attached to it is either staged as its own
    Tier-2 candidate (`--interpretation`) or refused with a reason
    (`--reject-interpretation`). Exactly one accepted Evidence results either way.
    """
    with cli_errors():
        if not _any_action(
            accept=accept,
            qualify=qualify,
            edit=edit,
            reject=reject,
            defer=defer,
            request_more=request_more,
            split=split,
        ):
            ctx = context_for(workspace)
            item = _item_for(_service(ctx), candidate_id)
            emit(item.as_dict(), _detail_lines(item), as_json=as_json)
            return
        chosen = _one_action(
            accept=accept,
            qualify=qualify,
            edit=edit,
            reject=reject,
            defer=defer,
            request_more=request_more,
            split=split,
        )
        if chosen == "split" and not (interpretation or reject_interpretation):
            raise ResearchHarnessError(
                "--split needs --interpretation TEXT (stage the reading for its own review) "
                "or --reject-interpretation REASON (refuse it)"
            )
        ctx = context_for(workspace)
        service = _service(ctx)
        payload = _review_action(
            service,
            candidate_id,
            chosen,
            qualify,
            edit,
            reject,
            defer,
            request_more,
            interpretation=interpretation,
            reject_interpretation=reject_interpretation,
        )
        emit(payload, _review_lines(payload), as_json=as_json)


@review_app.command("next")
def review_next(
    workspace: WorkspaceOption = None,
    work: Annotated[str | None, typer.Option("--work", help="Only this Work (W####).")] = None,
    category: Annotated[
        str | None,
        typer.Option("--category", help="Only one category: conflict, high_risk, stale, ..."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Show the next item to review, in Product §24.2 order, with its source context.

    The queue is already ordered — conflicts first, routine last — so "what should I look
    at now" has an answer, and walking it is `research review next`, act, repeat, instead of
    reading an id out of `research inbox` every time (dogfood F12).
    """
    with cli_errors():
        ctx = context_for(workspace)
        queue = _service(ctx).inbox(WorkId(work) if work else None)
        items = _filtered(queue, category)
        if not items:
            emit({"remaining": 0, "item": None}, ["nothing left to review"], as_json=as_json)
            return
        item = items[0]
        payload = {"remaining": len(items), "item": item.as_dict()}
        lines = [f"{len(items)} item(s) left; next in Product 24.2 order:", ""]
        emit(payload, [*lines, *_detail_lines(item)], as_json=as_json)


@review_app.command("batch")
def review_batch(
    workspace: WorkspaceOption = None,
    work: Annotated[str | None, typer.Option("--work", help="Only this Work (W####).")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Report what would be accepted; change nothing.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Accept every candidate meeting the deterministic conditions of Product §24.4.

    Refused outright unless the workspace's `review_policy` is `policy_batch`: strict review
    is the default, and a batch is an exception a researcher declares in `research.yaml`
    (ADR-007). Model confidence is never one of the conditions.
    """
    with cli_errors():
        ctx = context_for(workspace)
        result = _service(ctx).accept_batch(work=WorkId(work) if work else None, dry_run=dry_run)
        emit(result.as_dict(), _batch_lines(result), as_json=as_json)


def conflicts(
    workspace: WorkspaceOption = None,
    work: Annotated[str | None, typer.Option("--work", help="Only this Work (W####).")] = None,
    as_json: JsonOption = False,
) -> None:
    """Everything the system disagrees about, which is what to look at first (Product §25)."""
    with cli_errors():
        ctx = context_for(workspace)
        queue = _service(ctx).inbox(WorkId(work) if work else None)
        items = queue.by_category(ReviewCategory.CONFLICT)
        payload = {
            "count": len(items),
            "items": [item.as_dict() for item in items],
            # Materialized conflict records, claim-level ones included (Task 13.2).
            "conflicts": [record.as_dict() for record in queue.conflicts],
        }
        emit(payload, _conflict_lines(items), as_json=as_json)


def stale(
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Anchors that no longer replay, and accepted objects marked stale (Product §37).

    Nothing is repaired here. A stale anchor is reported and left alone: silently rewriting
    it would move the source an accepted conclusion rests on (ADR-008).
    """
    with cli_errors():
        ctx = context_for(workspace)
        queue = _service(ctx).inbox()
        items = queue.by_category(ReviewCategory.STALE)
        marked = [
            {"id": str(record.id), "work": str(record.source.work), "field": record.content.field}
            for work in ctx.repo.list_works()
            for record in ctx.repo.iter_evidence(work.id)
            if record.stale is StaleState.STALE
        ]
        payload = {
            "candidates": [item.as_dict() for item in items],
            "accepted_evidence": marked,
        }
        emit(payload, _stale_lines(items, marked), as_json=as_json)


def session(
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """What this workspace looks like at the end of a working session (Product §39)."""
    with cli_errors():
        ctx = context_for(workspace)
        summary = session_summary(ctx.repo, StagingStore(ctx.repo.layout.research_dir))
        emit(summary.as_dict(), _session_lines(summary), as_json=as_json)


# -- provider selection ------------------------------------------------------
#
# `cli/providers.py` owns it: `load_router` is re-exported above so existing importers of
# `cli.commands.evidence.load_router` keep working.


def _schema(ctx: CapabilityContext, name: str | None) -> InterrogationSchema:
    """The interrogation schema to ask with.

    Four forms, in the order they are tried: nothing (the core schema), a registered name,
    `plugin:<plugin-name>[:<schema>]` for a domain plugin's merged questions, and a path to
    a JSON file.
    """
    if name is None:
        return DEFAULT_SCHEMA
    if name in SCHEMAS:
        return SCHEMAS[name]
    if name.startswith(PLUGIN_SCHEMA_PREFIX):
        return plugin_interrogation_schema(ctx, name)
    path = Path(name)
    if path.is_file():
        try:
            return InterrogationSchema.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise ResearchHarnessError(f"cannot read interrogation schema {path}: {exc}") from exc
    raise ResearchHarnessError(
        f"unknown interrogation schema {name!r}; known: {', '.join(sorted(SCHEMAS))}, "
        f"{PLUGIN_SCHEMA_PREFIX}<plugin-name>[:<schema>], or a path to a JSON file"
    )


# -- plumbing ----------------------------------------------------------------


def _runtime(repo: WorkspaceRepository) -> tuple[StagingStore, WorkflowEngine]:
    """The two disposable stores a run needs, both under `.research/`."""
    research_dir = repo.layout.research_dir
    return StagingStore(research_dir), WorkflowEngine(RunStore(research_dir))


def _service(ctx: CapabilityContext) -> EvidenceReviewService:
    return EvidenceReviewService(ctx, StagingStore(ctx.repo.layout.research_dir))


def _verify_target(staging: StagingStore, target: str) -> tuple[WorkId, list[str] | None]:
    """Resolve `W####` to the whole Work, or a candidate id to that one candidate."""
    if _WORK_ID.fullmatch(target):
        return WorkId(target), None
    candidate = staging.get(target)
    return candidate.work, [candidate.candidate_id]


def _any_action(**flags: object) -> bool:
    """True when the caller asked for an action at all; false means "just show it" (F12)."""
    return any(value not in (None, False) for value in flags.values())


def _one_action(**flags: object) -> str:
    """The single review action asked for; refuse zero or several."""
    chosen = [name for name, value in flags.items() if value not in (None, False)]
    if len(chosen) != 1:
        options = ", ".join(f"--{name.replace('_', '-')}" for name in flags)
        raise ResearchHarnessError(f"give exactly one review action ({options})")
    return chosen[0]


def _item_for(service: EvidenceReviewService, candidate_id: str) -> ReviewItem:
    """The inbox item for one candidate, so showing it and listing it agree exactly.

    Read through the queue rather than off staging: the verdict is on the candidate, but the
    category, the competing answers, and the source context are computed by `build_inbox`,
    and a second way of computing them would be a second answer.
    """
    candidate = service.staging.get(candidate_id)
    queue = service.inbox(candidate.work)
    for item in queue.items:
        if item.candidate_id == candidate_id:
            return item
    raise ResearchHarnessError(
        f"candidate {candidate_id} is not in the review queue: it is "
        f"{candidate.status.value}, and only unreviewed candidates are reviewable"
    )


def _selected_fields(
    schema: InterrogationSchema, fields: Sequence[str] | None, excluded: Sequence[str] | None
) -> list[str] | None:
    """The fields to ask: named ones, or every field bar the excluded ones (dogfood F19).

    Both options split on commas and both repeat, so `--field a,b`, `--field a --field b`,
    and `--field a,b --field c` all mean what they look like. Naming a field the schema does
    not ask for is refused by name rather than silently dropped.
    """
    named = _field_list(fields)
    skipped = _field_list(excluded)
    if named and skipped:
        raise ResearchHarnessError("give --field or --except-field, not both")
    for name in (*named, *skipped):
        schema.field(name)  # raises UnknownFieldError, which names the schema's questions
    if skipped:
        remaining = [name for name in schema.names if name not in set(skipped)]
        if not remaining:
            raise ResearchHarnessError(
                f"--except-field excludes every field of {schema.name}@{schema.version}"
            )
        return remaining
    return named or None


def _field_list(values: Sequence[str] | None) -> list[str]:
    """One flat list from repeated and comma-separated values, order and duplicates kept once."""
    found: list[str] = []
    for value in values or ():
        for name in value.split(","):
            cleaned = name.strip()
            if cleaned and cleaned not in found:
                found.append(cleaned)
    return found


def _shown(items: Sequence[ReviewItem], limit: int) -> tuple[ReviewItem, ...]:
    """The page `--limit` asks for; `0` is the whole queue (dogfood F8)."""
    return tuple(items) if limit == 0 else tuple(items[:limit])


def _review_action(
    service: EvidenceReviewService,
    candidate_id: str,
    chosen: str,
    qualify: str | None,
    edit: Path | None,
    reject: str | None,
    defer: str | None,
    request_more: str | None,
    *,
    interpretation: str | None = None,
    reject_interpretation: str | None = None,
) -> dict[str, Any]:
    """Run the chosen review action and describe what it did."""
    match chosen:
        case "split":
            return _split_payload(service, candidate_id, interpretation, reject_interpretation)
        case "accept":
            result = service.accept(candidate_id)
            return _mutation_payload(candidate_id, ReviewAction.ACCEPT, result)
        case "qualify":
            result = service.accept(
                candidate_id,
                action=ReviewAction.ACCEPT_WITH_QUALIFICATION,
                qualification=qualify,
            )
            return _mutation_payload(candidate_id, ReviewAction.ACCEPT_WITH_QUALIFICATION, result)
        case "edit":
            result = service.accept(
                candidate_id,
                action=ReviewAction.EDIT,
                edited=_edited_evidence(edit),
            )
            return _mutation_payload(candidate_id, ReviewAction.EDIT, result)
        case "reject":
            result = service.reject(candidate_id, reject or "")
            return _mutation_payload(candidate_id, ReviewAction.REJECT, result)
        case "request_more":
            result = service.request_more_evidence(candidate_id, request_more or "")
            return _mutation_payload(candidate_id, ReviewAction.REQUEST_MORE_EVIDENCE, result)
        case _:
            candidate = service.defer(candidate_id, defer or "")
            return {
                "candidate_id": candidate_id,
                "action": ReviewAction.DEFER.value,
                "evidence": None,
                "status": candidate.status.value,
                "mutation": None,
            }


def _split_payload(
    service: EvidenceReviewService,
    candidate_id: str,
    interpretation: str | None,
    reject_interpretation: str | None,
) -> dict[str, Any]:
    """Partial acceptance through the same capability the other transports call."""
    from research_harness.capabilities.extra_handlers import (
        SplitCandidateRequest,
        review_split,
    )

    outcome = review_split(
        service.ctx,
        SplitCandidateRequest(
            candidate_id=candidate_id,
            interpretation=interpretation,
            reject_interpretation_reason=reject_interpretation,
        ),
    )
    return outcome.model_dump(mode="json")


def _edited_evidence(path: Path | None) -> Evidence:
    if path is None:  # pragma: no cover - guarded by _one_action
        raise ResearchHarnessError("--edit needs a JSON file holding the corrected Evidence")
    try:
        return Evidence.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ResearchHarnessError(f"cannot read edited evidence {path}: {exc}") from exc


def _filtered(queue: ReviewQueue, category: str | None) -> tuple[ReviewItem, ...]:
    if category is None:
        return queue.items
    try:
        wanted = ReviewCategory(category)
    except ValueError as exc:
        known = ", ".join(item.value for item in ReviewCategory)
        raise ResearchHarnessError(f"unknown category {category!r}; known: {known}") from exc
    return queue.by_category(wanted)


# -- payloads ----------------------------------------------------------------


def _mutation_payload(candidate_id: str, action: ReviewAction, result: Any) -> dict[str, Any]:
    objects = list(result.objects)
    return {
        "candidate_id": candidate_id,
        "action": action.value,
        "evidence": objects[0] if objects and objects[0].startswith("E") else None,
        "objects": objects,
        "mutation": result.as_dict(),
    }


def _interrogate_payload(report: InterrogationReport) -> dict[str, Any]:
    return {
        "run": report.run.run_id,
        "status": report.run.status.value,
        "candidates": [
            {"candidate_id": candidate.candidate_id, "field": candidate.field}
            for candidate in report.candidates
        ],
        "by_field": {
            name: [item.candidate_id for item in items]
            for name, items in report.candidates_by_field.items()
        },
        "fields_not_found": list(report.fields_not_found),
        "rejected": [{"field": item.field, "reason": item.reason} for item in report.rejected],
    }


def _interrogate_lines(report: InterrogationReport) -> list[str]:
    lines = [
        f"run {report.run.run_id}: staged {len(report.candidates)} candidate(s) "
        f"across {len(report.candidates_by_field)} field(s)"
    ]
    for name, items in report.candidates_by_field.items():
        for candidate in items:
            text = candidate.evidence.content.exact_text.replace("\n", " ")
            lines.append(f"  {candidate.candidate_id}  {name:<18} {_clip(text, 60)}")
    lines += [f"  not found          {name}" for name in report.fields_not_found]
    lines += [f"  rejected           {item.field}: {item.reason}" for item in report.rejected]
    return lines


def _verify_payload(report: VerificationReport) -> dict[str, Any]:
    return {
        "run": report.run.run_id,
        "status": report.run.status.value,
        "verdicts": {cid: verdict.value for cid, verdict in report.verdicts.items()},
        "skipped": list(report.skipped),
    }


def _verify_lines(report: VerificationReport) -> list[str]:
    lines = [f"run {report.run.run_id}: verified {len(report.verdicts)} candidate(s)"]
    lines += [
        f"  {candidate_id}  {verdict.value}" for candidate_id, verdict in report.verdicts.items()
    ]
    lines += [
        f"  skipped            {candidate_id} (already verified)" for candidate_id in report.skipped
    ]
    return lines


def _inbox_lines(
    items: Sequence[ReviewItem],
    shown: Sequence[ReviewItem],
    counts: Mapping[ReviewCategory, int],
) -> list[str]:
    """The queue header says how many of how many are on screen (dogfood F8)."""
    tally = ", ".join(f"{name.value} {count}" for name, count in counts.items() if count)
    total = len(items)
    head = (
        f"{total} item(s) to review"
        if len(shown) == total
        else f"showing {len(shown)} of {total} item(s) — use --limit 0 for all"
    )
    lines = [head + (f"  [{tally}]" if tally else "")]
    if not items:
        lines.append("  nothing waiting; run `research interrogate <work>` to propose candidates")
        return lines
    for item in shown:
        lines.extend(_item_lines(item))
    if len(shown) < total:
        lines.append(f"  ... {total - len(shown)} more; --limit 0 shows the whole queue")
    return lines


def _detail_lines(item: ReviewItem) -> list[str]:
    """One review item in full: the decision, why it is here, and the span it rests on.

    Everything Product §25 asks to be on one screen — the candidate value, the source
    context, and the competing interpretations — so a rejection can be honest without
    opening the JSON in another window (dogfood F12).
    """
    context = item.source_context
    text = item.candidate.evidence.content.exact_text.replace("\n", " ")
    lines = [
        f"{item.candidate_id}  {item.category.value}  tier {int(item.tier)}  "
        f"{item.candidate.field}",
        f"  work               {item.work}  ({item.candidate.artifact})",
        f"  verdict            {item.verdict or 'unverified'}",
        f"  anchor             {item.anchor_status.value}",
        f"  evidence type      {item.candidate.evidence.evidence_type.value}",
    ]
    numeric = item.candidate.evidence.content.numeric
    if numeric is not None:
        lines.append(f"  measured           {_numeric_line(numeric)}")
    if item.candidate.evidence.content.negative_state is not None:
        lines.append(f"  absence            {item.candidate.evidence.content.negative_state.value}")
    lines += [f"  reason             {reason}" for reason in item.reasons]
    lines += [
        f"  discrepancy        {detail}"
        for detail in (
            item.candidate.verification.discrepancies if item.candidate.verification else ()
        )
    ]
    if item.candidate.verification is not None and item.candidate.verification.rationale:
        lines.append(f"  verifier said      {_clip(item.candidate.verification.rationale, 88)}")
    if item.previously_rejected:
        lines.append("  note               a candidate at this span was rejected before")
    if item.accepted_conflict is not None:
        lines.append(f"  conflicts with     accepted {item.accepted_conflict}")
    lines += [f"  competing          {other}" for other in item.competing]
    if item.provider_conflict is not None:
        lines += [
            f"  provider           {position.label}: {position.decision}"
            for position in item.provider_conflict.positions
        ]
    lines += [
        "",
        f"  quoted             {_clip(text, 88)}",
        f"  at                 page {context.page}"
        + (f", {' > '.join(context.section_path)}" if context.section_path else ""),
    ]
    if context.block_text:
        lines.append(f"  in block           {_clip(context.block_text.replace(chr(10), ' '), 88)}")
    lines += [
        f"  nearby             {_clip(neighbor.replace(chr(10), ' '), 88)}"
        for neighbor in context.neighbors
    ]
    return lines


def _numeric_line(numeric: NumericValue) -> str:
    """A measured value with the four things Product §12 says it never travels without."""
    parts = [
        f"{numeric.raw}",
        *(str(part) for part in (numeric.unit, numeric.metric, numeric.dataset) if part),
    ]
    return ", ".join(parts)


def _item_lines(item: ReviewItem) -> list[str]:
    text = item.candidate.evidence.content.exact_text.replace("\n", " ")
    lines = [
        f"  {item.candidate_id}  {item.category.value:<10} tier {int(item.tier)}  "
        f"{item.candidate.field}  {item.verdict or 'unverified'}",
        f"      {_clip(text, 88)}",
    ]
    lines += [f"      - {reason}" for reason in item.reasons]
    return lines


def _conflict_lines(items: Sequence[ReviewItem]) -> list[str]:
    if not items:
        return ["no conflicts"]
    lines = [f"{len(items)} conflict(s)"]
    for item in items:
        lines.extend(_item_lines(item))
        if item.provider_conflict is not None:
            lines += [
                f"      {position.label}: {position.decision}"
                for position in item.provider_conflict.positions
            ]
    return lines


def _stale_lines(items: Sequence[ReviewItem], marked: Sequence[Mapping[str, Any]]) -> list[str]:
    if not items and not marked:
        return ["nothing stale"]
    lines = [f"{len(items)} stale candidate(s), {len(marked)} stale accepted object(s)"]
    for item in items:
        lines.extend(_item_lines(item))
    lines += [f"  {row['id']}  {row['work']}  {row['field'] or '-'}" for row in marked]
    return lines


def _batch_lines(result: BatchResult) -> list[str]:
    verb = "would accept" if result.dry_run else "accepted"
    lines = [f"{verb} {len(result.accepted)}, skipped {len(result.skipped)}"]
    lines += [f"  accept   {candidate_id}" for candidate_id in result.accepted]
    lines += [
        f"  skip     {candidate_id}: {reason}"
        for candidate_id, reason in sorted(result.skipped.items())
    ]
    return lines


def _review_lines(payload: Mapping[str, Any]) -> list[str]:
    evidence = payload.get("evidence")
    head = f"{payload['candidate_id']}: {payload['action']}"
    lines = [f"{head} -> {evidence}" if evidence else head]
    staged = payload.get("interpretation_candidate")
    if staged:
        lines.append(f"  interpretation     staged as {staged}")
    elif payload.get("rejected"):
        lines.append("  interpretation     rejected and recorded")
    mutation = payload.get("mutation")
    if isinstance(mutation, Mapping):
        lines.append(f"  event              {mutation['event']['event']}")
        lines += [f"  warning            {text}" for text in mutation["validation"]["warnings"]]
        lines += [f"  stale              {mark['object_id']}" for mark in mutation["stale"]]
    return lines


def _session_lines(summary: SessionSummary) -> list[str]:
    return [
        "session summary",
        f"  added              {summary.added} staged candidate(s)",
        f"  unreviewed         {summary.unreviewed}",
        f"  conflicts          {summary.conflicts}",
        f"  stale              {summary.stale}",
        f"  accepted evidence  {summary.accepted}",
        f"  rejected           {summary.rejected}",
        f"  claims changed     {summary.claims_changed}",
        f"  open questions     {summary.open_questions}",
        f"  notes              {summary.notes}",
    ]


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else f"{text[: width - 1]}…"
