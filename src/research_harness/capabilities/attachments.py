"""The `attachment.*` capabilities: intake, removal, the send check, and `Save to corpus`.

Five names, and the boundary between them is the product's boundary (attachments design
SS3, SS6):

* `attachment.add` and `attachment.remove` write **session-only** state. They copy bytes
  into `conversations/<session>/attachments/` and never touch the corpus, so attaching a
  file cannot create a Work, a Version, an Artifact, or a single line of Evidence.
* `attachment.check_send` and `attachment.resolve_identity` are reads. One answers "may
  this go to the selected model, and if not, what would take it"; the other answers "what
  would this become in the corpus". Neither writes anything, so the researcher can look
  before deciding.
* `attachment.save_to_corpus` is the one crossing, and it goes through the ordinary
  ingest/parse services, which go through `work.register` / `work.add_artifact`. It
  creates corpus *identity* and nothing scientific.

Like the rest of `capabilities/`, this module is a DTO translation over services that
already own the rules (ADR-004): `conversation/attachments.py` and
`conversation/promotion_corpus.py`.
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import CapabilityRequest
from research_harness.capabilities.permissions import Permission
from research_harness.capabilities.registry import CapabilitySpec, MutationResponse
from research_harness.conversation.attachments import (
    AttachmentCheck,
    AttachmentError,
    AttachmentService,
    SendCheck,
    sendability,
)
from research_harness.conversation.promotion_corpus import (
    AttachmentIdentity,
    AttachmentPromotion,
    AttachmentPromotionService,
)
from research_harness.domain.conversation import SessionAttachment, Visibility
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import ConversationSessionId, SessionAttachmentId, WorkId
from research_harness.providers.models.base import ProviderCapabilities
from research_harness.workspace.conversations import ConversationStore

__all__ = [
    "ATTACHMENT_CAPABILITIES",
    "ATTACHMENT_CAPABILITY_HANDLERS",
    "AddAttachmentRequest",
    "AttachmentIdentityView",
    "AttachmentPromotionView",
    "AttachmentRemoved",
    "AttachmentSendCheck",
    "AttachmentSendItem",
    "AttachmentView",
    "CheckAttachmentSendRequest",
    "RemoveAttachmentRequest",
    "ResolveAttachmentIdentityRequest",
    "SaveAttachmentToCorpusRequest",
    "add_attachment",
    "attachment_service",
    "attachment_specs",
    "check_attachment_send",
    "configured_models",
    "remove_attachment",
    "resolve_attachment_identity",
    "save_attachment_to_corpus",
]

#: Every capability this module registers, in the order the plan lists them (v1.1 SS0.4).
ATTACHMENT_CAPABILITIES: tuple[str, ...] = (
    "attachment.add",
    "attachment.remove",
    "attachment.check_send",
    "attachment.resolve_identity",
    "attachment.save_to_corpus",
)


class _Response(BaseModel):
    """Frozen, closed response envelope; every transport sees the same JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# -- requests ----------------------------------------------------------------


class AddAttachmentRequest(CapabilityRequest):
    """`attachment.add`: copy one file into a session as working material.

    The bytes come either from a local `path` (the CLI's way) or as `data_base64` (a host
    that has the file in hand). `filename` is display metadata: only its basename is kept
    and it never selects a path (attachments design SS8).
    """

    session: ConversationSessionId
    path: Path | None = None
    data_base64: str | None = None
    filename: str | None = None
    media_type: str | None = None
    description: str | None = None
    visibility: Visibility | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> AddAttachmentRequest:
        if (self.path is None) == (self.data_base64 is None):
            raise ValueError("give exactly one of `path` or `data_base64`")
        if self.data_base64 is not None and not self.filename:
            raise ValueError("`data_base64` needs a `filename` to display the attachment by")
        return self

    def bytes_and_name(self) -> tuple[bytes, str]:
        """The file's bytes and its display name, whichever way it was supplied."""
        if self.path is not None:
            try:
                return self.path.read_bytes(), self.filename or self.path.name
            except OSError as exc:
                raise AttachmentError(f"attachment.add: cannot read {self.path}: {exc}") from exc
        if self.data_base64 is None or not self.filename:  # pragma: no cover - validated above
            raise AttachmentError("attachment.add: no bytes and no filename to attach")
        try:
            return base64.b64decode(self.data_base64, validate=True), self.filename
        except (binascii.Error, ValueError) as exc:
            raise AttachmentError(
                f"attachment.add: `data_base64` is not valid base64: {exc}"
            ) from exc


