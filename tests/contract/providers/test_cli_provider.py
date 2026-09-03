"""A CLI-backed provider honours the same contract as every HTTP adapter (spec §20).

Driven entirely through fake executables: the real `codex` definition is used, but the
`codex` on PATH is `tests/fixtures/cli/fakes.py` replaying the sanitized event fixtures.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from research_harness.privacy.policy import EgressPolicy
from research_harness.providers.cli.detection import DEFAULT_CACHE, detect
from research_harness.providers.cli.errors import (
    CliAuthError,
    CliResponseError,
    CliTransportError,
)
from research_harness.providers.cli.provider import CliModelProvider, default_cli_capabilities
from research_harness.providers.cli.registry import RUNTIMES
from research_harness.providers.models.base import ModelRequest, StructuredOutputError
from research_harness.providers.models.router import (
    RouterConfig,
    RouterProviderConfig,
    build_router,
)
from research_harness.providers.models.streaming import chat_request, streaming_provider
from tests.contract.providers.conftest import CANONICAL_JSON, EXPECTED_VERDICT, Verdict
from tests.fixtures.cli.fakes import FakeCli

STREAMS = Path(__file__).resolve().parents[2] / "fixtures" / "cli" / "streams"

CODEX_HELP = (
    "--sandbox --output-schema --json --ephemeral "
    "--skip-git-repo-check --ignore-user-config --ignore-rules"
)
"""Every flag `codex`'s posture requires, so the run-time gate proves the bounded mode."""

CLAUDE_PROBES: list[dict[str, object]] = [
    {
        "args": ["auth", "status"],
        "stdout": json.dumps({"loggedIn": True, "authMethod": "claude.ai"}),
    },
    {"args": ["--help"], "stdout": " ".join(RUNTIMES["claude"].posture.required_help_flags)},
]
"""A logged-in Claude Code whose help output proves the posture the definition needs."""


def lines(name: str) -> list[str]:
    return [
        line
        for line in (STREAMS / name).read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]


@pytest.fixture
def codex(tmp_path: Path) -> FakeCli:
    return FakeCli.install(
        tmp_path,
        "codex",
        version_stdout="codex-cli 0.150.1",
        probes=[
            {"args": ["login", "status"], "stdout": "Logged in using ChatGPT\n"},
            {
                "args": ["exec", "--help"],
                "stdout": CODEX_HELP,
            },
            {"args": ["debug", "models"], "stdout": "{}"},
        ],
        run={"lines": lines("codex-success.jsonl")},
    )


def provider(codex: FakeCli, **kwargs: object) -> CliModelProvider:
    env = codex.env(
        {
            "PATH": "",
            "HOME": str(codex.root / "home"),
            "OPENAI_API_KEY": "sk-metered",
            "CODEX_HOME": str(codex.root / "home" / ".codex"),
        }
    )
    return CliModelProvider("codex", "gpt-5.5", env=env, timeout=10, **kwargs)  # type: ignore[arg-type]


# -- the contract --------------------------------------------------------------


