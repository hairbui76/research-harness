"""Session attachments: intake, validation, previews, and the pre-send compatibility check.

An attachment is working material, never corpus state (attachments design SS3). This module
owns the whole of that life before a promotion: the bytes are copied into the session under
an `SA####` identity, validated per item, previewed through disposable projections, and
checked against the selected model and the project's egress policy before anything is sent.
`conversation/promotion_corpus.py` owns what happens if the researcher then says
`Save to corpus`.

Three rules shape the code more than anything else:

* **One bad file never costs a good one.** `add` returns a `failed` attachment instead of
  raising, so a batch drop of five files where one is corrupt yields four ready
  attachments and one visible failure with a reason (attachments design SS2, SS9.3).
* **Nothing is silently dropped.** `sendability` is a total function over the composer's
  attachments: every one of them comes back as `sent`, `converted`, or `omitted` with a
  reason, and any *ready* attachment that cannot go makes the whole send refuse
  (attachments design SS5). The caller writes those lines into the `Context used` receipt
  with `receipt_items`, so what the researcher reads is what the check decided.
* **A filename is display metadata, not a path.** Intake keeps the basename for the
  researcher's eyes and takes the media type from the bytes wherever the bytes can say
  (attachments design SS8).

Previews live under `.research/cache/attachments/` and are regenerated on demand: deleting
the cache costs a re-render and never an attachment.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

import pymupdf

# Every `# type: ignore[no-untyped-call]` below has one cause: PyMuPDF ships `py.typed` but
# annotates almost nothing, so `--strict` counts each of its calls as untyped.
from research_harness.domain.base import Provenance
from research_harness.domain.conversation import (
    STORED_ATTACHMENT_STATES,
    AttachmentState,
    AuthorityLabel,
    ContextClass,
    ContextItem,
    OmissionReason,
    OmittedContextItem,
    SessionAttachment,
    Visibility,
    transition_attachment,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import ConversationSessionId, SessionAttachmentId
from research_harness.ingest.hashing import sha256_bytes
from research_harness.privacy.policy import EgressPolicy, check_egress, is_local_endpoint
from research_harness.providers.models.base import InputEnvelope, ProviderCapabilities
from research_harness.providers.models.media import (
    SUPPORTED_MEDIA_TYPES,
    MediaClass,
    MediaPart,
    accepts_media,
    media_class,
    normalize_media_type,
)
from research_harness.workspace.conversations import ConversationStore

__all__ = [
    "DEFAULT_LIMITS",
    "AttachmentCheck",
    "AttachmentError",
    "AttachmentLimits",
    "AttachmentService",
    "PreviewUnavailableError",
    "SendCheck",
    "SendDisposition",
    "attachment_link",
    "display_filename",
    "receipt_items",
    "sendability",
]

logger = logging.getLogger(__name__)

_KIB = 1024
_MIB = 1024 * _KIB

#: Magic numbers for every binary type the intake accepts. Text has none, which is why a
#: text attachment is the only one whose declared media type is taken on trust.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
)

_FILENAME_TYPES: Mapping[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
}

_FALLBACK_FILENAME = "attachment"
_UNKNOWN_MEDIA_TYPE = "application/octet-stream"


class AttachmentError(CapabilityError):
    """An attachment operation was asked for something it cannot do."""


class PreviewUnavailableError(AttachmentError):
    """This attachment has no image preview, or its bytes could not be rendered."""


class SendDisposition(StrEnum):
    """What happens to one attachment on a send, in the words the receipt uses."""

    SENT = "sent"
    """The bytes travel with the request as a media part."""
    CONVERTED = "converted"
    """The file is inlined as text because the model takes no media of that kind."""
    OMITTED = "omitted"
    """It does not travel. A *ready* attachment omitted this way blocks the send."""


@dataclass(frozen=True, slots=True)
class AttachmentLimits:
    """Ceilings the workstation applies to attachments, in one editable place.

    They are deliberately generous and deliberately explicit: the point is that a refusal
    names a number the researcher can read, not that the number is the only defensible one.
    """

    max_image_bytes: int = 20 * _MIB
    max_document_bytes: int = 32 * _MIB
    max_text_bytes: int = 2 * _MIB
    max_image_pixels: int = 50_000_000
    max_pdf_pages: int = 500
    """Intake ceiling: above this a PDF is a corpus object, not a chat attachment."""
    max_sent_pdf_pages: int = 100
    """Per-request ceiling; a longer PDF is saved to the corpus and retrieved by anchor."""
    max_sent_items: int = 20
    preview_dpi: int = 96
    thumbnail_max_edge: int = 512


DEFAULT_LIMITS = AttachmentLimits()


@dataclass(frozen=True, slots=True)
class AttachmentCheck:
    """What would happen to one attachment on a send, and why.

    `ok` answers "does this item let the send proceed", which is not the same as "does it
    travel": a `failed` attachment is omitted and still `ok`, because it was never ready;
    a *ready* attachment that the model cannot take is omitted and **not** ok, because
    dropping it silently is the failure the product forbids (attachments design SS5).
    """

    attachment: SessionAttachmentId
    filename: str
    media_type: str
    size_bytes: int
    state: AttachmentState
    disposition: SendDisposition
    ok: bool
    reason: str | None = None
    omission: OmissionReason | None = None
    suggested_model: str | None = None
    page_count: int | None = None

    @property
    def travels(self) -> bool:
        """True when this item reaches the model, as media or as inlined text."""
        return self.disposition is not SendDisposition.OMITTED


@dataclass(frozen=True, slots=True)
class SendCheck:
    """The per-item verdict for one (session, model) pair."""

    provider: str
    model: str
    items: tuple[AttachmentCheck, ...] = ()

    @property
    def ok(self) -> bool:
        """True when nothing blocks the send."""
        return all(item.ok for item in self.items)

    @property
    def blocked(self) -> tuple[AttachmentCheck, ...]:
        """Ready attachments that cannot be sent to this model, in order."""
        return tuple(item for item in self.items if not item.ok)

    @property
    def travelling(self) -> tuple[AttachmentCheck, ...]:
        """Items that reach the model, sent or converted."""
        return tuple(item for item in self.items if item.travels)

    def refusal(self) -> str | None:
        """One line naming every blocked item, or `None` when the send may proceed."""
        blocked = self.blocked
        if not blocked:
            return None
        listed = "; ".join(f"{item.attachment} {item.filename}: {item.reason}" for item in blocked)
        return (
            f"{len(blocked)} attachment(s) cannot be sent to {self.provider}/{self.model}: {listed}"
        )


def attachment_link(attachment: SessionAttachmentId) -> str:
    """The `rh://` deep link that identifies one attachment in a receipt."""
    return f"rh://attachment/{attachment}"


# -- the pre-send check ------------------------------------------------------


def sendability(
    attachments: Sequence[SessionAttachment],
    *,
    provider: str,
    model: str,
    capabilities: ProviderCapabilities,
    policy: EgressPolicy | None = None,
    alternatives: Sequence[tuple[str, ProviderCapabilities]] = (),
    limits: AttachmentLimits = DEFAULT_LIMITS,
) -> SendCheck:
    """Decide, per attachment, whether it may go to this model — and if not, why not.

    Pure: it reads the attachment *records* and the provider's declared capabilities, and
    performs no I/O, so `session.send` can call it before assembling anything and refuse
    without having touched a byte (ADR-018 decides egress at selection, not in an adapter).

    ``alternatives`` are other configured `(label, capabilities)` pairs; the first one that
    could take a refused attachment is named as `suggested_model`, which is what turns
    "this cannot be sent" into an action.
    """
    refusal = _provider_refusal(policy, capabilities)
    external = not is_local_endpoint(capabilities.egress.endpoint_host)
    items: list[AttachmentCheck] = []
    travelling = 0
    for attachment in attachments:
        check = _check_one(
            attachment,
            capabilities=capabilities,
            provider_refusal=refusal,
            external=external,
            policy=policy,
            alternatives=alternatives,
            limits=limits,
        )
        if check.travels:
            travelling += 1
            if travelling > limits.max_sent_items:
                check = replace(
                    check,
                    disposition=SendDisposition.OMITTED,
                    ok=False,
                    omission=OmissionReason.TOKEN_BUDGET,
                    reason=(
                        f"one request carries at most {limits.max_sent_items} attachments; "
                        "send the rest in a follow-up message"
                    ),
                )
        items.append(check)
    return SendCheck(provider=provider, model=model, items=tuple(items))


def _check_one(
    attachment: SessionAttachment,
    *,
    capabilities: ProviderCapabilities,
    provider_refusal: str | None,
    external: bool,
    policy: EgressPolicy | None,
    alternatives: Sequence[tuple[str, ProviderCapabilities]],
    limits: AttachmentLimits,
) -> AttachmentCheck:
    """The verdict for one attachment; the rules are applied in the order they matter."""
    base = AttachmentCheck(
        attachment=attachment.id,
        filename=attachment.filename,
        media_type=attachment.media_type,
        size_bytes=attachment.size_bytes,
        state=attachment.state,
        page_count=attachment.page_count,
        disposition=SendDisposition.SENT,
        ok=True,
    )
    kind = media_class(attachment.media_type)

    if attachment.state not in {AttachmentState.READY, AttachmentState.SESSION_ONLY}:
        # Never ready, so nothing was promised about it and nothing is being dropped.
        return _omit(
            base,
            OmissionReason.UNSUPPORTED_MEDIA,
            attachment.failure_reason or f"the attachment is {attachment.state.value}, not ready",
            blocking=False,
        )
    if provider_refusal is not None:
        return _omit(
            base,
            OmissionReason.EGRESS_BLOCKED,
            provider_refusal,
            suggested=_suggest(attachment, alternatives, policy=policy),
        )
    if external and attachment.visibility is Visibility.PRIVATE:
        return _omit(
            base,
            OmissionReason.PRIVACY_POLICY,
            (
                f"{attachment.filename} is private and "
                f"{capabilities.egress.endpoint_host} is not on this workstation; mark the "
                "attachment or its session `project` visibility to allow it"
            ),
            suggested=_suggest(attachment, alternatives, policy=policy),
        )
    over = _over_size(attachment, kind, limits)
    if over is not None:
        return _omit(base, OmissionReason.UNSUPPORTED_MEDIA, over)
    if accepts_media(capabilities, attachment.media_type):
        if (
            kind is MediaClass.DOCUMENT
            and attachment.page_count is not None
            and attachment.page_count > limits.max_sent_pdf_pages
        ):
            return _omit(
                base,
                OmissionReason.UNSUPPORTED_MEDIA,
                (
                    f"{attachment.page_count} pages exceeds the {limits.max_sent_pdf_pages}-page "
                    "send limit; save it to the corpus and cite the pages you need"
                ),
            )
        return base
    if kind is MediaClass.TEXT:
        # Local conversion: text needs no vision, so it is inlined rather than refused.
        return replace(base, disposition=SendDisposition.CONVERTED)
    return _omit(
        base,
        OmissionReason.UNSUPPORTED_MEDIA,
        f"the selected model does not accept {attachment.media_type} input",
        suggested=_suggest(attachment, alternatives, policy=policy),
    )


def _omit(
    base: AttachmentCheck,
    reason: OmissionReason,
    detail: str,
    *,
    suggested: str | None = None,
    blocking: bool = True,
) -> AttachmentCheck:
    return replace(
        base,
        disposition=SendDisposition.OMITTED,
        ok=not blocking,
        omission=reason,
        reason=detail,
        suggested_model=suggested,
    )


def _over_size(
    attachment: SessionAttachment, kind: MediaClass, limits: AttachmentLimits
) -> str | None:
    """The size refusal for this attachment, or `None` when it fits."""
    ceiling = {
        MediaClass.IMAGE: limits.max_image_bytes,
        MediaClass.DOCUMENT: limits.max_document_bytes,
        MediaClass.TEXT: limits.max_text_bytes,
    }.get(kind)
    if ceiling is None or attachment.size_bytes <= ceiling:
        return None
    return (
        f"{attachment.size_bytes} bytes exceeds the {ceiling}-byte limit for "
        f"{kind.value} attachments"
    )


def _provider_refusal(
    policy: EgressPolicy | None, capabilities: ProviderCapabilities
) -> str | None:
    """The project's egress refusal for this provider, or `None` when it may be called."""
    if policy is None:
        return None
    verdict = check_egress(policy, capabilities.egress, kind="model")
    return None if verdict.allowed else verdict.reason