class RemoveAttachmentRequest(CapabilityRequest):
    """`attachment.remove`: delete one session attachment, its bytes, and its previews."""

    session: ConversationSessionId
    attachment: SessionAttachmentId


class CheckAttachmentSendRequest(CapabilityRequest):
    """`attachment.check_send`: may this session's attachments go to the selected model?"""

    session: ConversationSessionId
    provider: str | None = None
    """Configured provider name or tag; the highest-priority entry when omitted."""
    model: str | None = None
    attachments: tuple[SessionAttachmentId, ...] = ()
    """Narrow the check to these attachments; empty means every attachment in the session."""


class ResolveAttachmentIdentityRequest(CapabilityRequest):
    """`attachment.resolve_identity`: what this attachment would become in the corpus."""

    session: ConversationSessionId
    attachment: SessionAttachmentId


class SaveAttachmentToCorpusRequest(CapabilityRequest):
    """`attachment.save_to_corpus`: the explicit promotion, with the researcher's answer.

    `as_new` and `attach_to` are that answer for an identity the resolver could not decide;
    a request that supplies neither is refused rather than guessed (Product 13).
    """

    session: ConversationSessionId
    attachment: SessionAttachmentId
    as_new: bool = False
    attach_to: WorkId | None = None
    parse: bool = True

    @model_validator(mode="after")
    def _one_answer(self) -> SaveAttachmentToCorpusRequest:
        if self.as_new and self.attach_to is not None:
            raise ValueError("`as_new` registers a new Work and `attach_to` uses an existing one")
        return self


# -- responses ---------------------------------------------------------------


class AttachmentView(_Response):
    """One session attachment as every transport sees it."""

    id: str
    session: str
    state: str
    filename: str
    media_type: str
    size_bytes: int
    content_hash: str | None = None
    page_count: int | None = None
    description: str | None = None
    visibility: str = Visibility.PRIVATE.value
    failure_reason: str | None = None
    work: str | None = None
    version: str | None = None
    artifact: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def of(cls, attachment: SessionAttachment) -> AttachmentView:
        """Render one record; the bytes are read through the byte route, never inlined."""
        return cls(
            id=str(attachment.id),
            session=str(attachment.session),
            state=attachment.state.value,
            filename=attachment.filename,
            media_type=attachment.media_type,
            size_bytes=attachment.size_bytes,
            content_hash=attachment.content_hash,
            page_count=attachment.page_count,
            description=attachment.description,
            visibility=attachment.visibility.value,
            failure_reason=attachment.failure_reason,
            work=None if attachment.work is None else str(attachment.work),
            version=None if attachment.version is None else str(attachment.version),
            artifact=None if attachment.artifact is None else str(attachment.artifact),
            created_at=attachment.created_at.isoformat(),
            updated_at=attachment.updated_at.isoformat(),
        )


class AttachmentRemoved(_Response):
    """`attachment.remove`: what was deleted."""

    session: str
    attachment: str
    removed: bool = True


class AttachmentSendItem(_Response):
    """One attachment's verdict for one model."""

    attachment: str
    filename: str
    media_type: str
    size_bytes: int
    state: str
    disposition: str
    ok: bool
    reason: str | None = None
    omission: str | None = None
    suggested_model: str | None = None
    page_count: int | None = None

    @classmethod
    def of(cls, check: AttachmentCheck) -> AttachmentSendItem:
        return cls(
            attachment=str(check.attachment),
            filename=check.filename,
            media_type=check.media_type,
            size_bytes=check.size_bytes,
            state=check.state.value,
            disposition=check.disposition.value,
            ok=check.ok,
            reason=check.reason,
            omission=None if check.omission is None else check.omission.value,
            suggested_model=check.suggested_model,
            page_count=check.page_count,
        )