def test_the_same_request_yields_the_same_validated_object(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    response = provider(codex).complete(model_request)

    assert response.parsed == EXPECTED_VERDICT
    assert response.provider == "local_cli:codex" and response.model == "gpt-5.5"
    assert response.request_fingerprint == model_request.fingerprint()
    assert response.usage.input_tokens == 1200 and response.usage.output_tokens == 95
    assert response.usage.cached_input_tokens == 400 and response.usage.reasoning_tokens == 64
    assert response.raw_text == CANONICAL_JSON


def test_research_content_travels_on_stdin_never_argv(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    provider(codex).complete(model_request)
    run = codex.runs()[0]

    assert "work:0a1b2c" in run["stdin"] and "Table 3 reports" in run["stdin"]
    assert not any("Table 3" in arg or "work:0a1b2c" in arg for arg in run["argv"])
    assert "--sandbox" in run["argv"] and "read-only" in run["argv"]
    schema = run["argv"][run["argv"].index("--output-schema") + 1]
    assert schema.startswith(run["cwd"]) and os.path.basename(schema) == "response.schema.json"


def test_the_process_runs_in_an_empty_temp_cwd_that_is_removed_afterwards(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    provider(codex).complete(model_request)
    run = codex.runs()[0]

    assert os.path.basename(run["cwd"]).startswith("rh-cli-")
    assert not os.path.exists(run["cwd"]), "the temp cwd is deleted in finally"
    assert run["cwd"] != os.getcwd()


def test_the_child_environment_keeps_the_login_and_drops_the_api_key(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    provider(codex).complete(model_request)
    env = codex.runs()[0]["env"]

    assert "OPENAI_API_KEY" not in env and env["CODEX_HOME"].endswith(".codex")
    assert env["NO_COLOR"] == "1" and env["RESEARCH_HARNESS_BOUNDED"] == "1"


def test_invalid_json_fails_through_the_shared_structured_output_path(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    codex.set_run(
        lines=[
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "i", "type": "agent_message", "text": "not json"},
                }
            ),
            json.dumps(
                {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}
            ),
        ]
    )
    with pytest.raises(StructuredOutputError) as caught:
        provider(codex).complete(model_request)
    assert caught.value.raw_text == "not json"


def test_a_schema_violation_never_returns_a_partial_object(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    codex.set_run(
        lines=[
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "i", "type": "agent_message", "text": '{"supported": true}'},
                }
            ),
            json.dumps({"type": "turn.completed", "usage": {}}),
        ]
    )
    with pytest.raises(StructuredOutputError):
        provider(codex).complete(model_request)


