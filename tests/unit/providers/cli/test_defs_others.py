"""The five remaining definitions: ported flags, honest postures (spec §9, §12, §21)."""

from __future__ import annotations

import json
from pathlib import Path

from research_harness.providers.cli.defs.amp import AMP, amp_args
from research_harness.providers.cli.defs.cursor_agent import (
    CURSOR_AGENT,
    cursor_args,
    cursor_auth,
    parse_cursor_models,
)
from research_harness.providers.cli.defs.deepseek_harness import (
    DEEPSEEK_HARNESS,
    dsh_args,
    dsh_probe_version,
    parse_dsh_models,
    parse_dsh_semver,
)
from research_harness.providers.cli.defs.opencode import (
    OPENCODE,
    opencode_args,
    parse_opencode_models,
)
from research_harness.providers.cli.defs.pi import PI, parse_pi_models, pi_args
from research_harness.providers.cli.registry import (
    FORBIDDEN_ARGS,
    RUNTIME_IDS,
    RUNTIMES,
    validate_definition,
)
from research_harness.providers.cli.types import UNKNOWN_EXTERNAL_HOST, CliInvocation, ProbeOutcome

PROBES = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "cli" / "probes"
CWD = Path("/tmp/rh-cli-x")


def outcome(name: str, exit_code: int = 0) -> ProbeOutcome:
    return ProbeOutcome(
        argv=("x",),
        exit_code=exit_code,
        stdout=(PROBES / name).read_text(encoding="utf-8"),
        stderr="",
    )


def invocation(model: str | None = None, reasoning: str | None = None) -> CliInvocation:
    return CliInvocation(model=model, reasoning=reasoning, cwd=CWD, request_id="req-1")


def test_all_seven_runtimes_are_registered_in_display_order() -> None:
    assert RUNTIME_IDS == (
        "codex",
        "claude",
        "cursor-agent",
        "amp",
        "deepseek-harness",
        "opencode",
        "pi",
    )
    for item in RUNTIMES.values():
        validate_definition(item)
        assert item.upstream_source.startswith("open-design@9bb4a7d")


def test_every_ported_argv_is_free_of_bypass_flags() -> None:
    for build in (cursor_args, amp_args, dsh_args, opencode_args, pi_args):
        for args in (build(invocation()), build(invocation(model="m", reasoning="high"))):
            assert not FORBIDDEN_ARGS & set(args), (build.__name__, args)


def test_none_of_the_five_claims_a_known_destination() -> None:
    for item in (CURSOR_AGENT, AMP, DEEPSEEK_HARNESS, OPENCODE, PI):
        assert item.egress == "unknown_external" and item.egress_host == UNKNOWN_EXTERNAL_HOST


# -- cursor agent --------------------------------------------------------------


def test_cursor_argv_and_probes() -> None:
    args = cursor_args(invocation(model="sonnet-4"))
    assert (
        args[:3] == ("--print", "--output-format", "stream-json")
        and "--stream-partial-output" in args
    )
    assert args[args.index("--workspace") : args.index("--workspace") + 2] == (
        "--workspace",
        str(CWD),
    )
    assert args[-2:] == ("--model", "sonnet-4")
    assert "--force" not in args and "--trust" not in args
    assert cursor_auth(outcome("cursor-status-ok.txt")) == ("ok", "")
    assert cursor_auth(outcome("cursor-status-missing.txt", exit_code=1))[0] == "missing"
    assert [m.id for m in parse_cursor_models(outcome("cursor-models.txt")) or ()] == [
        "auto",
        "sonnet-4",
        "gpt-5",
    ]
    assert (
        parse_cursor_models(
            ProbeOutcome(
                argv=("x",), exit_code=0, stdout="No models available for this account.", stderr=""
            )
        )
        is None
    )
    assert CURSOR_AGENT.posture.kind == "none", "no documented deny flag; never routed"


# -- amp -----------------------------------------------------------------------


