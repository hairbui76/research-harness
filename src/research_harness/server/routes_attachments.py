"""The three attachment routes: byte intake, original bytes, and page previews.

`POST /sessions/{session_id}/attachments` is **the one documented write that is not a
capability call** (v1.1 plan SS0.4). Everything else the daemon writes goes through
`POST /capabilities/{name}`, and that rule is what makes the review gate impossible to
route around (ADR-004). The exception is deliberate and narrow:

* it writes **session-only** state — bytes into `conversations/<session>/attachments/` —
  and can create no Work, Version, Artifact, Evidence, or Claim;
* it writes it through `AttachmentService.add`, the same service `attachment.add` calls,
  so there is one intake path with one set of validation rules rather than two;
* it is authorised exactly as `attachment.add` is (`mutate`, researcher only), so an agent
  host cannot upload bytes here that it could not upload there.

The alternative was to base64 a 30 MB PDF through a JSON capability request, which buys
nothing: the same bytes reach the same service either way, and the capability layer still
owns every mutation of *accepted* state.

The two reads are byte-faithful and deliberately inert: the original bytes are served with
the recorded media type narrowed to the attachment allowlist (never `text/html`, never an
SVG) under `nosniff` and a `default-src 'none'` policy, and a preview is a PNG the harness
rendered itself. Nothing a file contains is ever executed (attachments design SS8).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Query, Request
from starlette.responses import FileResponse

from research_harness.capabilities.attachments import AttachmentView, attachment_service
from research_harness.capabilities.context import open_context
from research_harness.capabilities.permissions import Permission, Principal
from research_harness.conversation.attachments import (
    AttachmentError,
    AttachmentService,
    PreviewUnavailableError,
)
from research_harness.domain.conversation import SessionAttachment
from research_harness.domain.errors import DomainValidationError, ResearchHarnessError
from research_harness.domain.ids import ConversationSessionId, SessionAttachmentId
from research_harness.protocol.dto import error_body
from research_harness.providers.models.media import SUPPORTED_MEDIA_TYPES, normalize_media_type
from research_harness.workspace.conversations import ConversationNotFoundError

if TYPE_CHECKING:  # pragma: no cover - `server/app.py` imports this module, not the reverse
    from fastapi import FastAPI

__all__ = ["MAX_UPLOAD_BYTES", "register_attachment_routes"]

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
"""Hard ceiling on one upload, refused before the body is read into memory. The per-class
limits that decide whether an attachment becomes *ready* live in `AttachmentLimits`; this
is only the daemon's guard against an unbounded request body."""

#: Sent with every byte response. The daemon serves research files a model or a colleague
#: handed the researcher, so the browser is told not to sniff a type and not to fetch,
#: frame, or script anything on their behalf.
_INERT_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Referrer-Policy": "no-referrer",
}

_FALLBACK_MEDIA_TYPE = "application/octet-stream"

FilenameQuery = Annotated[
    str | None,
    Query(description="Display name for the attachment. Metadata only; never a path."),
]
DescriptionQuery = Annotated[
    str | None,
    Query(description="Researcher-supplied description or alt text, kept apart from reading."),
]
PageQuery = Annotated[int, Query(ge=1, description="1-based page of the preview to render.")]


def _caller(request: Request) -> Principal:
    """Who is calling, resolved exactly as every other daemon route resolves it."""
    resolve: Callable[[str | None], Principal] = request.app.state.principal_resolver
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    return resolve(token.strip() if scheme.lower() == "bearer" and token.strip() else None)


Caller = Annotated[Principal, Depends(_caller)]


