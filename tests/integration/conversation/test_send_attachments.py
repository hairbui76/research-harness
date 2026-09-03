"""What a session's attachments do to a send: they travel, or they stop it.

The rule the attachments design refuses to bend (SS5, SS7): a *ready* attachment the
selected model cannot take blocks the send, with a reason per item. It never disappears
from the request quietly, and it never reaches the model as a shrug. A preview reports the
same verdict without refusing, because seeing what would happen is the point of a preview.
"""

from __future__ import annotations

from typing import Any

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.conversation.attachments import AttachmentService
from research_harness.domain.conversation import (
    AttachmentState,
    ContextClass,
    OmissionReason,
)
from research_harness.domain.errors import CapabilityError
from research_harness.providers.models.scripted import (
    ScriptedProvider,
    default_scripted_capabilities,
)
from research_harness.workspace.conversations import ConversationStore
from tests.fixtures.attachments import png_bytes
from tests.integration.conversation.conftest import ANSWER, service_for


def vision_capabilities() -> Any:
    """Scripted capabilities that accept an image, so a figure may travel.

    Re-validated rather than copied: `vision` and `input_media` are two spellings of one
    fact, and only validation derives one from the other.
    """
    from research_harness.providers.models.base import ProviderCapabilities

    declared = default_scripted_capabilities().model_dump(exclude={"input_media"})
    return ProviderCapabilities.model_validate({**declared, "vision": True})


def attach(ctx: CapabilityContext, session: Any, name: str, media: str, data: bytes) -> Any:
    service = AttachmentService(ConversationStore.for_repository(ctx.repo))
    return service.add(
        session, filename=name, media_type=media, data=data, provenance=ctx.provenance()
    )


def test_a_sendable_attachment_reaches_the_request_and_the_receipt(
    ctx: CapabilityContext,
) -> None:
    provider = ScriptedProvider([{"text": ANSWER}], capabilities=vision_capabilities())
    service = service_for(ctx, provider)
    session = service.create("Latency study")
    image = attach(ctx, session.id, "figure.png", "image/png", png_bytes())

    started = service.send(session.id, "What does this figure show?", background=False)

    pack = service.read_pack(session.id, started.context_pack)
    attached = [
        item for item in pack.receipt.included if item.context_class is ContextClass.ATTACHMENTS
    ]
    assert [str(item.id) for item in attached] == [str(image.id)]
    assert any(envelope.object_id == str(image.id) for envelope in provider.requests[0].inputs)


def test_a_ready_attachment_the_model_cannot_take_blocks_the_send(
    ctx: CapabilityContext,
) -> None:
    provider = ScriptedProvider([{"text": ANSWER}])  # declares no vision
    service = service_for(ctx, provider)
    session = service.create("Latency study")
    image = attach(ctx, session.id, "figure.png", "image/png", png_bytes())

    with pytest.raises(CapabilityError) as refusal:
        service.send(session.id, "What does this figure show?", background=False)

    assert str(image.id) in str(refusal.value)
    assert "figure.png" in str(refusal.value)
    assert service.transcript(session.id).total == 0, "a blocked send writes nothing"


def test_a_preview_reports_a_blocked_attachment_instead_of_refusing(
    ctx: CapabilityContext,
) -> None:
    provider = ScriptedProvider([{"text": ANSWER}])
    service = service_for(ctx, provider)
    session = service.create("Latency study")
    image = attach(ctx, session.id, "figure.png", "image/png", png_bytes())

    pack, _ = service.preview(session.id, "What does this figure show?", persist=False)

    blocked = [
        item for item in pack.receipt.omitted if item.context_class is ContextClass.ATTACHMENTS
    ]
    assert [str(item.id) for item in blocked] == [str(image.id)]
    assert blocked[0].detail


def test_an_attachment_that_never_became_ready_is_reported_and_does_not_block(
    ctx: CapabilityContext,
) -> None:
    """A failed item was never promised to anyone, so it explains itself and stands aside."""
    provider = ScriptedProvider([{"text": ANSWER}], capabilities=vision_capabilities())
    service = service_for(ctx, provider)
    session = service.create("Latency study")
    broken = attach(ctx, session.id, "truncated.png", "image/png", b"\x89PNG" + b"broken")

    assert broken.state is AttachmentState.FAILED

    started = service.send(session.id, "What does this figure show?", background=False)

    pack = service.read_pack(session.id, started.context_pack)
    omitted = [
        item for item in pack.receipt.omitted if item.context_class is ContextClass.ATTACHMENTS
    ]
    assert [str(item.id) for item in omitted] == [str(broken.id)]
    assert omitted[0].reason is OmissionReason.UNSUPPORTED_MEDIA