class AttachmentSendCheck(_Response):
    """`attachment.check_send`: the per-item verdict, and whether the send may proceed."""

    session: str
    provider: str
    model: str
    ok: bool
    refusal: str | None = None
    items: tuple[AttachmentSendItem, ...] = ()

    @classmethod
    def of(cls, session: ConversationSessionId, check: SendCheck) -> AttachmentSendCheck:
        return cls(
            session=str(session),
            provider=check.provider,
            model=check.model,
            ok=check.ok,
            refusal=check.refusal(),
            items=tuple(AttachmentSendItem.of(item) for item in check.items),
        )


class AttachmentIdentityView(_Response):
    """`attachment.resolve_identity`: the corpus identity a save would use."""

    attachment: str
    choice: str
    outcome: str
    content_hash: str
    requires_confirmation: bool
    duplicate: bool
    parsable: bool
    reasons: tuple[str, ...] = ()
    work: str | None = None
    version: str | None = None
    artifact: str | None = None
    title: str | None = None
    doi: str | None = None
    arxiv: str | None = None
    year: int | None = None

    @classmethod
    def of(cls, identity: AttachmentIdentity) -> AttachmentIdentityView:
        return cls(
            attachment=str(identity.attachment.id),
            choice=identity.choice.value,
            outcome=identity.outcome.value,
            content_hash=identity.content_hash,
            requires_confirmation=identity.requires_confirmation,
            duplicate=identity.duplicate,
            parsable=identity.parsable,
            reasons=identity.reasons,
            work=None if identity.work is None else str(identity.work),
            version=None if identity.version is None else str(identity.version),
            artifact=None if identity.artifact is None else str(identity.artifact),
            title=identity.title,
            doi=identity.doi,
            arxiv=identity.arxiv,
            year=identity.year,
        )


class AttachmentPromotionView(_Response):
    """`attachment.save_to_corpus`: what the promotion linked, and what it created.

    `evidence_created` is always false and is stated rather than assumed: corpus identity
    is not evidence, and the receipt should say so where a researcher reads it
    (attachments design SS7).
    """

    attachment: AttachmentView
    work: str
    version: str
    artifact: str
    created: str
    outcome: str
    parsed: bool
    linked_existing: bool
    evidence_created: bool = False
    reasons: tuple[str, ...] = ()
    mutation: MutationResponse | None = None

    @classmethod
    def of(cls, promotion: AttachmentPromotion) -> AttachmentPromotionView:
        return cls(
            attachment=AttachmentView.of(promotion.attachment),
            work=str(promotion.work),
            version=str(promotion.version),
            artifact=str(promotion.artifact),
            created=promotion.created,
            outcome=promotion.outcome.value,
            parsed=promotion.parsed,
            linked_existing=promotion.linked_existing,
            reasons=promotion.reasons,
            mutation=(
                None if promotion.mutation is None else MutationResponse.of(promotion.mutation)
            ),
        )


# -- handlers ----------------------------------------------------------------


def attachment_service(ctx: CapabilityContext) -> AttachmentService:
    """The attachment service for this context, sharing the repository's lock."""
    return AttachmentService(ConversationStore.for_repository(ctx.repo))


def add_attachment(ctx: CapabilityContext, request: AddAttachmentRequest) -> AttachmentView:
    """`attachment.add`: copy one file into the session and validate it.

    A file that fails validation still comes back — as a `failed` attachment carrying the
    reason — because an item that disappears is the failure mode the design forbids
    (attachments design SS2).
    """
    data, filename = request.bytes_and_name()
    service = attachment_service(ctx)
    attachment = service.add(
        request.session,
        filename=filename,
        media_type=request.media_type,
        data=data,
        provenance=ctx.provenance(workflow="attachment"),
        description=request.description,
        visibility=request.visibility,
    )
    return AttachmentView.of(attachment)


def remove_attachment(
    ctx: CapabilityContext, request: RemoveAttachmentRequest
) -> AttachmentRemoved:
    """`attachment.remove`: delete a session attachment nothing durable refers to."""
    service = attachment_service(ctx)
    attachment = service.get(request.session, request.attachment)
    service.remove(attachment)
    return AttachmentRemoved(session=str(request.session), attachment=str(request.attachment))