def _suggest(
    attachment: SessionAttachment,
    alternatives: Sequence[tuple[str, ProviderCapabilities]],
    *,
    policy: EgressPolicy | None,
) -> str | None:
    """The first configured model that could take this attachment, or `None`."""
    for label, capabilities in alternatives:
        if not accepts_media(capabilities, attachment.media_type):
            continue
        if _provider_refusal(policy, capabilities) is not None:
            continue
        if attachment.visibility is Visibility.PRIVATE and not is_local_endpoint(
            capabilities.egress.endpoint_host
        ):
            continue
        return label
    return None


# -- the `Context used` lines ------------------------------------------------

#: Characters of text per token, for the one estimate this module makes. Only *converted*
#: text has a text cost at all; image and PDF cost is provider-specific and is reported as
#: the file's size rather than invented as a token count.
CHARS_PER_TOKEN = 4


def receipt_items(
    check: SendCheck,
) -> tuple[tuple[ContextItem, ...], tuple[OmittedContextItem, ...]]:
    """The `Context used` attachment lines: what was sent, converted, and omitted.

    Returned as the two halves of a `ContextReceipt` so the caller can merge them with the
    rest of the pack (`ContextItem` for what travelled, `OmittedContextItem` for what did
    not, each carrying the reason the check recorded).
    """
    included: list[ContextItem] = []
    omitted: list[OmittedContextItem] = []
    for item in check.items:
        source = attachment_link(item.attachment)
        label = _receipt_label(item)
        if item.travels:
            included.append(
                ContextItem(
                    context_class=ContextClass.ATTACHMENTS,
                    source=source,
                    id=item.attachment,
                    authority=AuthorityLabel.PRIVATE,
                    label=label,
                    tokens=(
                        item.size_bytes // CHARS_PER_TOKEN
                        if item.disposition is SendDisposition.CONVERTED
                        else 0
                    ),
                )
            )
            continue
        omitted.append(
            OmittedContextItem(
                context_class=ContextClass.ATTACHMENTS,
                source=source,
                id=item.attachment,
                authority=AuthorityLabel.PRIVATE,
                label=label,
                tokens=0,
                reason=item.omission or OmissionReason.UNSUPPORTED_MEDIA,
                detail=_receipt_detail(item),
            )
        )
    return tuple(included), tuple(omitted)