def test_amp_argv_selects_a_mode_not_a_model() -> None:
    assert amp_args(invocation()) == ("-x", "--stream-json")
    assert amp_args(invocation(model="deep")) == ("-x", "--stream-json", "--mode", "deep")
    assert amp_args(invocation(model="not-a-mode")) == ("-x", "--stream-json")
    assert "--dangerously-allow-all" not in amp_args(invocation())
    assert AMP.posture.kind == "none" and AMP.protocol == "claude_stream" and AMP.auth_probe is None


# -- deepseek harness ----------------------------------------------------------


def test_dsh_argv_probes_and_version_policy() -> None:
    assert dsh_args(invocation(model="deepseek/deepseek-v3", reasoning="high")) == (
        "--profile",
        "open-design",
        "--stdio",
    )
    assert (
        parse_dsh_semver(ProbeOutcome(argv=("x",), exit_code=0, stdout="v0.1.1-rc.2\n", stderr=""))
        == "0.1.1-rc.2"
    )
    assert (
        parse_dsh_semver(ProbeOutcome(argv=("x",), exit_code=0, stdout="dsh 0.1.1\n", stderr=""))
        is None
    )
    assert dsh_probe_version(outcome("dsh-probe.jsonl")) == ("ok", "")
    assert (
        dsh_probe_version(
            ProbeOutcome(argv=("x",), exit_code=1, stdout="", stderr="profile not installed")
        )[0]
        == "unknown"
    )
    models = parse_dsh_models(outcome("dsh-models.jsonl"))
    assert (
        models is not None
        and models[0].id == "deepseek/deepseek-v3"
        and models[0].reasoning == ("low", "high")
    )
    assert DEEPSEEK_HARNESS.reasoning_choices == ("low", "medium", "high")
    assert DEEPSEEK_HARNESS.posture.kind == "none" and DEEPSEEK_HARNESS.transport == "dsh_profile"
    assert DEEPSEEK_HARNESS.minimum_version == "0.1.0" and "DSH_HOME" in DEEPSEEK_HARNESS.env_keep


# -- opencode ------------------------------------------------------------------


def test_opencode_argv_env_and_models() -> None:
    args = opencode_args(invocation(model="openai/gpt-5"))
    assert args[:3] == ("run", "--format", "json") and args[3:5] == ("--dir", str(CWD))
    assert args[-2:] == ("-m", "openai/gpt-5") and "--variant" not in args
    assert "--dangerously-skip-permissions" not in args
    permission = json.loads(OPENCODE.env_set["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert permission == {"edit": "deny", "bash": "deny", "webfetch": "deny"}
    assert OPENCODE.env_set["OPENCODE_DISABLE_PROJECT_CONFIG"] == "true"
    assert "OPENCODE_CONFIG" in OPENCODE.env_drop and OPENCODE.env_keep == ()
    assert OPENCODE.posture.kind == "native_env" and OPENCODE.posture.required_help_flags == (
        "--format",
        "--dir",
    )
    models = parse_opencode_models(outcome("opencode-models-verbose.txt"))
    assert models is not None and [m.id for m in models] == [
        "anthropic/claude-sonnet-4-5",
        "openai/gpt-5",
    ]
    assert models[0].reasoning == ("low", "high") and OPENCODE.fallback_executables == ("opencode",)


# -- pi ------------------------------------------------------------------------


def test_pi_argv_and_models() -> None:
    assert pi_args(invocation()) == ("--mode", "rpc")
    assert pi_args(invocation(model="anthropic/claude-sonnet-4-5", reasoning="high")) == (
        "--mode",
        "rpc",
        "--model",
        "anthropic/claude-sonnet-4-5",
        "--thinking",
        "high",
    )
    models = parse_pi_models(outcome("pi-list-models.txt"))
    assert models is not None and [m.id for m in models] == [
        "anthropic/claude-sonnet-4-5",
        "openai/gpt-5",
    ]
    assert parse_pi_models(ProbeOutcome(argv=("x",), exit_code=0, stdout="", stderr="")) is None
    assert PI.posture.kind == "none" and PI.version_probe.timeout_seconds == 15.0
    assert PI.reasoning_choices == ("minimal", "low", "medium", "high", "xhigh")
