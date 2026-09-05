"""`research chat`: open, continue, inspect, and promote out of a conversation.

A transport and nothing more (ADR-004). Every command here calls the same
`session.*` / `context.*` capability an HTTP or MCP client calls, so a conversation started
on the CLI is the session the Web workspace reopens, with the same ids and the same
receipts.

The family is `chat` rather than `session` because `research session` already exists and
means something else: the end-of-working-session summary of Product 39. Two commands cannot
own one word, and the older one is the one people have typed.

Two commands are worth reading twice:

* `research chat send` starts the durable run and then *waits* for it, because a person at
  a terminal wants the answer. The run is the same one `GET /runs/{id}/events` streams;
  waiting is a convenience of this transport, not a second code path.
* `research chat context` prints the `Context used` receipt without sending anything — the
  fastest way to answer "what would this model see?" before it sees it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from research_harness.capabilities.context import CapabilityContext
from research_harness.cli.context import JsonOption, WorkspaceOption, cli_errors, context_for, emit
from research_harness.conversation.binding import binding_of, binding_words
from research_harness.conversation.context import ContextBudget
from research_harness.conversation.promote import ClaimProposal, PromotionService
from research_harness.conversation.send import ScriptedProviders, SendOutcome
from research_harness.conversation.service import ConversationService
from research_harness.domain.conversation import (
    ContextPack,
    ConversationSession,
    PromotionRequest,
    PromotionTarget,
    Visibility,
)
from research_harness.domain.enums import ClaimScope, ClaimType, DecisionType
from research_harness.domain.errors import ResearchHarnessError
from research_harness.domain.ids import ContextPackId, ConversationSessionId, MessageId

__all__ = ["register"]

session_app = typer.Typer(
    name="chat",
    help="Research conversations: durable, private working context (Product 39).",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Add the `research chat ...` family to ``app``.

    Not `session`: `research session` is the working-session summary this workspace has had
    since v1.0, and a new group by that name would shadow it everywhere, including inside
    `research shell`.
    """
    app.add_typer(session_app, name="chat")


# -- options -----------------------------------------------------------------

SessionArgument = Annotated[str, typer.Argument(help="Session id, e.g. CS0001.")]
ProviderOption = Annotated[
    str | None,
    typer.Option("--provider", help="Provider entry from `providers:` in research.yaml."),
]
CHAT_SCRIPT_SHAPE = (
    'a chat script is a JSON list of replies, each an object with a "text" string — or one '
    'such object for a single answer, e.g. [{"text": "..."}]. The role-keyed form the '
    'workflow commands take (`{"writer": [...]}`) does not apply here: a conversation '
    "turn is answered by the routing role `conversation`, which is not a workflow role"
)
"""What `--script` expects, stated once so the option help and the refusal agree.

A chat turn's reply schema is `ChatReply` — one `text` field — because a conversation is
prose rather than a structured research object. A file in any other shape used to reach
the provider and fail there, as a validation error about a schema the researcher never
named; it is refused here instead, by the transport that knows what was asked for.
"""

ScriptOption = Annotated[
    Path | None,
    typer.Option(
        "--script",
        help=(
            'JSON replies for the in-process scripted provider, e.g. [{"text": "..."}]; '
            "runs fully offline."
        ),
        show_default=False,
    ),
]
ChunkOption = Annotated[
    int,
    typer.Option("--chunk-words", help="Words per delta when the scripted provider streams."),
]
ReferenceOption = Annotated[
    list[str] | None,
    typer.Option("--ref", help="Stable reference to send, e.g. E0482; repeatable."),
]
BudgetOption = Annotated[
    int | None, typer.Option("--budget", help="Token budget for the assembled context.")
]


# -- sessions ----------------------------------------------------------------


@session_app.command("new")
def session_new(
    title: Annotated[str, typer.Argument(help="What this conversation is about.")],
    workspace: WorkspaceOption = None,
    visibility: Annotated[
        Visibility,
        typer.Option(
            "--visibility",
            help=(
                "project (the default) lets the selected external provider see the "
                "transcript; private keeps the conversation on this machine, so only a "
                "local provider may answer it. Decided once: nothing changes it after."
            ),
        ),
    ] = Visibility.PROJECT,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            help=(
                "Bind the new session to this entry name from research.yaml "
                "(see `research chat configure`)."
            ),
        ),
    ] = None,
    budget: BudgetOption = None,
    as_json: JsonOption = False,
) -> None:
    """Open a session (`session.create`)."""
    with cli_errors():
        service = _service(workspace)
        session = service.create(title, visibility=visibility, model=model, token_budget=budget)
        emit(
            {"session": session.model_dump(mode="json")},
            [f"{session.id}  {session.visibility.value}  {session.title}"],
            as_json=as_json,
        )