def test_a_tool_event_cancels_the_process_and_is_a_bounded_authority_violation(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    codex.set_run(lines=[*lines("codex-tool.jsonl"), {"sleep": 30}], hang=True)
    with pytest.raises(CliResponseError) as caught:
        provider(codex).complete(model_request)
    assert caught.value.diagnostic == "bounded_authority_violation"
    assert "command_execution" in caught.value.message


def test_a_missing_terminal_event_is_a_transport_failure_even_with_text(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    codex.set_run(lines=lines("codex-success.jsonl")[:-1])
    with pytest.raises(CliTransportError) as caught:
        provider(codex).complete(model_request)
    assert caught.value.diagnostic == "missing_terminal_event"


def test_a_timeout_terminates_the_tree(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    codex.set_run(lines=['{"type":"thread.started","thread_id":"t"}'], hang=True)
    with pytest.raises(CliTransportError) as caught:
        CliModelProvider("codex", "gpt-5.5", env=codex.env({"PATH": ""}), timeout=1).complete(
            model_request
        )
    assert caught.value.diagnostic == "timeout"


def test_an_empty_answer_is_a_response_error(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    codex.set_run(lines=[json.dumps({"type": "turn.completed", "usage": {}})])
    with pytest.raises(CliResponseError) as caught:
        provider(codex).complete(model_request)
    assert caught.value.diagnostic == "empty_response"


def test_a_failed_turn_is_classified_from_the_stream(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    codex.set_run(lines=lines("codex-failed.jsonl"))
    with pytest.raises(CliResponseError) as caught:
        provider(codex).complete(model_request)
    assert caught.value.diagnostic == "unsupported_model"


def test_a_missing_executable_is_a_transport_error(
    tmp_path: Path, model_request: ModelRequest[Verdict]
) -> None:
    with pytest.raises(CliTransportError) as caught:
        CliModelProvider("codex", "gpt-5.5", env={"PATH": str(tmp_path)}).complete(model_request)
    assert caught.value.diagnostic == "executable_missing"


def test_media_inputs_are_refused_before_anything_is_spawned(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    from research_harness.providers.models.media import MediaPart

    request = model_request.model_copy(
        update={
            "inputs": [
                *model_request.inputs,
                model_request.inputs[0].model_copy(
                    update={"media": MediaPart(media_type="image/png", data=b"x", filename="x.png")}
                ),
            ]
        }
    )
    with pytest.raises(CliResponseError) as caught:
        provider(codex).complete(request)
    assert caught.value.diagnostic == "invalid_invocation" and codex.runs() == []


# -- capabilities and egress ---------------------------------------------------


def test_capabilities_are_external_text_only_and_structured() -> None:
    caps = default_cli_capabilities(RUNTIMES["codex"], "gpt-5.5")
    assert caps.structured_output and caps.max_context_tokens == 272_000
    assert (
        caps.reasoning_levels == {"low", "medium", "high"}
        and not caps.vision
        and caps.input_media == frozenset()
    )
    assert (
        caps.egress.endpoint_host == "chatgpt.com"
        and caps.egress.sends_source_text
        and caps.egress.sends_identifiers
    )
    assert "leaves this workstation" in caps.egress.description


def test_the_privacy_policy_refuses_before_any_process_is_spawned(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    from research_harness.privacy.policy import EgressDeniedError

    config = RouterConfig.model_validate(
        {
            "providers": [
                {"name": "codex-sub", "kind": "local_cli", "runtime": "codex", "model": "gpt-5.5"}
            ]
        }
    )
    router = build_router(
        config, codex.env({"PATH": ""}), policy=EgressPolicy(external_models="disabled")
    )
    with pytest.raises(EgressDeniedError):
        router.complete(model_request)
    assert codex.calls() == []


def test_the_router_builds_a_cli_provider_from_configuration(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    config = RouterConfig.model_validate(
        {
            "providers": [
                {
                    "name": "codex-sub",
                    "kind": "local_cli",
                    "runtime": "codex",
                    "model": "gpt-5.5",
                    "reasoning": "high",
                    "timeout_seconds": 20,
                }
            ]
        }
    )
    router = build_router(config, codex.env({"PATH": ""}))
    response = router.complete(model_request)
    assert response.parsed == EXPECTED_VERDICT and response.provider == "local_cli:codex"
    assert 'model_reasoning_effort="high"' in codex.runs()[0]["argv"]
    assert "codex-sub" in router.entries[0].tags


# -- streaming -----------------------------------------------------------------


def test_a_chat_turn_streams_prose_deltas_that_concatenate_to_the_answer(tmp_path: Path) -> None:
    claude = FakeCli.install(
        tmp_path,
        "claude",
        version_stdout="2.1.259 (Claude Code)",
        probes=CLAUDE_PROBES,
        run={"lines": lines("claude-partial.jsonl")},
    )
    adapter = CliModelProvider("claude", "opus", env=claude.env({"PATH": ""}), timeout=10)
    request = chat_request(instructions="Summarise.", context_tokens=1000)

    deltas = list(streaming_provider(adapter, model="opus").stream(request))

    assert [d.text for d in deltas if not d.final] == [
        "Batching ",
        "reduces tail latency ",
        "across the pilot corpus.",
    ]
    assert (
        deltas[-1].final and deltas[-1].usage is not None and deltas[-1].usage.output_tokens == 41
    )
    assert deltas[-1].stop_reason == "end_turn" and deltas[-1].model == "opus"
    prompt = json.loads(claude.runs()[0]["stdin"])["message"]["content"][0]["text"]
    assert "Answer in plain prose" in prompt and "Response schema" not in prompt


def test_a_non_chat_schema_is_routed_back_through_the_validated_call(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    deltas = list(streaming_provider(provider(codex)).stream(model_request))
    assert len(deltas) == 1 and deltas[0].final and json.loads(deltas[0].text)["supported"] is True


def test_abandoning_the_stream_cancels_the_process(tmp_path: Path) -> None:
    claude = FakeCli.install(
        tmp_path,
        "claude",
        probes=CLAUDE_PROBES,
        run={"lines": [*lines("claude-partial.jsonl")[:4], {"sleep": 30}], "hang": True},
    )
    adapter = CliModelProvider("claude", "opus", env=claude.env({"PATH": ""}), timeout=30)
    stream = adapter.stream(chat_request(instructions="x", context_tokens=100))
    first = next(stream)
    stream.close()
    assert first.text == "Batching "
    assert adapter.last_process is not None and not adapter.last_process.running


def test_abandoning_the_stream_through_the_wrapper_also_cancels_the_process(
    tmp_path: Path,
) -> None:
    """The wrapper is what a conversation turn actually holds (`conversation/send.py`).

    `streaming_provider` puts a `NativeStream` between the caller and the adapter, and a
    cancelled turn closes *that*; unless it closes the adapter's stream in turn, the
    subprocess outlives the turn until the garbage collector notices.
    """
    claude = FakeCli.install(
        tmp_path,
        "claude",
        probes=CLAUDE_PROBES,
        run={"lines": [*lines("claude-partial.jsonl")[:4], {"sleep": 30}], "hang": True},
    )
    adapter = CliModelProvider("claude", "opus", env=claude.env({"PATH": ""}), timeout=30)
    stream = streaming_provider(adapter, model="opus").stream(
        chat_request(instructions="x", context_tokens=100)
    )
    first = next(stream)
    stream.close()
    assert first.text == "Batching " and not first.final
    assert adapter.last_process is not None and not adapter.last_process.running


def test_the_trace_records_runtime_version_protocol_and_model(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    class Sink:
        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def record(
            self, kind: str, *, provider: str, model: str, request_fingerprint: str, payload: object
        ) -> None:
            self.payloads.append(dict(payload))  # type: ignore[call-overload]

    sink = Sink()
    provider(codex).complete(model_request, trace=sink)
    cli = sink.payloads[0]["cli"]
    assert isinstance(cli, dict)
    assert cli["runtime"] == "codex" and cli["protocol"] == "json_events"
    assert cli["transport"] == "stdin_text" and cli["model"] == "gpt-5.5"
    assert cli["version"] is None, "the provider never probes a version itself"
    assert isinstance(cli["executable"], str) and cli["executable"].endswith("bin/codex")
    assert "sk-metered" not in json.dumps(sink.payloads)


# -- the run-time gate ---------------------------------------------------------

UNPROVEN = ["pi", "amp", "cursor-agent", "deepseek-harness"]


@pytest.mark.parametrize("runtime", UNPROVEN)
def test_a_runtime_with_no_bounded_posture_cannot_be_configured_at_all(runtime: str) -> None:
    """Data only: a hand-written `research.yaml` fails at load, before anything is spawned."""
    with pytest.raises(ValidationError) as caught:
        RouterConfig.model_validate(
            {
                "providers": [
                    {"name": "x", "kind": "local_cli", "runtime": runtime, "model": "default"}
                ]
            }
        )
    message = str(caught.value)
    assert runtime in message and "no proven bounded" in message
    assert "cannot be configured" in message


def test_opencodes_declared_posture_loads_but_the_engine_refuses_it_at_run_time(
    tmp_path: Path, model_request: ModelRequest[Verdict]
) -> None:
    """The fifth non-routable runtime: it declares a posture, so only the live gate can judge.

    OpenCode's bounded mode is injected through the environment; a help probe can prove a
    flag exists and never that an injected table denies anything, so an unverified version
    leaves the posture unproven and the request is refused before a process is spawned.
    """
    RouterConfig.model_validate(
        {"providers": [{"name": "x", "kind": "local_cli", "runtime": "opencode", "model": "d"}]}
    )
    fake = FakeCli.install(
        tmp_path,
        "opencode-cli",
        probes=[
            {"args": ["run", "--help"], "stdout": "--format --dir"},
            {"args": ["models", "--verbose"], "stdout": ""},
        ],
        run={"lines": lines("opencode-success.jsonl")},
    )
    env = fake.env({"PATH": "", "HOME": str(fake.root / "home")})
    with pytest.raises(CliResponseError) as caught:
        CliModelProvider("opencode", env=env, timeout=10).complete(model_request)

    assert caught.value.diagnostic == "bounded_mode_unsupported"
    assert caught.value.message == detect(RUNTIMES["opencode"], env=env).unavailable_reason
    assert fake.runs() == []


def test_an_unproven_bounded_mode_is_refused_before_the_process_exists(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    """This build of `codex` no longer offers `--sandbox`, so nothing proves the posture."""
    DEFAULT_CACHE.clear()
    script = codex.script()
    script["probes"] = [
        probe if probe["args"] != ["exec", "--help"] else {**probe, "stdout": "--json --ephemeral"}
        for probe in script["probes"]
    ]
    codex.write_script(script)

    with pytest.raises(CliResponseError) as caught:
        provider(codex).complete(model_request)

    assert caught.value.diagnostic == "bounded_mode_unsupported"
    env = codex.env({"PATH": "", "HOME": str(codex.root / "home")})
    assert caught.value.message == detect(RUNTIMES["codex"], env=env).unavailable_reason
    assert "no tested bounded" in caught.value.message
    assert codex.runs() == []


def test_a_logged_out_runtime_is_refused_before_the_process_exists(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    DEFAULT_CACHE.clear()
    script = codex.script()
    script["probes"] = [
        probe
        if probe["args"] != ["login", "status"]
        else {**probe, "stdout": "Not logged in\n", "exit": 1}
        for probe in script["probes"]
    ]
    codex.write_script(script)

    with pytest.raises(CliAuthError) as caught:
        provider(codex).complete(model_request)

    assert caught.value.diagnostic == "login_missing"
    env = codex.env({"PATH": "", "HOME": str(codex.root / "home")})
    assert caught.value.message == detect(RUNTIMES["codex"], env=env).unavailable_reason
    assert codex.runs() == []


def test_a_routable_runtime_still_completes_and_spawns_exactly_one_run(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    """The gate is a gate, not a wall: a proven, logged-in runtime answers as before."""
    response = provider(codex).complete(model_request)

    assert response.parsed == EXPECTED_VERDICT
    assert [call["kind"] for call in codex.calls()].count("run") == 1


def test_the_gate_pays_at_most_one_probe_round_per_cache_window(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    """A second request inside the cache window re-uses the first request's detection."""
    DEFAULT_CACHE.clear()
    adapter = provider(codex)
    adapter.complete(model_request)
    probes = [call for call in codex.calls() if call["kind"] != "run"]
    adapter.complete(model_request)

    assert [call for call in codex.calls() if call["kind"] != "run"] == probes


# -- the run-time argv screen --------------------------------------------------


def test_a_poisoned_reasoning_value_never_reaches_a_spawn(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    """An effort name that smuggles a second `-c` override past a bypassed request validator.

    `model_construct` is how a configuration reaches the router without the validator that
    would refuse this; the registry's own argv screen, run again over the argv about to be
    spawned, is what stops it.
    """
    entry = RouterProviderConfig.model_construct(
        name="codex-sub",
        kind="local_cli",
        runtime="codex",
        model="gpt-5.5",
        reasoning='high"; sandbox_mode="danger-full-access',
    )
    router = build_router(RouterConfig.model_construct(providers=[entry]), codex.env({"PATH": ""}))

    with pytest.raises(CliResponseError) as caught:
        router.complete(model_request)

    assert caught.value.diagnostic == "invalid_invocation"
    assert "danger-full-access" not in str(codex.calls())
    assert codex.runs() == []


def test_an_ordinary_effort_name_still_reaches_the_runtime(
    codex: FakeCli, model_request: ModelRequest[Verdict]
) -> None:
    provider(codex, reasoning="high").complete(model_request)
    assert 'model_reasoning_effort="high"' in codex.runs()[0]["argv"]
