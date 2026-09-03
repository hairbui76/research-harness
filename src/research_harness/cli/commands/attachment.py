"""`research attachment`: attach files to a session, check them, and save them to the corpus.

Six subcommands over the five `attachment.*` capabilities plus one read of the session's
own records. Nothing here holds a rule of its own: the CLI is a transport (ADR-004), so a
refusal a researcher sees here is the same refusal the daemon and an MCP host produce.

The boundary the output keeps repeating is the point of the phase: `add` says
"session-only, no corpus object", and only `save` crosses -- explicitly, with the identity
it resolved printed before it does (attachments design SS3, SS6).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from research_harness.capabilities.attachments import (
    AddAttachmentRequest,
    AttachmentIdentityView,
    AttachmentPromotionView,
    AttachmentSendCheck,
    AttachmentView,
    CheckAttachmentSendRequest,
    RemoveAttachmentRequest,
    ResolveAttachmentIdentityRequest,
    SaveAttachmentToCorpusRequest,
    add_attachment,
    attachment_service,
    check_attachment_send,
    remove_attachment,
    resolve_attachment_identity,
    save_attachment_to_corpus,
)
from research_harness.cli.context import JsonOption, WorkspaceOption, cli_errors, context_for, emit
from research_harness.domain.conversation import SessionAttachment, Visibility
from research_harness.domain.ids import ConversationSessionId, SessionAttachmentId, WorkId

__all__ = ["register"]

attachment_app = typer.Typer(
    name="attachment",
    help="Attach files to a conversation session, check them, and save them to the corpus.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Add `research attachment ...` to ``app``."""
    app.add_typer(attachment_app, name="attachment")


SessionArgument = Annotated[str, typer.Argument(help="Conversation session (CS####).")]
AttachmentArgument = Annotated[str, typer.Argument(help="Session attachment (SA####).")]


