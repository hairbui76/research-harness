"""A bound session routes like an entry and is refused like one (binding spec §9)."""

from __future__ import annotations

from typing import Any

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.conversation.service import ConversationService
from research_harness.domain.conversation import (
    AttemptStatus,
    Message,
    MessageRole,
    Visibility,
)
from research_harness.domain.errors import CapabilityError
from research_harness.domain.ids import ConversationSessionId
from research_harness.providers.cli.detection import DEFAULT_CACHE
from tests.fixtures.cli.fakes import FakeCli


def last_assistant(service: ConversationService, session: ConversationSessionId) -> Message:
    page = service.transcript(session, limit=500)
    return [message for message in page.messages if message.role is MessageRole.ASSISTANT][-1]


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
    from research_harness.privacy.policy import EgressPolicy

    service = ConversationService(ctx)
    session = bound_session(service, runtime="codex", model="gpt-5.5")
    ctx.repo.update_config(EgressPolicy(external_models="disabled"))

    with pytest.raises(Exception, match="external"):
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