@session_app.command("list")
def session_list(workspace: WorkspaceOption = None, as_json: JsonOption = False) -> None:
    """Every session in this project (`session.list`)."""
    with cli_errors():
        sessions = _service(workspace).sessions()
        emit(
            {"sessions": [item.model_dump(mode="json") for item in sessions]},
            [_session_row(item) for item in sessions] or ["no sessions yet"],
            as_json=as_json,
        )


@session_app.command("show")
def session_show(
    session: SessionArgument,
    workspace: WorkspaceOption = None,
    offset: Annotated[int, typer.Option("--offset", help="First message to print.")] = 0,
    limit: Annotated[int, typer.Option("--limit", help="How many messages to print.")] = 50,
    as_json: JsonOption = False,
) -> None:
    """Reopen a session with its transcript intact (`session.get`)."""
    with cli_errors():
        page = _service(workspace).transcript(
            ConversationSessionId(session), offset=offset, limit=limit
        )
        lines = [
            f"{page.session.id}  {page.session.title}",
            f"bound to: {binding_words(page.session.defaults)}",
            "",
        ]
        for message in page.messages:
            flag = " (incomplete)" if message.incomplete else ""
            lines.append(f"{message.id}  {message.role.value}{flag}")
            lines.append(_indent(message.text()))
            if message.context_pack is not None:
                lines.append(f"    context: {message.context_pack}")
            lines.append("")
        if page.next_offset is not None:
            lines.append(f"…{page.total - page.next_offset} more; --offset {page.next_offset}")
        emit(
            {
                "session": page.session.model_dump(mode="json"),
                "messages": [item.model_dump(mode="json") for item in page.messages],
                "total": page.total,
                "next_offset": page.next_offset,
            },
            lines,
            as_json=as_json,
        )