@attachment_app.command("add")
def add(
    session: SessionArgument,
    file: Annotated[Path, typer.Argument(help="Local file to attach.")],
    workspace: WorkspaceOption = None,
    media_type: Annotated[
        str | None,
        typer.Option("--media-type", help="Override the media type; sniffed from the bytes."),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="Alt text or description, kept apart from reading."),
    ] = None,
    visibility: Annotated[
        str | None,
        typer.Option("--visibility", help="private|project; defaults to the session's."),
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Attach a file to a session as working material (`attachment.add`).

    Session-only: this creates no Work, Version, Artifact, or Evidence.
    """
    with cli_errors():
        ctx = context_for(workspace)
        view = add_attachment(
            ctx,
            AddAttachmentRequest(
                session=ConversationSessionId(session),
                path=file,
                media_type=media_type,
                description=description,
                visibility=None if visibility is None else Visibility(visibility),
            ),
        )
        emit(view.model_dump(mode="json"), _add_lines(view), as_json=as_json)


@attachment_app.command("list")
def list_attachments(
    session: SessionArgument, workspace: WorkspaceOption = None, as_json: JsonOption = False
) -> None:
    """List a session's attachments and their states."""
    with cli_errors():
        ctx = context_for(workspace)
        records = attachment_service(ctx).list_attachments(ConversationSessionId(session))
        payload: dict[str, Any] = {
            "session": session,
            "attachments": [AttachmentView.of(item).model_dump(mode="json") for item in records],
            "count": len(records),
        }
        emit(payload, _list_lines(records), as_json=as_json)


@attachment_app.command("remove")
def remove(
    session: SessionArgument,
    attachment: AttachmentArgument,
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Delete an attachment, its bytes, and its previews (`attachment.remove`)."""
    with cli_errors():
        ctx = context_for(workspace)
        result = remove_attachment(
            ctx,
            RemoveAttachmentRequest(
                session=ConversationSessionId(session),
                attachment=SessionAttachmentId(attachment),
            ),
        )
        emit(
            result.model_dump(mode="json"),
            [f"removed {result.attachment} from {result.session}"],
            as_json=as_json,
        )


@attachment_app.command("check")
def check(
    session: SessionArgument,
    workspace: WorkspaceOption = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="Configured provider name; the preferred one by default."),
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="Model served by that provider.")
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Check whether the attachments may go to the selected model (`attachment.check_send`)."""
    with cli_errors():
        ctx = context_for(workspace)
        result = check_attachment_send(
            ctx,
            CheckAttachmentSendRequest(
                session=ConversationSessionId(session), provider=provider, model=model
            ),
        )
        emit(result.model_dump(mode="json"), _check_lines(result), as_json=as_json)


@attachment_app.command("resolve")
def resolve(
    session: SessionArgument,
    attachment: AttachmentArgument,
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Show what an attachment would become in the corpus (`attachment.resolve_identity`)."""
    with cli_errors():
        ctx = context_for(workspace)
        result = resolve_attachment_identity(
            ctx,
            ResolveAttachmentIdentityRequest(
                session=ConversationSessionId(session),
                attachment=SessionAttachmentId(attachment),
            ),
        )
        emit(result.model_dump(mode="json"), _resolve_lines(result), as_json=as_json)


@attachment_app.command("save")
def save(
    session: SessionArgument,
    attachment: AttachmentArgument,
    workspace: WorkspaceOption = None,
    as_new: Annotated[
        bool,
        typer.Option("--as-new", help="Register a new Work even if the identity looks familiar."),
    ] = False,
    attach_to: Annotated[
        str | None, typer.Option("--attach-to", help="Save the file under this Work (W####).")
    ] = None,
    skip_parse: Annotated[
        bool, typer.Option("--no-parse", help="Register the file without parsing it.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Save an attachment into the corpus under a resolved identity (`attachment.save_to_corpus`).

    Creates or links Work/Version/Artifact identity and parses the file. It accepts no
    Evidence and no Claim: extraction still goes through the review gates.
    """
    with cli_errors():
        ctx = context_for(workspace)
        result = save_attachment_to_corpus(
            ctx,
            SaveAttachmentToCorpusRequest(
                session=ConversationSessionId(session),
                attachment=SessionAttachmentId(attachment),
                as_new=as_new,
                attach_to=WorkId(attach_to) if attach_to else None,
                parse=not skip_parse,
            ),
        )
        emit(result.model_dump(mode="json"), _save_lines(result), as_json=as_json)


# -- rendering ---------------------------------------------------------------


def _add_lines(view: AttachmentView) -> list[str]:
    lines = [
        f"{view.id}  {view.filename}  {view.media_type}  {view.size_bytes} bytes  [{view.state}]"
    ]
    if view.page_count:
        lines.append(f"  pages              {view.page_count}")
    if view.failure_reason:
        lines.append(f"  failed             {view.failure_reason}")
        lines.append("  the file is still listed; fix it and attach it again")
    else:
        lines.append(f"  content hash       {view.content_hash}")
    lines.append(f"  visibility         {view.visibility}")
    lines.append("session-only: no Work, Version, Artifact, or Evidence was created")
    return lines


def _list_lines(records: list[SessionAttachment]) -> list[str]:
    if not records:
        return ["no attachments in this session"]
    lines = [
        f"{item.id}  {item.state.value:<12}  {item.media_type:<24}  "
        f"{item.size_bytes:>9} B  {item.filename}"
        for item in records
    ]
    in_corpus = [item for item in records if item.artifact is not None]
    if in_corpus:
        lines.append("")
        lines.extend(f"{item.id} saved to the corpus as {item.artifact}" for item in in_corpus)
    return lines


def _check_lines(result: AttachmentSendCheck) -> list[str]:
    lines = [f"model  {result.provider}/{result.model}"]
    for item in result.items:
        mark = "ok " if item.ok else "BLOCKED"
        lines.append(f"{mark:<8}{item.attachment}  {item.disposition:<10}{item.filename}")
        if item.reason:
            lines.append(f"          {item.reason}")
        if item.suggested_model:
            lines.append(f"          try {item.suggested_model}")
    lines.append("")
    lines.append("send may proceed" if result.ok else str(result.refusal))
    return lines


def _resolve_lines(result: AttachmentIdentityView) -> list[str]:
    lines = [
        f"{result.attachment}  {result.choice}",
        f"  content hash       {result.content_hash}",
        f"  resolver outcome   {result.outcome}",
    ]
    for name, value in (
        ("work", result.work),
        ("version", result.version),
        ("artifact", result.artifact),
        ("title", result.title),
        ("doi", result.doi),
        ("arxiv", result.arxiv),
    ):
        if value:
            lines.append(f"  {name:<18} {value}")
    lines.extend(f"  reason             {reason}" for reason in result.reasons)
    if result.duplicate:
        lines.append("these exact bytes are already registered; saving links to them")
    if result.requires_confirmation:
        lines.append("identity is undecided: save with --as-new or --attach-to W####")
    return lines


def _save_lines(result: AttachmentPromotionView) -> list[str]:
    created = {
        "nothing": "linked the existing Artifact; nothing was copied",
        "artifact": "added an Artifact to an existing Version",
        "version": "added a Version and an Artifact to an existing Work",
        "work": "registered a new Work",
    }.get(result.created, result.created)
    return [
        f"{result.attachment.id}  ->  {result.work} / {result.version} / {result.artifact}",
        f"  outcome            {result.outcome} ({created})",
        f"  parsed             {'yes' if result.parsed else 'no'}",
        f"  attachment state   {result.attachment.state}",
        "no Evidence and no Claim were created: extraction still goes through review",
    ]