def _receipt_label(item: AttachmentCheck) -> str:
    pages = f", {item.page_count} pages" if item.page_count else ""
    return (
        f"{item.filename} ({item.media_type}, {item.size_bytes} bytes{pages}) "
        f"— {item.disposition.value}"
    )


def _receipt_detail(item: AttachmentCheck) -> str | None:
    if item.reason is None:
        return None
    if item.suggested_model is None:
        return item.reason
    return f"{item.reason}; {item.suggested_model} would accept it"


# -- the service -------------------------------------------------------------


class AttachmentService:
    """Intake, removal, previews, and media inputs for one workspace's sessions."""

    def __init__(
        self, store: ConversationStore, *, limits: AttachmentLimits = DEFAULT_LIMITS
    ) -> None:
        self._store = store
        self._limits = limits

    @property
    def store(self) -> ConversationStore:
        return self._store

    @property
    def limits(self) -> AttachmentLimits:
        return self._limits

    # -- intake --------------------------------------------------------------

    def add(
        self,
        session: ConversationSessionId,
        *,
        filename: str,
        media_type: str | None,
        data: bytes,
        provenance: Provenance,
        description: str | None = None,
        visibility: Visibility | None = None,
    ) -> SessionAttachment:
        """Copy ``data`` into the session and validate it; never raises for a bad file.

        The bytes land durably with the `SA####` identity before validation runs, which is
        what makes a failure *visible*: the researcher sees the item, its name, and the
        reason it did not become ready, instead of a file that vanished (design SS2).
        """
        display = display_filename(filename)
        effective = _effective_media_type(data, media_type, display)
        session_record = self._store.get_session(session)
        chosen = visibility if visibility is not None else session_record.visibility

        def build(attachment_id: SessionAttachmentId) -> SessionAttachment:
            return SessionAttachment(
                id=attachment_id,
                session=session,
                state=AttachmentState.SELECTED,
                filename=display,
                media_type=effective,
                size_bytes=len(data),
                description=description,
                visibility=chosen,
                provenance=provenance,
            )

        selected = self._store.add_attachment(session, build, data=data)
        validating = self._store.put_attachment(
            transition_attachment(selected, AttachmentState.VALIDATING)
        )
        try:
            page_count = self._validate(effective, data)
        except AttachmentError as exc:
            logger.info("attachment %s failed validation: %s", validating.id, exc)
            return self._store.put_attachment(
                transition_attachment(validating, AttachmentState.FAILED, failure_reason=str(exc))
            )
        return self._store.put_attachment(
            transition_attachment(
                validating,
                AttachmentState.READY,
                content_hash=sha256_bytes(data),
                size_bytes=len(data),
                page_count=page_count,
            )
        )

    def add_file(
        self,
        session: ConversationSessionId,
        path: Path | str,
        *,
        provenance: Provenance,
        media_type: str | None = None,
        description: str | None = None,
        visibility: Visibility | None = None,
    ) -> SessionAttachment:
        """`add` for a local file, reading it once."""
        source = Path(path)
        try:
            data = source.read_bytes()
        except OSError as exc:
            raise AttachmentError(f"attachment.add: cannot read {source}: {exc}") from exc
        return self.add(
            session,
            filename=source.name,
            media_type=media_type,
            data=data,
            provenance=provenance,
            description=description,
            visibility=visibility,
        )

    def retry(self, attachment: SessionAttachment) -> SessionAttachment:
        """Validate a `failed` attachment again; the session copy was never deleted."""
        if attachment.state is not AttachmentState.FAILED:
            raise AttachmentError(
                f"attachment.retry: {attachment.id} is {attachment.state.value}, not failed"
            )
        data = self._store.read_attachment_bytes(attachment)
        validating = self._store.put_attachment(
            transition_attachment(attachment, AttachmentState.VALIDATING)
        )
        try:
            page_count = self._validate(attachment.media_type, data)
        except AttachmentError as exc:
            return self._store.put_attachment(
                transition_attachment(validating, AttachmentState.FAILED, failure_reason=str(exc))
            )
        return self._store.put_attachment(
            transition_attachment(
                validating,
                AttachmentState.READY,
                content_hash=sha256_bytes(data),
                size_bytes=len(data),
                page_count=page_count,
            )
        )

    # -- reads ---------------------------------------------------------------

    def get(
        self, session: ConversationSessionId, attachment: SessionAttachmentId
    ) -> SessionAttachment:
        """One attachment record, or `ConversationNotFoundError`."""
        return self._store.get_attachment(session, attachment)

    def list_attachments(self, session: ConversationSessionId) -> list[SessionAttachment]:
        """Every attachment of a session, in id order, whatever its state."""
        return self._store.list_attachments(session)

    def sendable(self, session: ConversationSessionId) -> list[SessionAttachment]:
        """The attachments a send would consider: the ready ones."""
        return [
            attachment
            for attachment in self.list_attachments(session)
            if attachment.state in {AttachmentState.READY, AttachmentState.SESSION_ONLY}
        ]

    # -- removal -------------------------------------------------------------

    def remove(self, attachment: SessionAttachment) -> None:
        """Delete one attachment: its record, its bytes, and its previews.

        Refused when a message or a context receipt names it. `SA####` numbers are handed
        out by scanning the attachment files, so deleting the newest record would let the
        next intake reuse its id — and a transcript line or a `Context used` receipt that
        still said `SA0003` would then point at a different file. A researcher who wants
        that history gone deletes the session, which is a separate explicit retention
        operation (attachments design SS8).
        """
        referenced = self._references(attachment.id)
        if referenced:
            listed = ", ".join(referenced)
            raise AttachmentError(
                f"attachment.remove: {attachment.id} is named by {listed}; removing it would "
                "leave the transcript pointing at a file that no longer exists. Delete the "
                "session instead."
            )
        self.discard_previews(attachment.id)
        self._store.attachment_bytes_path(attachment).unlink(missing_ok=True)
        self._store.layout.session_attachment_file(attachment.session, attachment.id).unlink(
            missing_ok=True
        )
        logger.info("removed attachment %s from session %s", attachment.id, attachment.session)

    def _references(self, attachment: SessionAttachmentId) -> list[str]:
        """Everything durable that names this attachment: messages, then receipts."""
        found: list[str] = []
        link = attachment_link(attachment)
        for session in self._store.list_sessions():
            found.extend(
                str(message.id)
                for message in self._store.iter_messages(session.id)
                if attachment in message.attachments
            )
            for pack_id in self._store.list_context_packs(session.id):
                pack = self._store.read_context_pack(session.id, pack_id)
                receipt = pack.receipt
                if any(item.source == link for item in (*receipt.included, *receipt.omitted)):
                    found.append(str(pack_id))
        return found

    # -- previews ------------------------------------------------------------

    def preview(self, attachment: SessionAttachment, *, page: int = 1) -> Path:
        """The PNG projection of one attachment page, rendering it if the cache is cold.

        Everything here lives under `.research/cache/`: deleting it costs a re-render and
        can never cost an attachment (Product 8.2).
        """
        if attachment.state not in STORED_ATTACHMENT_STATES:
            raise PreviewUnavailableError(
                f"{attachment.id} is {attachment.state.value}; only a stored attachment "
                "has a preview"
            )
        target = self._preview_path(attachment, page)
        if target.is_file():
            return target
        data = self._store.read_attachment_bytes(attachment)
        png = self._render(attachment, data, page)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(png)
        temporary.replace(target)
        return target

    def preview_pages(self, attachment: SessionAttachment) -> int:
        """How many previewable pages this attachment has; an image has one."""
        if media_class(attachment.media_type) is MediaClass.DOCUMENT:
            return attachment.page_count or 1
        return 1

    def discard_previews(self, attachment: SessionAttachmentId) -> None:
        """Delete this attachment's cached previews; they regenerate on the next read."""
        directory = self._store.layout.attachment_preview_dir(attachment)
        if not directory.is_dir():
            return
        for path in directory.iterdir():
            path.unlink(missing_ok=True)
        directory.rmdir()

    def _preview_path(self, attachment: SessionAttachment, page: int) -> Path:
        directory = self._store.layout.attachment_preview_dir(attachment.id)
        kind = media_class(attachment.media_type)
        if kind is MediaClass.IMAGE:
            if page != 1:
                raise PreviewUnavailableError(
                    f"{attachment.id} is an image and has only page 1, not {page}"
                )
            return directory / "thumbnail.png"
        if kind is MediaClass.DOCUMENT:
            pages = attachment.page_count or 1
            if page < 1 or page > pages:
                raise PreviewUnavailableError(
                    f"{attachment.id} has {pages} page(s); page {page} does not exist"
                )
            return directory / f"page-{page:04d}.png"
        raise PreviewUnavailableError(
            f"{attachment.id} is {attachment.media_type}; read its bytes instead of a preview"
        )

    def _render(self, attachment: SessionAttachment, data: bytes, page: int) -> bytes:
        """Render one preview. Never executes anything the file contains (design SS8)."""
        if media_class(attachment.media_type) is MediaClass.DOCUMENT:
            with _pdf(data, attachment.filename) as document:
                rendered = document[page - 1].get_pixmap(dpi=self._limits.preview_dpi)
                return bytes(rendered.tobytes("png"))
        try:
            pixmap = pymupdf.Pixmap(data)  # type: ignore[no-untyped-call]
        except Exception as exc:  # PyMuPDF raises plain exceptions for undecodable images
            raise PreviewUnavailableError(
                f"{attachment.filename}: this build cannot decode {attachment.media_type} "
                f"for a thumbnail ({exc})"
            ) from exc
        if pixmap.colorspace is not None and pixmap.colorspace.n == 4:
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)  # type: ignore[no-untyped-call]
        while max(pixmap.width, pixmap.height) > self._limits.thumbnail_max_edge:
            pixmap.shrink(1)  # type: ignore[no-untyped-call]
        return bytes(pixmap.tobytes("png"))  # type: ignore[no-untyped-call]

    # -- model inputs --------------------------------------------------------

    def media_part(self, attachment: SessionAttachment) -> MediaPart:
        """This attachment as a provider-neutral `MediaPart`, bytes included."""
        data = self._store.read_attachment_bytes(attachment)
        return MediaPart(
            media_type=attachment.media_type,
            data=data,
            filename=attachment.filename,
            size_bytes=len(data),
            page_count=attachment.page_count,
        )

    def inputs(self, session: ConversationSessionId, check: SendCheck) -> list[InputEnvelope]:
        """The `InputEnvelope`s for everything ``check`` says may travel.

        A `sent` item carries its bytes as a `MediaPart`; a `converted` one carries its
        text in `content` and no media at all, which is what "the model takes no media of
        that kind, so we inlined it" means in the request itself.
        """
        envelopes: list[InputEnvelope] = []
        for item in check.travelling:
            attachment = self.get(session, item.attachment)
            part = self.media_part(attachment)
            if item.disposition is SendDisposition.CONVERTED:
                envelopes.append(
                    InputEnvelope(
                        object_id=str(attachment.id),
                        kind="attachment_text",
                        content=(f"{attachment.filename} ({attachment.media_type})\n{part.text()}"),
                    )
                )
                continue
            envelopes.append(
                InputEnvelope(
                    object_id=str(attachment.id),
                    kind="attachment",
                    content=_media_description(attachment),
                    media=part,
                )
            )
        return envelopes

    # -- validation ----------------------------------------------------------

    def _validate(self, media_type: str, data: bytes) -> int | None:
        """Check one file and return its page count; raises `AttachmentError` if unusable."""
        if not data:
            raise AttachmentError("the file is empty")
        if media_type not in SUPPORTED_MEDIA_TYPES:
            supported = ", ".join(sorted(SUPPORTED_MEDIA_TYPES))
            raise AttachmentError(
                f"{media_type or 'unknown media type'} is not a supported attachment type "
                f"(supported: {supported})"
            )
        kind = media_class(media_type)
        limit = {
            MediaClass.IMAGE: self._limits.max_image_bytes,
            MediaClass.DOCUMENT: self._limits.max_document_bytes,
            MediaClass.TEXT: self._limits.max_text_bytes,
        }[kind]
        if len(data) > limit:
            raise AttachmentError(
                f"{len(data)} bytes exceeds the {limit}-byte limit for {kind.value} attachments"
            )
        if kind is MediaClass.TEXT:
            _validate_text(media_type, data)
            return None
        if kind is MediaClass.DOCUMENT:
            return self._validate_pdf(data)
        self._validate_image(media_type, data)
        return None

    def _validate_pdf(self, data: bytes) -> int:
        with _pdf(data, "the attachment") as document:
            if document.needs_pass:
                raise AttachmentError(
                    "the PDF is password protected; decrypt it before attaching it"
                )
            pages = int(document.page_count)
        if pages < 1:
            raise AttachmentError("the PDF has no pages")
        if pages > self._limits.max_pdf_pages:
            raise AttachmentError(
                f"{pages} pages exceeds the {self._limits.max_pdf_pages}-page attachment "
                "limit; save it to the corpus instead"
            )
        return pages

    def _validate_image(self, media_type: str, data: bytes) -> None:
        """Confirm the bytes really are the image they claim, and bound their size."""
        if _sniff(data) is None:
            raise AttachmentError(
                f"the bytes are not a readable {media_type} image "
                "(the file may be truncated or misnamed)"
            )
        try:
            pixmap = pymupdf.Pixmap(data)  # type: ignore[no-untyped-call]
        except Exception:
            # A recognised container this build cannot decode (WebP, typically). The file
            # is what it says it is; only the local thumbnail is unavailable.
            logger.debug("no local decoder for %s; skipping the dimension check", media_type)
            return
        if pixmap.width * pixmap.height > self._limits.max_image_pixels:
            raise AttachmentError(
                f"{pixmap.width}x{pixmap.height} exceeds the "
                f"{self._limits.max_image_pixels}-pixel limit"
            )


