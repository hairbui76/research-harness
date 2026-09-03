"""`sendability`: the pure check that decides whether a send may proceed, and why not.

One property carries the phase: an attachment the researcher can see is never silently
dropped. Every item comes back as `sent`, `converted`, or `omitted` with a reason, a
*ready* item that cannot travel blocks the whole send, and the same verdicts become the
`Context used` lines — so the receipt cannot say something the check did not decide
(attachments design SS5, ROADMAP Gate P19).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from research_harness.conversation.attachments import (
    DEFAULT_LIMITS,
    AttachmentLimits,
    SendCheck,
    SendDisposition,
    attachment_link,
    receipt_items,
    sendability,
)
from research_harness.domain.base import Provenance
from research_harness.domain.conversation import (
    AttachmentState,
    ContextClass,
    ContextReceipt,
    OmissionReason,
    SessionAttachment,
    Visibility,
)
from research_harness.domain.ids import ConversationSessionId, SessionAttachmentId
from research_harness.privacy.policy import EgressPolicy
from research_harness.providers.models.base import EgressDeclaration, ProviderCapabilities
from research_harness.providers.models.media import DOCUMENT_MEDIA_TYPES, IMAGE_MEDIA_TYPES

SESSION = ConversationSessionId("CS0001")
HASH = "sha256:" + "a" * 64


def attachment(
    number: int = 1,
    *,
    media_type: str = "image/png",
    state: AttachmentState = AttachmentState.READY,
    size_bytes: int = 2048,
    page_count: int | None = None,
    visibility: Visibility = Visibility.PROJECT,
    filename: str | None = None,
    failure_reason: str | None = None,
) -> SessionAttachment:
    """One attachment record, ready by default, with no store behind it."""
    return SessionAttachment(
        id=SessionAttachmentId(f"SA{number:04d}"),
        session=SESSION,
        state=state,
        filename=filename or f"file-{number}",
        media_type=media_type,
        size_bytes=size_bytes,
        content_hash=None if state is AttachmentState.FAILED else HASH,
        page_count=page_count,
        visibility=visibility,
        failure_reason=failure_reason,
        provenance=Provenance.human(),
    )


def provider_capabilities(
    *, media: frozenset[str] = frozenset(), host: str = "api.example.com"
) -> ProviderCapabilities:
    return ProviderCapabilities(
        structured_output=True,
        max_context_tokens=200_000,
        reasoning_levels={"low", "high"},
        input_media=media,
        egress=EgressDeclaration(
            endpoint_host=host,
            sends_source_text=True,
            sends_identifiers=True,
            description="a fake provider",
        ),
    )


SIGHTED = provider_capabilities(media=IMAGE_MEDIA_TYPES | DOCUMENT_MEDIA_TYPES)
BLIND = provider_capabilities()
LOCAL_BLIND = provider_capabilities(host="localhost")


def check(
    attachments: list[SessionAttachment],
    *,
    capabilities: ProviderCapabilities = SIGHTED,
    policy: EgressPolicy | None = None,
    alternatives: Sequence[tuple[str, ProviderCapabilities]] = (),
    limits: AttachmentLimits = DEFAULT_LIMITS,
) -> SendCheck:
    """`sendability` for one fake provider, so each test states only what it varies."""
    return sendability(
        attachments,
        provider="fake",
        model="fake-1",
        capabilities=capabilities,
        policy=policy,
        alternatives=alternatives,
        limits=limits,
    )


# -- what travels ------------------------------------------------------------


def test_a_supported_image_and_pdf_are_sent() -> None:
    result = check([attachment(1), attachment(2, media_type="application/pdf", page_count=8)])

    assert result.ok is True
    assert [item.disposition for item in result.items] == [
        SendDisposition.SENT,
        SendDisposition.SENT,
    ]
    assert result.refusal() is None


def test_a_text_file_is_converted_when_the_model_takes_no_media() -> None:
    """Local conversion is the difference between a text file and an image (design SS5)."""
    result = check([attachment(1, media_type="text/markdown")], capabilities=BLIND)
    item = result.items[0]

    assert item.disposition is SendDisposition.CONVERTED
    assert item.ok is True
    assert result.ok is True


# -- what blocks -------------------------------------------------------------


def test_an_unsupported_image_blocks_the_send_and_names_a_model_that_would_take_it() -> None:
    result = check(
        [attachment(1, filename="figure.png")],
        capabilities=BLIND,
        alternatives=[("sighted/model-1", SIGHTED)],
    )
    item = result.items[0]

    assert result.ok is False
    assert item.disposition is SendDisposition.OMITTED
    assert item.omission is OmissionReason.UNSUPPORTED_MEDIA
    assert item.suggested_model == "sighted/model-1"
    assert "figure.png" in str(result.refusal())


def test_a_private_attachment_never_reaches_an_external_provider() -> None:
    """Product 42 N and workspace design SS7: private working context stays on the machine."""
    private = attachment(1, visibility=Visibility.PRIVATE)

    external = check([private], capabilities=SIGHTED)
    local = check(
        [private], capabilities=provider_capabilities(media=IMAGE_MEDIA_TYPES, host="localhost")
    )

    assert external.ok is False
    assert external.items[0].omission is OmissionReason.PRIVACY_POLICY
    assert local.ok is True


def test_a_policy_that_forbids_external_models_blocks_before_capability() -> None:
    """ADR-018: the refusal names the policy, not the model's eyesight."""
    result = check(
        [attachment(1)],
        capabilities=SIGHTED,
        policy=EgressPolicy(external_models="disabled"),
        alternatives=[("local/small", LOCAL_BLIND)],
    )
    item = result.items[0]

    assert item.omission is OmissionReason.EGRESS_BLOCKED
    assert "external model egress is disabled" in str(item.reason)
    # The local alternative is blind, so it is not offered for an image either.
    assert item.suggested_model is None