def register_attachment_routes(app: FastAPI, root: Path) -> None:
    """Add the attachment intake and byte reads to ``app``.

    Called once from `create_app`, before the built web bundle is mounted at `/`.
    """

    @app.post("/sessions/{session_id}/attachments", response_model=AttachmentView)
    async def add_attachment_bytes(
        session_id: str,
        request: Request,
        caller: Caller,
        filename: FilenameQuery = None,
        description: DescriptionQuery = None,
    ) -> AttachmentView:
        """Attach a file to a session. The one non-capability write, and session-only.

        The body is the raw file, `Content-Type` is its media type, and `?filename=` is
        display metadata: only its basename is kept and it never selects a path. The bytes
        become a `selected -> validating -> ready` attachment (or a `failed` one carrying
        the reason), and no corpus object is created — `attachment.save_to_corpus` is the
        only thing that does that.
        """
        # Authorised exactly as `attachment.add`: a byte route must not be a way around a
        # capability's permission (Product 22, 29).
        _authorize(caller, "attachment.add", Permission.MUTATE, human_only=True)
        session = _session_id(session_id)
        data = await _read_body(request)
        ctx = open_context(root, caller.actor)
        service = attachment_service(ctx)
        try:
            attachment = service.add(
                session,
                filename=filename or _FALLBACK_NAME,
                media_type=request.headers.get("content-type"),
                data=data,
                provenance=ctx.provenance(workflow="attachment"),
                description=description,
            )
        except ConversationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AttachmentError as exc:  # pragma: no cover - intake refuses in-band
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return AttachmentView.of(attachment)

    @app.get("/sessions/{session_id}/attachments/{attachment_id}/bytes")
    def attachment_bytes(session_id: str, attachment_id: str, caller: Caller) -> FileResponse:
        """The attachment's original bytes, inline, exactly as they were stored.

        Read-only and byte-identical: an attachment's bytes are immutable once stored, so
        there is no route that rewrites them.
        """
        _authorize(caller, f"attachment.bytes:{attachment_id}", Permission.READ)
        service, attachment = _lookup(root, caller.actor, session_id, attachment_id)
        path = service.store.attachment_bytes_path(attachment)
        if not path.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"attachment {attachment.id} has no stored bytes at {path}",
            )
        return FileResponse(
            path,
            media_type=_safe_media_type(attachment.media_type),
            filename=attachment.filename,
            content_disposition_type="inline",
            headers=dict(_INERT_HEADERS),
        )

    @app.get("/sessions/{session_id}/attachments/{attachment_id}/preview")
    def attachment_preview(
        session_id: str, attachment_id: str, caller: Caller, page: PageQuery = 1
    ) -> FileResponse:
        """A PNG projection of one page: a thumbnail for an image, a render for a PDF.

        The file lives under `.research/cache/attachments/` and is rendered on demand, so
        deleting the cache costs a re-render and never an attachment (Product 8.2).
        """
        _authorize(caller, f"attachment.preview:{attachment_id}", Permission.READ)
        service, attachment = _lookup(root, caller.actor, session_id, attachment_id)
        try:
            rendered = service.preview(attachment, page=page)
        except PreviewUnavailableError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConversationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(
            rendered,
            media_type="image/png",
            filename=f"{attachment.id}-page-{page}.png",
            content_disposition_type="inline",
            headers=dict(_INERT_HEADERS),
        )


_FALLBACK_NAME = "attachment"


def _authorize(
    caller: Principal, capability: str, permission: Permission, *, human_only: bool = False
) -> None:
    """Refuse a caller the same way the capability layer would, with the same body.

    A route that raised the refusal as an unhandled error would answer 500 where
    `POST /capabilities/attachment.add` answers 403, and two transports that disagree about
    a refusal is exactly what ADR-009 forbids.
    """
    try:
        caller.authorize(capability, permission, human_only=human_only)
    except ResearchHarnessError as exc:
        body = error_body(exc, capability=capability)
        raise HTTPException(status_code=body.status, detail=body.model_dump(mode="json")) from exc


async def _read_body(request: Request) -> bytes:
    """The whole request body, refused if it claims or turns out to be too large."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"attachment upload exceeds the {MAX_UPLOAD_BYTES}-byte limit",
        )
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="the request body carried no bytes")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"attachment upload exceeds the {MAX_UPLOAD_BYTES}-byte limit",
        )
    return data


def _lookup(
    root: Path, actor: str, session_id: str, attachment_id: str
) -> tuple[AttachmentService, SessionAttachment]:
    """The service and the attachment record, or a 404 naming what was not found."""
    session = _session_id(session_id)
    try:
        attachment = SessionAttachmentId(attachment_id)
    except DomainValidationError as exc:
        raise HTTPException(
            status_code=404, detail=f"{attachment_id} is not a session attachment id"
        ) from exc
    service = attachment_service(open_context(root, actor))
    try:
        return service, service.get(session, attachment)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _session_id(session_id: str) -> ConversationSessionId:
    try:
        return ConversationSessionId(session_id)
    except DomainValidationError as exc:
        raise HTTPException(
            status_code=404, detail=f"{session_id} is not a conversation session id"
        ) from exc


def _safe_media_type(media_type: str) -> str:
    """The recorded media type, narrowed to the allowlist.

    Anything the intake would not accept is served as an opaque download rather than as
    itself: a byte route must never hand a browser something it will render as a document
    or execute as a script (attachments design SS8).
    """
    normalized = normalize_media_type(media_type)
    if normalized in SUPPORTED_MEDIA_TYPES:
        return normalized
    return _FALLBACK_MEDIA_TYPE
