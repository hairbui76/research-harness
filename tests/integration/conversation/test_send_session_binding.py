"""A bound session routes like an entry and is refused like one (binding spec §9)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.conversation.service import ConversationService
from research_harness.domain.conversation import (
    AttemptStatus,
    EgressClass,
    Message,
    MessageRole,
    ModelIdentity,
    SessionDefaults,
    Visibility,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import ConversationSessionId
from research_harness.privacy.policy import EgressDeniedError, EgressPolicy
from research_harness.providers.cli.detection import DEFAULT_CACHE
from research_harness.workspace.conversations import ConversationStore
from tests.fixtures.cli.fakes import FakeCli


def last_assistant(service: ConversationService, session: ConversationSessionId) -> Message:
    page = service.transcript(session, limit=500)
    return [message for message in page.messages if message.role is MessageRole.ASSISTANT][-1]


def traces(ctx: CapabilityContext) -> list[dict[str, Any]]:
    """Every completion trace this workspace wrote, oldest name first."""
    root = ctx.repo.layout.research_dir / "traces"
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("*/completion-*.json"))
    ]


def bound_session(service: ConversationService, **binding: Any) -> ConversationSessionId:
    """A session a CLI runtime may answer: `project`, because Codex is external egress."""
    session = service.create("Latency study", visibility=Visibility.PROJECT)
    service.configure(session.id, **binding)
    return session.id


def test_a_bound_session_spawns_the_runtime_with_its_model_and_reasoning(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = bound_session(service, runtime="codex", model="gpt-5.5", reasoning="high")

    service.send(session, "What does Table 3 say?", background=False)

    (run,) = codex.runs()
    argv = run["argv"]
    assert argv[argv.index("--model") + 1] == "gpt-5.5"
    assert 'model_reasoning_effort="high"' in argv
    assert argv[argv.index('model_reasoning_effort="high"') - 1] == "-c"
    assert "What does Table 3 say?" not in " ".join(argv)
    answer = last_assistant(service, session)
    assert answer.model is not None
    assert (answer.model.provider, answer.model.model) == ("session:codex", "gpt-5.5")
    # The transcript names the binding; the trace names the adapter that ran, because the
    # trace writer records `provider.name` (plan ruling 2).
    (trace,) = traces(ctx)
    assert (trace["provider"], trace["model"]) == ("local_cli:codex", "gpt-5.5")


def test_a_preview_of_a_bound_session_assembles_against_the_bound_runtime(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    """`context.preview` shows what *would* be sent, so it must see the binding too."""
    service = ConversationService(ctx)
    session = bound_session(service, runtime="codex", model="gpt-5.5")

    _, assembled = service.preview(session, "What does Table 3 say?", persist=False)

    profile = assembled.profile
    assert (profile.provider, profile.model) == ("session:codex", "gpt-5.5")
    assert profile.egress is EgressClass.EXTERNAL
    assert codex.runs() == [], "a preview sends nothing"


def test_a_configured_entry_may_not_impersonate_the_session_label(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    """`session:<runtime>` is the binding's name; a hand-written entry never answers for it.

    Neither by taking the name nor by wearing it as a tag: `session:` is reserved, and a
    foreign entry that claims it -- at the session entry's own priority, where a stable
    sort would let the earlier declaration win, or above it -- is still not the binding.
    """
    ctx.repo.update_providers(
        [
            {
                "name": "session:codex",
                "kind": "local_cli",
                "runtime": "codex",
                "model": "gpt-5.4-mini",
                "priority": 0,
            },
            {
                "name": "tie",
                "kind": "openai",
                "model": "gpt-4o",
                "api_key_env": "OPENAI_API_KEY",
                "priority": 0,
                "tags": ["session:codex"],
            },
            {
                "name": "outranks",
                "kind": "openai",
                "model": "gpt-4o",
                "api_key_env": "OPENAI_API_KEY",
                "priority": -1,
                "tags": ["session:codex"],
            },
        ]
    )
    service = ConversationService(ctx)
    session = bound_session(service, runtime="codex", model="gpt-5.5")

    service.send(session, "hello", background=False)

    (run,) = codex.runs()
    assert "gpt-5.5" in run["argv"] and "gpt-5.4-mini" not in run["argv"]
    answer = last_assistant(service, session)
    assert answer.attempt.status is AttemptStatus.COMPLETE
    assert answer.model is not None
    assert (answer.model.provider, answer.model.model) == ("session:codex", "gpt-5.5")


def test_a_record_written_before_bindings_sends_through_the_project_default(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    """An old `create --model openai/gpt-4` record bound nothing then, and binds nothing now.

    `defaults.model` was write-only before this branch. Reading its provider half as an
    entry name would refuse every send of such a session with "no provider named 'gpt-4'",
    so a shape that is neither `entry` nor `local_cli:<runtime>` is no binding (spec §15).
    """
    ctx.repo.update_providers(
        [{"name": "house", "kind": "local_cli", "runtime": "codex", "model": "gpt-5.5"}]
    )
    service = ConversationService(ctx)
    session = service.create("Latency study", visibility=Visibility.PROJECT).id
    ConversationStore.for_repository(ctx.repo).update_session(
        session, defaults=SessionDefaults(model=ModelIdentity(provider="openai", model="gpt-4"))
    )

    service.send(session, "hello", background=False)

    (run,) = codex.runs()
    assert "gpt-5.5" in run["argv"]
    answer = last_assistant(service, session)
    assert answer.attempt.status is AttemptStatus.COMPLETE
    assert answer.model is not None
    assert (answer.model.provider, answer.model.model) == ("local_cli:codex", "gpt-5.5")


def test_a_per_message_model_wins_over_the_binding(ctx: CapabilityContext, codex: FakeCli) -> None:
    ctx.repo.update_providers(
        [{"name": "codex-sub", "kind": "local_cli", "runtime": "codex", "model": "gpt-5.4-mini"}]
    )
    service = ConversationService(ctx)
    session = bound_session(service, runtime="codex", model="gpt-5.5")

    service.send(session, "hello", model="codex-sub", background=False)

    (run,) = codex.runs()
    assert "gpt-5.4-mini" in run["argv"] and "gpt-5.5" not in run["argv"]
    answer = last_assistant(service, session)
    assert answer.model is not None
    assert answer.model.provider == "local_cli:codex"


def test_a_bound_runtime_that_is_logged_out_is_refused_before_any_run(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = bound_session(service, runtime="codex", model="gpt-5.5")
    codex.write_script(
        {
            **codex.script(),
            "probes": [
                {"args": ["login", "status"], "stdout": "Not logged in\n", "exit": 1},
                *[p for p in codex.script()["probes"] if p["args"] != ["login", "status"]],
            ],
        }
    )
    DEFAULT_CACHE.clear()

    started = service.send(session, "hello", background=False)

    # The gate lives in the adapter, so the send records a failed attempt rather than
    # raising: the transcript keeps the question and one failure, and nothing was spawned.
    answer = last_assistant(service, session)
    assert answer.attempt.status is AttemptStatus.FAILED
    assert "codex is not logged in" in (answer.attempt.error or "")
    codes = [payload["code"] for name, payload in service.events(started.run_id) if name == "error"]
    assert codes == ["provider_auth_failed"]
    assert codex.runs() == []


def test_the_policy_refuses_a_bound_session_before_any_spawn(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = bound_session(service, runtime="codex", model="gpt-5.5")
    ctx.repo.update_config(EgressPolicy(external_models="disabled"))

    with pytest.raises(EgressDeniedError, match="external"):
        service.send(session, "hello", background=False)
    assert codex.runs() == []


def test_an_entry_binding_to_a_removed_entry_fails_like_a_stale_name(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    ctx.repo.update_providers(
        [{"name": "codex-sub", "kind": "local_cli", "runtime": "codex", "model": "gpt-5.5"}]
    )
    service = ConversationService(ctx)
    session = bound_session(service, entry="codex-sub")
    ctx.repo.update_providers([])

    with pytest.raises(CapabilityError, match="no provider named 'codex-sub'"):
        service.send(session, "hello", background=False)
    assert codex.runs() == []


def test_a_retry_follows_the_binding_at_retry_time(ctx: CapabilityContext, codex: FakeCli) -> None:
    service = ConversationService(ctx)
    session = bound_session(service, runtime="codex", model="gpt-5.4-mini")
    healthy = codex.script()["run"]
    codex.write_script({**codex.script(), "run": {"lines": [], "exit": 1}})
    service.send(session, "hello", background=False)
    failed = last_assistant(service, session)
    assert failed.model is not None
    assert failed.model.model == "gpt-5.4-mini"

    service.configure(session, runtime="codex", model="gpt-5.5")
    codex.write_script({**codex.script(), "run": healthy})
    service.retry(failed.id, background=False)

    assert "gpt-5.5" in codex.runs()[-1]["argv"]
    answered = last_assistant(service, session)
    assert answered.attempt.status is AttemptStatus.COMPLETE
    assert answered.model is not None
    assert (answered.model.provider, answered.model.model) == ("session:codex", "gpt-5.5")