def check_attachment_send(
    ctx: CapabilityContext, request: CheckAttachmentSendRequest
) -> AttachmentSendCheck:
    """`attachment.check_send`: the per-item verdict for the selected model. A read."""
    from research_harness.privacy.policy import load_policy

    service = attachment_service(ctx)
    attachments = service.list_attachments(request.session)
    if request.attachments:
        wanted = set(request.attachments)
        missing = sorted(str(name) for name in wanted - {item.id for item in attachments})
        if missing:
            raise CapabilityError(
                f"attachment.check_send: session {request.session} has no {', '.join(missing)}"
            )
        attachments = [item for item in attachments if item.id in wanted]
    models, provider = _session_target(ctx, request)
    selected, alternatives = _select_model(models, provider, request.model)
    check = sendability(
        attachments,
        provider=selected[0].split("/", 1)[0],
        model=selected[0].split("/", 1)[-1],
        capabilities=selected[1],
        policy=load_policy(ctx.repo),
        alternatives=alternatives,
    )
    return AttachmentSendCheck.of(request.session, check)


def resolve_attachment_identity(
    ctx: CapabilityContext, request: ResolveAttachmentIdentityRequest
) -> AttachmentIdentityView:
    """`attachment.resolve_identity`: hash, inspect, and match against the corpus. A read."""
    store = ConversationStore.for_repository(ctx.repo)
    service = AttachmentPromotionService(ctx, store=store)
    attachment = store.get_attachment(request.session, request.attachment)
    return AttachmentIdentityView.of(service.resolve(attachment))


def save_attachment_to_corpus(
    ctx: CapabilityContext, request: SaveAttachmentToCorpusRequest
) -> AttachmentPromotionView:
    """`attachment.save_to_corpus`: the explicit promotion into corpus identity."""
    store = ConversationStore.for_repository(ctx.repo)
    service = AttachmentPromotionService(ctx, store=store)
    attachment = store.get_attachment(request.session, request.attachment)
    promotion = service.save(
        attachment, as_new=request.as_new, attach_to=request.attach_to, parse=request.parse
    )
    return AttachmentPromotionView.of(promotion)


# -- configured models -------------------------------------------------------


def configured_models(ctx: CapabilityContext) -> list[tuple[str, ProviderCapabilities]]:
    """Every enabled provider entry as `(label, capabilities)`, best priority first.

    Read from `research.yaml` without constructing an adapter or resolving a credential,
    the way the egress report does: deciding whether a model could take a PNG must not
    depend on having a key for it (Product 34).
    """
    from research_harness.providers.models.router import RouterConfig, entry_capabilities

    config = RouterConfig.model_validate({"providers": list(ctx.repo.config.providers)})
    entries: list[tuple[int, str, ProviderCapabilities]] = []
    for provider_config in config.providers:
        if not provider_config.enabled:
            continue
        entries.append(
            (
                provider_config.priority,
                f"{provider_config.name}/{provider_config.model}",
                entry_capabilities(provider_config),
            )
        )
    entries.sort(key=lambda item: (item[0], item[1]))
    return [(label, capabilities) for _, label, capabilities in entries]


def _session_target(
    ctx: CapabilityContext, request: CheckAttachmentSendRequest
) -> tuple[list[tuple[str, ProviderCapabilities]], str | None]:
    """The models this check may pick from, and the one the session is bound to.

    A check must describe the send that would actually happen (binding spec §9). A named
    `provider`/`model` wins, exactly as a per-message model wins on send; otherwise a
    runtime binding contributes its in-memory entry -- which is the whole target when
    `research.yaml` has no `providers:` list -- and an entry binding narrows to its name,
    so a binding to an entry that is gone is refused here as it is there.
    """
    from research_harness.conversation.binding import (
        EntryBinding,
        RuntimeBinding,
        binding_of,
        session_entry,
    )
    from research_harness.providers.models.router import entry_capabilities

    models = configured_models(ctx)
    if request.provider is not None or request.model is not None:
        return models, request.provider
    store = ConversationStore.for_repository(ctx.repo)
    binding = binding_of(store.get_session(request.session).defaults)
    if isinstance(binding, EntryBinding):
        return models, binding.name
    if not isinstance(binding, RuntimeBinding):
        return models, None
    entry = session_entry(binding)
    label = f"{entry.name}/{entry.model}"
    return (
        [
            (label, entry_capabilities(entry)),
            *(item for item in models if item[0] != label),
        ],
        None,
    )


