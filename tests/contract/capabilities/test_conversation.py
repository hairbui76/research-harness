"""The `session.*` / `context.*` capability contract: names, authority, and refusals.

Two things are pinned here. The first is the permission model: conversation is private
working context, so every read is host-readable and every write needs the researcher — a
host that could append to a transcript could put words in it and then promote them. The
second is the promotion boundary: `evidence` is refused with a typed error that names the
anchor requirement, because "not a valid enum value" is not an answer a person can act on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.conversation import (
    CONVERSATION_CAPABILITIES,
    CONVERSATION_CAPABILITY_HANDLERS,
)
from research_harness.capabilities.handlers import CAPABILITY_HANDLERS
from research_harness.capabilities.permissions import (
    Permission,
    PermissionDenied,
    Principal,
)
from research_harness.capabilities.registry import CapabilityRegistry, build_default_registry
from research_harness.conversation.promote import EvidenceRequiresAnchorError
from research_harness.domain.conversation import AttemptStatus, MessageRole, PromotionTarget
from research_harness.domain.enums import ClaimStatus, DecisionStatus
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import ClaimId, DecisionId
from research_harness.workspace.repository import WorkspaceRepository

READS = {"session.list", "session.get", "session.search", "context.preview", "context.get"}
MUTATIONS = set(CONVERSATION_CAPABILITIES) - READS


@pytest.fixture
def registry() -> CapabilityRegistry:
    return build_default_registry()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    WorkspaceRepository.init(tmp_path / "project", "conversation-contract")
    return tmp_path / "project"


@pytest.fixture
def ctx(workspace: Path) -> CapabilityContext:
    return open_context(workspace)


# -- the surface -------------------------------------------------------------


def test_every_conversation_capability_is_registered(registry: CapabilityRegistry) -> None:
    assert set(CONVERSATION_CAPABILITIES) <= set(registry.names())
    assert set(CONVERSATION_CAPABILITIES) == set(CONVERSATION_CAPABILITY_HANDLERS)


def test_the_registry_and_the_handler_table_agree_about_conversation(
    registry: CapabilityRegistry,
) -> None:
    for name, handler in CONVERSATION_CAPABILITY_HANDLERS.items():
        assert registry.get(name).handler is handler
        assert CAPABILITY_HANDLERS[name] is handler


@pytest.mark.parametrize("name", sorted(READS))
def test_a_conversation_read_is_host_readable(registry: CapabilityRegistry, name: str) -> None:
    spec = registry.get(name)
    assert spec.permission is Permission.READ
    assert not spec.descriptor().human_only


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_a_conversation_write_needs_the_researcher(registry: CapabilityRegistry, name: str) -> None:
    """A host reads a transcript and proposes; it does not write one (Product 24, 29)."""
    spec = registry.get(name)
    assert spec.permission is Permission.MUTATE
    assert spec.descriptor().human_only is True


def test_sending_and_retrying_are_long_running(registry: CapabilityRegistry) -> None:
    """ADR-009: the answer arrives on a run, not on a held connection."""
    assert registry.get("session.send").long_running
    assert registry.get("session.retry").long_running
    assert not registry.get("context.preview").long_running


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_an_agent_host_is_refused_every_conversation_write(
    registry: CapabilityRegistry, ctx: CapabilityContext, name: str
) -> None:
    host = Principal.agent_host("claude")
    with pytest.raises(PermissionDenied):
        registry.invoke(name, ctx, {}, principal=host)


def test_an_agent_host_may_list_sessions(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    result = registry.invoke("session.list", ctx, {}, principal=Principal.agent_host("claude"))
    assert result.model_dump(mode="json") == {"count": 0, "sessions": []}


# -- the loop through the registry -------------------------------------------


def invoke(registry: CapabilityRegistry, ctx: CapabilityContext, name: str, request: object):
    return registry.invoke(name, ctx, request, principal=Principal.human())  # type: ignore[arg-type]


def test_a_session_round_trips_through_the_registry(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    created = invoke(registry, ctx, "session.create", {"title": "Latency study"})
    session = created.session.id

    renamed = invoke(
        registry, ctx, "session.rename", {"session": str(session), "title": "Latency, revisited"}
    )
    assert renamed.session.title == "Latency, revisited"

    listed = invoke(registry, ctx, "session.list", {})
    assert listed.count == 1

    read = invoke(registry, ctx, "session.get", {"session": str(session)})
    assert read.total == 0 and read.next_offset is None

    found = invoke(registry, ctx, "session.search", {"query": "latency"})
    assert found.count == 1 and found.matches[0].title_matched

    summarized = invoke(registry, ctx, "session.summarize", {"session": str(session)})
    assert "Latency, revisited" in summarized.summary


def test_context_preview_records_that_nothing_was_sent(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    created = invoke(registry, ctx, "session.create", {"title": "Latency study"})
    preview = invoke(
        registry,
        ctx,
        "context.preview",
        {"session": str(created.session.id), "text": "what do we know about latency"},
    )
    assert preview.pack.egress.value == "none"
    assert preview.tokens == preview.pack.receipt.total_tokens()
    assert "policy" in preview.tokens_by_class


def test_a_preview_can_refuse_to_persist_itself(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    created = invoke(registry, ctx, "session.create", {"title": "Latency study"})
    invoke(
        registry,
        ctx,
        "context.preview",
        {"session": str(created.session.id), "text": "latency", "persist": False},
    )
    read = invoke(registry, ctx, "session.get", {"session": str(created.session.id)})
    assert read.context_packs == ()


def test_context_get_answers_with_the_receipt_preview_recorded(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    """`context.get` and `context.preview` are one shape: a receipt, assembled or read back."""
    created = invoke(registry, ctx, "session.create", {"title": "Latency study"})
    session = str(created.session.id)
    preview = invoke(
        registry, ctx, "context.preview", {"session": session, "text": "does @C0404 still hold"}
    )

    read = invoke(registry, ctx, "context.get", {"session": session, "pack": str(preview.pack.id)})

    assert read == preview, "the same object, whether it was just assembled or read off disk"
    assert type(read) is type(preview)


def test_a_receipt_read_back_still_names_the_reference_that_resolved_to_nothing(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    """A receipt is complete on disk, so `Context used` needs no reassembly (Product 42 M)."""
    created = invoke(registry, ctx, "session.create", {"title": "Latency study"})
    session = str(created.session.id)
    preview = invoke(
        registry,
        ctx,
        "context.preview",
        {"session": session, "references": ["C9999"], "text": "and what about it"},
    )

    read = invoke(registry, ctx, "context.get", {"session": session, "pack": str(preview.pack.id)})

    assert read.unresolved == ("C9999",)
    assert read.pack.receipt.unresolved == ("C9999",)
    assert any(item.reason == "unresolved_reference" for item in read.omissions)


def test_a_receipt_survives_deleting_the_projection(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    """`conversations/` is durable; `.research/` is not (workspace design SS2)."""
    import shutil

    created = invoke(registry, ctx, "session.create", {"title": "Latency study"})
    session = str(created.session.id)
    preview = invoke(registry, ctx, "context.preview", {"session": session, "text": "latency"})

    shutil.rmtree(ctx.repo.layout.research_dir)

    read = invoke(registry, ctx, "context.get", {"session": session, "pack": str(preview.pack.id)})
    assert read.pack == preview.pack


def test_asking_for_a_receipt_that_was_never_recorded_is_a_typed_refusal(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    from research_harness.workspace.conversations import ConversationNotFoundError

    created = invoke(registry, ctx, "session.create", {"title": "Latency study"})
    with pytest.raises(ConversationNotFoundError):
        invoke(
            registry,
            ctx,
            "context.get",
            {"session": str(created.session.id), "pack": "CP0404"},
        )


# -- promotion ---------------------------------------------------------------


def promoted_session(registry: CapabilityRegistry, ctx: CapabilityContext) -> tuple[str, str]:
    """A session holding one model answer worth promoting, written without a provider."""
    from research_harness.domain.base import Provenance
    from research_harness.domain.conversation import Message, MessageAttempt, TextBlock
    from research_harness.workspace.conversations import ConversationStore

    created = invoke(registry, ctx, "session.create", {"title": "Latency study"})
    store = ConversationStore.for_repository(ctx.repo)
    message = store.append_message(
        created.session.id,
        lambda message_id: Message(
            id=message_id,
            session=created.session.id,
            role=MessageRole.ASSISTANT,
            blocks=(TextBlock(text="Batching reduces tail latency across the pilot corpus."),),
            attempt=MessageAttempt(status=AttemptStatus.COMPLETE),
            provenance=Provenance.human(),
        ),
    )
    return str(created.session.id), str(message.id)


def test_promoting_to_evidence_is_refused_with_the_anchor_requirement(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    session, message = promoted_session(registry, ctx)

    with pytest.raises(EvidenceRequiresAnchorError) as refusal:
        invoke(
            registry,
            ctx,
            "session.promote",
            {"session": session, "message": message, "target": "evidence"},
        )
    assert "anchor" in str(refusal.value)
    assert "note, question, or claim candidate" in str(refusal.value)


def test_a_note_promotion_copies_the_excerpt_and_leaves_the_message_alone(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    session, message = promoted_session(registry, ctx)
    before = invoke(registry, ctx, "session.get", {"session": session}).messages

    result = invoke(
        registry,
        ctx,
        "session.promote",
        {"session": session, "message": message, "target": "note"},
    )
    assert result.target is PromotionTarget.NOTE
    assert result.accepted is False
    after = invoke(registry, ctx, "session.get", {"session": session}).messages
    assert after == before, "promotion copies; it never rewrites the transcript"
    notes = list(ctx.repo.iter_notes())
    assert len(notes) == 1
    assert "Batching reduces tail latency" in notes[0].text
    assert f"session {session}/{message}" in (notes[0].provenance.note or "")


def test_a_claim_candidate_is_created_unverified_and_still_needs_an_audit(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    session, message = promoted_session(registry, ctx)

    result = invoke(
        registry,
        ctx,
        "session.promote",
        {
            "session": session,
            "message": message,
            "target": "claim_candidate",
            "subject": "batching",
            "predicate": "reduces",
            "object": "tail latency",
            "scope": "corpus_pattern",
        },
    )
    claim = ctx.repo.get_claim(ClaimId(str(result.object_id)))
    assert claim.assessment.status is ClaimStatus.UNVERIFIED
    assert claim.assessment.allowed_strength.level == 0, "review decides what it may say"
    assert "promoted from rh://session/" in (claim.provenance.note or "")


def test_a_claim_candidate_without_a_proposition_is_refused(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    session, message = promoted_session(registry, ctx)

    with pytest.raises(CapabilityError, match="subject, predicate, object"):
        invoke(
            registry,
            ctx,
            "session.promote",
            {"session": session, "message": message, "target": "claim_candidate"},
        )


def test_a_decision_candidate_is_drafted_and_not_accepted(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    """Accepting is `decision.accept`, a separate researcher act. Promotion drafts."""
    session, message = promoted_session(registry, ctx)

    result = invoke(
        registry,
        ctx,
        "session.promote",
        {"session": session, "message": message, "target": "decision_candidate"},
    )
    assert result.decision is not None
    assert result.decision["status"] == DecisionStatus.PROPOSED.value
    assert result.accepted is False
    assert "decision.accept" in result.review
    assert ctx.repo.list_decisions() == [], "no Decision is written until it is accepted"
    from research_harness.workspace.repository import ObjectNotFoundError

    with pytest.raises(ObjectNotFoundError):
        ctx.repo.get_decision(DecisionId(str(result.object_id)))
    assert len(list(ctx.repo.iter_notes())) == 1, "the proposal is durable as a note"