# -- module helpers ----------------------------------------------------------


def display_filename(filename: str) -> str:
    """The basename of ``filename``, for display only.

    Directory separators of both flavours are stripped and `..` is refused: an attachment's
    name is metadata a remote client chose, and it must never be able to steer a path
    (attachments design SS8).
    """
    candidate = filename.replace("\\", "/").strip()
    name = PurePosixPath(candidate).name.strip()
    if not name or name in {".", ".."}:
        return _FALLBACK_FILENAME
    return name


def _effective_media_type(data: bytes, declared: str | None, filename: str) -> str:
    """What this file actually is: its magic bytes, else what was declared, else its name."""
    sniffed = _sniff(data)
    if sniffed is not None:
        return sniffed
    normalized = normalize_media_type(declared)
    if normalized and normalized != _UNKNOWN_MEDIA_TYPE:
        return normalized
    suffix = PurePosixPath(filename).suffix.lower()
    # Never empty: an unknown type has to be *named* so the failure can explain itself
    # rather than being refused by the schema before the researcher ever sees the item.
    return _FILENAME_TYPES.get(suffix) or normalized or _UNKNOWN_MEDIA_TYPE


def _sniff(data: bytes) -> str | None:
    """The media type the bytes themselves declare, or `None` for a format without magic."""
    for magic, media_type in _MAGIC:
        if data.startswith(magic):
            return media_type
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _validate_text(media_type: str, data: bytes) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AttachmentError(
            f"declared {media_type} but the bytes are not valid UTF-8 text ({exc.reason})"
        ) from exc
    if media_type == "application/json":
        try:
            json.loads(text)
        except ValueError as exc:
            raise AttachmentError(
                f"declared application/json but it does not parse: {exc}"
            ) from exc


def _media_description(attachment: SessionAttachment) -> str:
    """The text that travels beside an attachment's bytes, naming what the model is seeing."""
    parts = [f"{attachment.filename} ({attachment.media_type}, {attachment.size_bytes} bytes)"]
    if attachment.page_count:
        parts.append(f"{attachment.page_count} page(s)")
    if attachment.description:
        parts.append(attachment.description)
    return " — ".join(parts)


class _PdfContext:
    """`with` wrapper turning PyMuPDF's own exceptions into `AttachmentError`."""

    def __init__(self, data: bytes, label: str) -> None:
        self._data = data
        self._label = label
        self._document: Any = None

    def __enter__(self) -> Any:
        try:
            self._document = pymupdf.open(  # type: ignore[no-untyped-call]
                stream=self._data, filetype="pdf"
            )
        except Exception as exc:  # PyMuPDF reports every corruption as a plain exception
            raise AttachmentError(f"{self._label} is not a readable PDF ({exc})") from exc
        return self._document

    def __exit__(self, *exc_info: object) -> None:
        if self._document is not None:
            self._document.close()


def _pdf(data: bytes, label: str) -> _PdfContext:
    """Open PDF bytes for reading, closing the document however the block ends."""
    return _PdfContext(data, label)