@session_app.command("rename")
def session_rename(
    session: SessionArgument,
    title: Annotated[str, typer.Argument(help="The new title.")],
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Retitle a session (`session.rename`)."""
    with cli_errors():
        record = _service(workspace).rename(ConversationSessionId(session), title)
        emit(
            {"session": record.model_dump(mode="json")},
            [f"{record.id}  {record.title}"],
            as_json=as_json,
        )


@session_app.command("configure")
def session_configure(
    session: SessionArgument,
    workspace: WorkspaceOption = None,
    runtime: Annotated[
        str | None,
        typer.Option("--runtime", help="Runtime id from `research providers scan`."),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model id from the scan, or `default`."),
    ] = None,
    reasoning: Annotated[
        str | None,
        typer.Option("--reasoning", help="The runtime's own effort name."),
    ] = None,
    entry: Annotated[
        str | None,
        typer.Option("--entry", help="An entry name in research.yaml."),
    ] = None,
    clear: Annotated[
        bool,
        typer.Option("--clear", help="Return the session to the project default."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Bind a session to a runtime and model, or an entry, or clear it (`session.configure`).

    Nothing is written to research.yaml: the binding lives on the session
    record, and every gate a configured entry passes still applies when the
    session next sends. The egress line comes first because a binding decides
    where this conversation will go.
    """
    from research_harness.cli.commands.provider import egress_sentence
    from research_harness.providers.cli.registry import RUNTIMES

    with cli_errors():
        # An id no registry knows is refused below, in the daemon's own words; the sentence
        # is printed only for a runtime there is a destination to name.
        if runtime is not None and runtime in RUNTIMES and not as_json:
            typer.echo(egress_sentence(runtime, subject=f"session {session}"))
        record = _service(workspace).configure(
            ConversationSessionId(session),
            runtime=runtime,
            model=model,
            reasoning=reasoning,
            entry=entry,
            clear=clear,
        )
        emit(
            {"session": record.model_dump(mode="json")},
            [f"bound to: {binding_words(record.defaults)}"],
            as_json=as_json,
        )


@session_app.command("search")
def session_search(
    query: Annotated[str, typer.Argument(help="Text to look for in titles and messages.")],
    workspace: WorkspaceOption = None,
    limit: Annotated[int, typer.Option("--limit", help="Maximum sessions to report.")] = 20,
    as_json: JsonOption = False,
) -> None:
    """Search titles and transcripts (`session.search`). Works with `.research/` deleted."""
    with cli_errors():
        matches = _service(workspace).search(query, limit=limit)
        emit(
            {
                "matches": [
                    {
                        "session": str(match.session),
                        "title": match.title,
                        "title_matched": match.title_matched,
                        "messages": [str(item) for item in match.messages],
                        "snippet": match.snippet,
                    }
                    for match in matches
                ]
            },
            [f"{match.session}  {match.title}  {match.snippet or ''}".rstrip() for match in matches]
            or ["no matches"],
            as_json=as_json,
        )


@session_app.command("summarize")
def session_summarize(
    session: SessionArgument, workspace: WorkspaceOption = None, as_json: JsonOption = False
) -> None:
    """Regenerate the derived summary (`session.summarize`). No model call."""
    with cli_errors():
        summary = _service(workspace).summarize(ConversationSessionId(session))
        emit({"summary": summary}, [summary], as_json=as_json)


# -- context -----------------------------------------------------------------


@session_app.command("context")
def session_context(
    session: SessionArgument,
    workspace: WorkspaceOption = None,
    pack_id: Annotated[
        str | None,
        typer.Option(
            "--pack",
            help="Read a receipt already recorded, e.g. CP0001, instead of assembling one.",
            show_default=False,
        ),
    ] = None,
    text: Annotated[str, typer.Option("--text", help="The draft to assemble context for.")] = "",
    reference: ReferenceOption = None,
    provider: ProviderOption = None,
    budget: BudgetOption = None,
    persist: Annotated[
        bool, typer.Option("--persist/--no-persist", help="Record the pack under the session.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Show what a message would send, or what one did (`context.preview`, `context.get`).

    Without `--pack` this assembles a receipt for a draft and sends nothing. With `--pack`
    it reads the receipt a past message already named, which is the durable record of what
    that call was shown.
    """
    with cli_errors():
        service = _service(workspace)
        session_id = ConversationSessionId(session)
        if pack_id is not None:
            if text or reference or provider or budget is not None:
                raise ResearchHarnessError(
                    "--pack reads a recorded receipt; it takes no draft, reference, "
                    "provider, or budget"
                )
            pack = service.read_pack(session_id, ContextPackId(pack_id))
        else:
            pack, _ = service.preview(
                session_id,
                text,
                tuple(reference or ()),
                model=provider,
                budget=None if budget is None else ContextBudget(total=budget),
                persist=persist,
            )
        emit(_receipt_payload(pack), _receipt_lines(pack), as_json=as_json)


# -- sending -----------------------------------------------------------------


@session_app.command("send")
def session_send(
    session: SessionArgument,
    text: Annotated[str, typer.Argument(help="The message to send.")],
    workspace: WorkspaceOption = None,
    reference: ReferenceOption = None,
    provider: ProviderOption = None,
    script: ScriptOption = None,
    chunk_words: ChunkOption = 8,
    budget: BudgetOption = None,
    as_json: JsonOption = False,
) -> None:
    """Send a message and print the answer (`session.send`).

    The run is durable: the same answer is readable afterwards with `session show`, and a
    client watching `GET /runs/{id}/events` sees exactly these deltas.
    """
    with cli_errors():
        ctx = context_for(workspace)
        service = _service_for(ctx, script, chunk_words)
        started = service.send(
            ConversationSessionId(session),
            text,
            references=tuple(reference or ()),
            model=provider,
            budget=None if budget is None else ContextBudget(total=budget),
        )
        service.wait(started.run_id)
        outcome = service.outcome(started.run_id)
        emit(
            _outcome_payload(outcome, started.unresolved), _outcome_lines(outcome), as_json=as_json
        )


@session_app.command("stop")
def session_stop(
    run_id: Annotated[str, typer.Argument(help="The run to stop.")],
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Stop a streaming answer (`session.stop`). What arrived is kept as incomplete."""
    with cli_errors():
        state = _service(workspace).stop(run_id)
        emit({"run_id": run_id, "state": state}, [f"{run_id}  {state}"], as_json=as_json)


@session_app.command("retry")
def session_retry(
    message: Annotated[str, typer.Argument(help="The failed model message, e.g. M0042.")],
    workspace: WorkspaceOption = None,
    provider: ProviderOption = None,
    script: ScriptOption = None,
    chunk_words: ChunkOption = 8,
    as_json: JsonOption = False,
) -> None:
    """Answer again as a new attempt (`session.retry`); the failed one is kept."""
    with cli_errors():
        ctx = context_for(workspace)
        service = _service_for(ctx, script, chunk_words)
        started = service.retry(MessageId(message), model=provider)
        service.wait(started.run_id)
        outcome = service.outcome(started.run_id)
        emit(
            _outcome_payload(outcome, started.unresolved), _outcome_lines(outcome), as_json=as_json
        )


# -- promotion ---------------------------------------------------------------


@session_app.command("promote")
def session_promote(
    message: Annotated[str, typer.Argument(help="The message to promote from, e.g. M0042.")],
    target: Annotated[
        str,
        typer.Argument(help="note | question | claim_candidate | decision_candidate."),
    ],
    workspace: WorkspaceOption = None,
    session: Annotated[
        str | None, typer.Option("--session", help="Session the message belongs to.")
    ] = None,
    excerpt: Annotated[
        str | None, typer.Option("--excerpt", help="Text to promote; defaults to the message.")
    ] = None,
    rationale: Annotated[str | None, typer.Option("--rationale", help="Why.")] = None,
    subject: Annotated[str, typer.Option("--subject", help="Claim proposition subject.")] = "",
    predicate: Annotated[str, typer.Option("--predicate", help="Claim predicate.")] = "",
    obj: Annotated[str, typer.Option("--object", help="Claim object.")] = "",
    scope: Annotated[
        ClaimScope, typer.Option("--scope", help="Scope the claim is asserted at.")
    ] = ClaimScope.INDIVIDUAL,
    claim_type: Annotated[
        ClaimType, typer.Option("--type", help="Claim type.")
    ] = ClaimType.DESCRIPTIVE,
    decision_type: Annotated[
        DecisionType, typer.Option("--decision-type", help="Decision type for a candidate.")
    ] = DecisionType.OTHER,
    as_json: JsonOption = False,
) -> None:
    """Promote an excerpt into reviewable state (`session.promote`).

    Evidence is not a target: it needs an Artifact and an exact anchor, so asking for it
    here is refused with the route that does work.
    """
    with cli_errors():
        PromotionService.refuse_evidence(target)
        ctx = context_for(workspace)
        service = ConversationService(ctx)
        message_id = MessageId(message)
        session_id = (
            ConversationSessionId(session) if session is not None else _session_of(ctx, message_id)
        )
        text = excerpt or service.store.get_message(session_id, message_id).text()
        proposal = (
            ClaimProposal(
                subject=subject,
                predicate=predicate,
                object=obj,
                claim_type=claim_type,
                scope=scope,
            )
            if subject and predicate and obj
            else None
        )
        promotion = service.promote(
            PromotionRequest(
                session=session_id,
                message=message_id,
                target=PromotionTarget(target),
                excerpt=text,
                rationale=rationale,
                provenance=ctx.provenance(workflow="session.promote"),
            ),
            claim=proposal,
            decision_type=decision_type,
        )
        emit(
            {
                "target": promotion.target.value,
                "object_id": promotion.object_id,
                "note_key": promotion.note_key,
                "accepted": promotion.accepted,
                "review": promotion.review,
                "decision": (
                    None
                    if promotion.decision is None
                    else promotion.decision.model_dump(mode="json")
                ),
            },
            [
                f"{promotion.target.value}  {promotion.object_id or promotion.note_key or ''}",
                f"  {promotion.review}",
            ],
            as_json=as_json,
        )


# -- helpers -----------------------------------------------------------------


def _service(workspace: Path | None) -> ConversationService:
    return ConversationService(context_for(workspace))


def _session_row(item: ConversationSession) -> str:
    """One `chat list` row, with the binding in brackets when the session has one."""
    row = f"{item.id}  {item.message_count:>4} msg  {item.visibility.value:<7}  {item.title}"
    if binding_of(item.defaults) is None:
        return row
    return f"{row}  [{binding_words(item.defaults)}]"


def _service_for(
    ctx: CapabilityContext, script: Path | None, chunk_words: int
) -> ConversationService:
    """The service, with the scripted provider wired in when `--script` names one."""
    if script is None:
        return ConversationService(ctx)
    return ConversationService(
        ctx,
        providers=ScriptedProviders(_chat_script(script), chunk_words=max(chunk_words, 1)),
    )


def _chat_script(path: Path) -> Any:
    """The scripted answers for `research chat send|retry --script`, shape checked here.

    `cli/providers.py::scripted_model_provider` reads the three shapes the *workflow*
    commands take, one of which is keyed by role. A conversation turn cannot use it — its
    role is `conversation`, which the role registry does not know — so this reads the one
    shape a chat turn can use and says so when the file is not in it.
    """
    import json

    from research_harness.cli.providers import SCRIPTED_PROVIDER
    from research_harness.providers.models.scripted import ScriptedProvider

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchHarnessError(f"cannot read script {path}: {exc}") from exc
    replies = payload if isinstance(payload, list) else [payload]
    for reply in replies:
        if not isinstance(reply, dict) or not isinstance(reply.get("text"), str):
            raise ResearchHarnessError(f"{path}: {CHAT_SCRIPT_SHAPE}")
    return ScriptedProvider(list(replies), name=SCRIPTED_PROVIDER)


def _session_of(ctx: CapabilityContext, message: MessageId) -> ConversationSessionId:
    """Which session holds a message, when the caller did not say."""
    from research_harness.workspace.conversations import ConversationStore

    found = ConversationStore.for_repository(ctx.repo).find_message(message)
    if found is None:
        raise ResearchHarnessError(f"no message {message} in this workspace")
    return found.session


def _outcome_payload(outcome: SendOutcome, unresolved: tuple[str, ...]) -> dict[str, Any]:
    return {
        "run_id": outcome.run_id,
        "session": str(outcome.session),
        "message": str(outcome.assistant_message),
        "context_pack": str(outcome.context_pack),
        "attempt": outcome.attempt,
        "state": outcome.state,
        "text": outcome.text,
        "error": outcome.error,
        "unresolved": list(unresolved),
    }


def _outcome_lines(outcome: SendOutcome) -> list[str]:
    lines = [f"{outcome.assistant_message}  {outcome.state}  (context {outcome.context_pack})"]
    if outcome.text:
        lines.append(outcome.text)
    if outcome.error:
        lines.append(f"error: {outcome.error}")
    return lines


def _receipt_payload(pack: ContextPack) -> dict[str, Any]:
    """The receipt as JSON: the pack, plus the two lists a client groups by."""
    return {
        "pack": pack.model_dump(mode="json"),
        "discrepancies": [
            {"accepted": item.accepted, "message": item.message, "detail": item.detail}
            for item in pack.receipt.discrepancies
        ],
        "unresolved": list(pack.receipt.unresolved),
    }


def _receipt_lines(pack: ContextPack) -> list[str]:
    """The `Context used` receipt as a person reads it: what went, and what did not."""
    lines = [
        f"{pack.id}  {pack.egress.value}  {pack.receipt.total_tokens()} tokens of "
        f"{pack.token_budget}",
        "",
        "included:",
    ]
    lines.extend(
        f"  [{item.context_class.value}] {item.source}  {item.authority.value}  {item.tokens} tok"
        for item in pack.receipt.included
    )
    if pack.receipt.omitted:
        lines.extend(["", "omitted:"])
        lines.extend(
            f"  [{item.context_class.value}] {item.source}  {item.reason.value}"
            + (f"  — {item.detail}" if item.detail else "")
            for item in pack.receipt.omitted
        )
    if pack.receipt.unresolved:
        lines.extend(["", f"unresolved references: {', '.join(pack.receipt.unresolved)}"])
    if pack.receipt.discrepancies:
        lines.extend(["", "accepted state outranked:"])
        lines.extend(
            f"  {item.accepted} over {item.message} — {item.detail}"
            for item in pack.receipt.discrepancies
        )
    return lines


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(f"{prefix}{line}" for line in (text or "(no text)").splitlines())