def _select_model(
    models: list[tuple[str, ProviderCapabilities]], provider: str | None, model: str | None
) -> tuple[tuple[str, ProviderCapabilities], list[tuple[str, ProviderCapabilities]]]:
    """The entry the check is about, and every other configured entry as an alternative."""
    if not models:
        raise CapabilityError(
            "attachment.check_send: no model providers configured; add a `providers:` list "
            "to research.yaml so the workspace knows what the attachments would be sent to"
        )
    if provider is None and model is None:
        return models[0], list(models[1:])
    matches = [entry for entry in models if _matches(entry[0], provider, model)]
    if not matches:
        known = ", ".join(label for label, _ in models)
        wanted = "/".join(part for part in (provider, model) if part)
        raise CapabilityError(
            f"attachment.check_send: no configured model matches {wanted!r} (have: {known})"
        )
    return matches[0], [entry for entry in models if entry[0] != matches[0][0]]


def _matches(label: str, provider: str | None, model: str | None) -> bool:
    name, _, served = label.partition("/")
    if provider is not None and provider not in {name, label, served}:
        return False
    return model is None or model in {served, label}


# -- registration ------------------------------------------------------------


def attachment_specs() -> list[CapabilitySpec]:
    """The five `attachment.*` capabilities, named and permissioned."""
    return [
        CapabilitySpec(
            name="attachment.add",
            summary="Attach a file to a session as working material.",
            permission=Permission.MUTATE,
            scientific_semantics=(
                "copies bytes into a session; creates no Work, Version, Artifact, or Evidence"
            ),
            request_model=AddAttachmentRequest,
            response_model=AttachmentView,
            handler=add_attachment,
        ),
        CapabilitySpec(
            name="attachment.remove",
            summary="Delete a session attachment, its bytes, and its previews.",
            permission=Permission.MUTATE,
            scientific_semantics=(
                "removes session-only working material; the corpus is not touched"
            ),
            request_model=RemoveAttachmentRequest,
            response_model=AttachmentRemoved,
            handler=remove_attachment,
        ),
        CapabilitySpec(
            name="attachment.check_send",
            summary="Whether each attachment may go to the selected model, and why not.",
            permission=Permission.READ,
            scientific_semantics=(
                "reads attachment records and provider capabilities; changes nothing"
            ),
            request_model=CheckAttachmentSendRequest,
            response_model=AttachmentSendCheck,
            handler=check_attachment_send,
        ),
        CapabilitySpec(
            name="attachment.resolve_identity",
            summary="What one attachment would become in the corpus, without saving it.",
            permission=Permission.READ,
            scientific_semantics="resolves corpus identity for a file; writes nothing",
            request_model=ResolveAttachmentIdentityRequest,
            response_model=AttachmentIdentityView,
            handler=resolve_attachment_identity,
        ),
        CapabilitySpec(
            name="attachment.save_to_corpus",
            summary="Promote a session attachment into the corpus under a resolved identity.",
            permission=Permission.MUTATE,
            scientific_semantics=(
                "creates or links Work/Version/Artifact identity and parses the file; "
                "accepts no Evidence or Claim"
            ),
            request_model=SaveAttachmentToCorpusRequest,
            response_model=AttachmentPromotionView,
            handler=save_attachment_to_corpus,
            human_only=True,
        ),
    ]


#: The handler behind each name, so the registry and the handler table stay one fact.
ATTACHMENT_CAPABILITY_HANDLERS: dict[str, Any] = {
    "attachment.add": add_attachment,
    "attachment.remove": remove_attachment,
    "attachment.check_send": check_attachment_send,
    "attachment.resolve_identity": resolve_attachment_identity,
    "attachment.save_to_corpus": save_attachment_to_corpus,
}