def test_an_oversize_file_and_an_overlong_pdf_are_refused_with_the_number() -> None:
    limits = AttachmentLimits(max_image_bytes=1024, max_sent_pdf_pages=4)
    result = check(
        [
            attachment(1, size_bytes=4096),
            attachment(2, media_type="application/pdf", page_count=9),
        ],
        limits=limits,
    )

    assert result.ok is False
    assert "1024-byte limit" in str(result.items[0].reason)
    assert "4-page send limit" in str(result.items[1].reason)


def test_more_attachments_than_one_request_carries_are_refused_not_truncated() -> None:
    limits = AttachmentLimits(max_sent_items=2)
    result = check([attachment(number) for number in range(1, 5)], limits=limits)

    dispositions = [item.disposition for item in result.items]
    assert dispositions == [
        SendDisposition.SENT,
        SendDisposition.SENT,
        SendDisposition.OMITTED,
        SendDisposition.OMITTED,
    ]
    assert result.items[2].omission is OmissionReason.TOKEN_BUDGET
    assert result.ok is False


def test_an_attachment_that_never_became_ready_is_reported_but_does_not_block() -> None:
    """A failed intake promised nothing, so it cannot be the thing that was dropped."""
    failed = attachment(
        1, state=AttachmentState.FAILED, failure_reason="the bytes are not a readable PNG"
    )
    result = check([failed, attachment(2)])

    assert result.ok is True
    assert result.items[0].disposition is SendDisposition.OMITTED
    assert result.items[0].ok is True
    assert "not a readable PNG" in str(result.items[0].reason)


def test_the_limits_are_stated_rather_than_hidden() -> None:
    assert DEFAULT_LIMITS.max_sent_items > 0
    assert DEFAULT_LIMITS.max_pdf_pages >= DEFAULT_LIMITS.max_sent_pdf_pages


# -- the receipt -------------------------------------------------------------


def test_the_receipt_lists_every_attachment_as_sent_converted_or_omitted() -> None:
    result = check(
        [
            attachment(1, filename="figure.png"),
            attachment(2, media_type="text/csv", filename="table.csv", size_bytes=400),
            attachment(3, media_type="image/webp", filename="odd.webp"),
        ],
        capabilities=provider_capabilities(media=frozenset({"image/png"})),
    )
    included, omitted = receipt_items(result)
    receipt = ContextReceipt(included=included, omitted=omitted)

    assert [item.source for item in included] == [
        attachment_link(SessionAttachmentId("SA0001")),
        attachment_link(SessionAttachmentId("SA0002")),
    ]
    assert "sent" in str(included[0].label)
    assert "converted" in str(included[1].label)
    assert [item.source for item in omitted] == [attachment_link(SessionAttachmentId("SA0003"))]
    assert omitted[0].reason is OmissionReason.UNSUPPORTED_MEDIA
    assert receipt.tokens_by_class()[ContextClass.ATTACHMENTS] == included[1].tokens
    assert all(item.context_class is ContextClass.ATTACHMENTS for item in (*included, *omitted))


def test_a_receipt_never_lists_the_same_attachment_twice() -> None:
    """`ContextReceipt` refuses a source in both lists; the check must never produce one."""
    result = check([attachment(1), attachment(2, media_type="image/webp")])
    included, omitted = receipt_items(result)

    ContextReceipt(included=included, omitted=omitted)  # raises if a source repeats
    assert {item.source for item in included} & {item.source for item in omitted} == set()


def test_an_omitted_line_carries_the_reason_and_the_suggestion() -> None:
    result = check(
        [attachment(1, filename="figure.png")],
        capabilities=BLIND,
        alternatives=[("sighted/model-1", SIGHTED)],
    )
    _, omitted = receipt_items(result)

    assert omitted[0].detail is not None
    assert "sighted/model-1 would accept it" in omitted[0].detail


@pytest.mark.parametrize("state", [AttachmentState.SELECTED, AttachmentState.VALIDATING])
def test_an_attachment_still_being_validated_is_not_sent(state: AttachmentState) -> None:
    result = check([attachment(1, state=state)])

    assert result.items[0].disposition is SendDisposition.OMITTED
    assert result.ok is True
