"""`ConversationService.configure`: a binding is validated like an entry (binding spec §8)."""

from __future__ import annotations

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.conversation.binding import EntryBinding, RuntimeBinding, binding_of
from research_harness.conversation.service import ConversationService
from research_harness.domain.conversation import Visibility
from research_harness.domain.errors import CapabilityError
from tests.fixtures.cli.fakes import FakeCli

SHAREABLE = Visibility.PROJECT
"""A CLI runtime is external egress, so only a shareable session may be bound to one."""


def test_a_runtime_binding_is_stored_with_its_model_and_reasoning(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = service.create("Latency study", visibility=SHAREABLE)

    record = service.configure(session.id, runtime="codex", model="gpt-5.5", reasoning="high")

    assert binding_of(record.defaults) == RuntimeBinding("codex", "gpt-5.5", "high")
    assert service.store.get_session(session.id).defaults == record.defaults, "durable"
    assert codex.runs() == [], "binding never sends a request"


def test_default_model_and_no_reasoning_are_accepted(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = service.create("x", visibility=SHAREABLE)
    record = service.configure(session.id, runtime="codex", model="default")
    assert binding_of(record.defaults) == RuntimeBinding("codex", "default", None)


def test_a_runtime_with_no_proven_posture_is_refused_with_the_entry_sentence(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = service.create("x")
    with pytest.raises(CapabilityError, match="has no proven bounded"):
        service.configure(session.id, runtime="pi", model="default")


def test_an_unknown_runtime_an_unlisted_model_and_an_unoffered_reasoning_are_refused(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = service.create("x")
    with pytest.raises(CapabilityError, match="runtime"):
        service.configure(session.id, runtime="nope", model="default")
    with pytest.raises(CapabilityError, match="does not list model 'gpt-9'"):
        service.configure(session.id, runtime="codex", model="gpt-9")
    with pytest.raises(CapabilityError, match="reasoning 'max'"):
        service.configure(session.id, runtime="codex", model="gpt-5.5", reasoning="max")


def test_an_installed_but_logged_out_runtime_can_still_be_bound(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    codex.write_script(
        {
            **codex.script(),
            "probes": [
                {"args": ["login", "status"], "stdout": "Not logged in\n", "exit": 1},
                *[p for p in codex.script()["probes"] if p["args"] != ["login", "status"]],
            ],
        }
    )
    from research_harness.providers.cli.detection import DEFAULT_CACHE

    DEFAULT_CACHE.clear()
    service = ConversationService(ctx)
    session = service.create("x", visibility=SHAREABLE)
    record = service.configure(session.id, runtime="codex", model="gpt-5.5")
    assert binding_of(record.defaults) == RuntimeBinding("codex", "gpt-5.5", None)


def test_a_private_session_may_not_be_bound_to_a_runtime(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    """Every CLI runtime is external egress, so the refusal belongs at bind time.

    Storing the binding and refusing on every send would leave a session that looks
    configured and can never answer; the daemon says so once, in the sentence the send
    path uses.
    """
    service = ConversationService(ctx)
    private = service.create("x")
    assert private.visibility is Visibility.PRIVATE, "the default, and the case that matters"

    with pytest.raises(CapabilityError) as caught:
        service.configure(private.id, runtime="codex", model="gpt-5.5")

    assert f"session {private.id} is private" in str(caught.value)
    assert "session:codex/gpt-5.5 is an external provider" in str(caught.value)
    assert service.store.get_session(private.id).defaults.model is None, "nothing was stored"
    assert codex.runs() == []

    shareable = service.create("x", visibility=SHAREABLE)
    record = service.configure(shareable.id, runtime="codex", model="gpt-5.5")
    assert binding_of(record.defaults) == RuntimeBinding("codex", "gpt-5.5", None)


def test_a_private_session_may_still_be_bound_to_an_entry(ctx: CapabilityContext) -> None:
    """An entry can be local, so its egress is the send path's question, not bind time's."""
    ctx.repo.update_providers(
        [
            {
                "name": "on-box",
                "kind": "local_openai_compatible",
                "model": "llama-test",
                "base_url": "http://127.0.0.1:11434/v1",
            }
        ]
    )
    service = ConversationService(ctx)
    session = service.create("x")

    record = service.configure(session.id, entry="on-box")

    assert binding_of(record.defaults) == EntryBinding("on-box")


def test_an_entry_binding_needs_an_enabled_entry(ctx: CapabilityContext) -> None:
    ctx.repo.update_providers(
        [
            {
                "name": "fast",
                "kind": "openai",
                "model": "gpt-5.4-mini",
                "api_key_env": "OPENAI_API_KEY",
            },
            {
                "name": "retired",
                "kind": "openai",
                "model": "gpt-5.4-mini",
                "api_key_env": "OPENAI_API_KEY",
                "enabled": False,
            },
        ]
    )
    service = ConversationService(ctx)
    session = service.create("x")
    assert binding_of(service.configure(session.id, entry="fast").defaults) == EntryBinding("fast")
    with pytest.raises(CapabilityError, match="no provider named 'slow'"):
        service.configure(session.id, entry="slow")
    with pytest.raises(CapabilityError, match="no provider named 'retired'"):
        service.configure(session.id, entry="retired")


def test_clear_returns_the_session_to_the_project_default(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = service.create("x", token_budget=4000, visibility=SHAREABLE)
    service.configure(session.id, runtime="codex", model="gpt-5.5", reasoning="high")
    record = service.configure(session.id, clear=True)
    assert record.defaults.model is None and record.defaults.reasoning is None
    assert record.defaults.token_budget == 4000, "other defaults are kept"


def test_exactly_one_target_is_required(ctx: CapabilityContext) -> None:
    service = ConversationService(ctx)
    session = service.create("x")
    with pytest.raises(CapabilityError, match="exactly one of"):
        service.configure(session.id)
    with pytest.raises(CapabilityError, match="exactly one of"):
        service.configure(session.id, entry="fast", clear=True)
    with pytest.raises(CapabilityError, match="model is required"):
        service.configure(session.id, runtime="codex")


def test_create_stores_a_model_argument_as_an_entry_binding(ctx: CapabilityContext) -> None:
    # A slash-bearing name separates the two behaviours: `create` used to split on "/" and
    # store `provider="openai", model="gpt-4"`, which the legacy read turns into
    # `EntryBinding("gpt-4")`. The whole string is now the entry name.
    session = ConversationService(ctx).create("x", model="openai/gpt-4")
    assert session.defaults.model is not None and session.defaults.model.provider == "entry"
    assert binding_of(session.defaults) == EntryBinding("openai/gpt-4")
