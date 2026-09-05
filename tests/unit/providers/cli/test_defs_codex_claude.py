"""The Codex CLI and Claude Code definitions are bounded, complete, and honest (spec §9)."""

from __future__ import annotations

import json
from pathlib import Path

from research_harness.providers.cli.defs.claude import CLAUDE, claude_args, claude_auth
from research_harness.providers.cli.defs.codex import (
    CODEX,
    codex_args,
    codex_auth,
    parse_codex_models,
)
from research_harness.providers.cli.registry import FORBIDDEN_ARGS, RUNTIMES, validate_definition
from research_harness.providers.cli.types import CliInvocation, ProbeOutcome

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
    return CliInvocation(
        model=model,
        reasoning=reasoning,
        cwd=CWD,
        request_id="req-1",
        schema_path=CWD / "response.schema.json",
    )


def test_both_definitions_are_registered_and_valid() -> None:
    assert RUNTIMES["codex"] is CODEX and RUNTIMES["claude"] is CLAUDE
    validate_definition(CODEX)
    validate_definition(CLAUDE)


# -- codex ---------------------------------------------------------------------


def test_codex_argv_is_read_only_never_approves_and_delivers_the_schema_by_file() -> None:
    args = codex_args(invocation(model="gpt-5.5", reasoning="high"))
    assert args[:2] == ("exec", "--json")
    assert args[args.index("--sandbox") : args.index("--sandbox") + 2] == ("--sandbox", "read-only")
    assert 'approval_policy="never"' in args
    assert "--ephemeral" in args and "--skip-git-repo-check" in args
    assert "--ignore-user-config" in args
    assert args[args.index("-C") : args.index("-C") + 2] == ("-C", str(CWD))
    schema_at = args.index("--output-schema")
    schema = str(CWD / "response.schema.json")
    assert args[schema_at : schema_at + 2] == ("--output-schema", schema)
    assert args[args.index("--model") : args.index("--model") + 2] == ("--model", "gpt-5.5")
    assert 'model_reasoning_effort="high"' in args
    assert not FORBIDDEN_ARGS & set(args)


def test_codex_default_model_sends_no_model_flag_and_no_schema_without_a_path() -> None:
    args = codex_args(CliInvocation(model=None, reasoning=None, cwd=Path("/tmp/x"), request_id="r"))
    assert "--model" not in args
    assert "--output-schema" not in args
    assert "model_reasoning_effort" not in " ".join(args)


def test_codex_login_status_classifies_both_ways() -> None:
    assert codex_auth(outcome("codex-login-status-ok.txt")) == ("ok", "")
    assert codex_auth(outcome("codex-login-status-missing.txt", exit_code=1)) == (
        "missing",
        "run `codex login`",
    )
    surprising = ProbeOutcome(argv=("x",), exit_code=3, stdout="", stderr="unexpected")
    assert codex_auth(surprising)[0] == "unknown"


def test_codex_api_key_login_is_not_a_subscription_and_is_not_routable() -> None:
    status, guidance = codex_auth(outcome("codex-login-status-apikey.txt"))
    assert status == "missing", "an API-key login is metered; it is not the ChatGPT subscription"
    assert "API key" in guidance and "api.openai.com" in guidance
    # a login that does not name ChatGPT is never silently accepted
    plain = ProbeOutcome(argv=("x",), exit_code=0, stdout="Logged in\n", stderr="")
    assert codex_auth(plain)[0] != "ok"


def test_codex_debug_models_lists_only_visible_models_with_their_efforts() -> None:
    models = parse_codex_models(outcome("codex-debug-models.json"))
    assert models is not None
    assert [item.id for item in models] == ["gpt-5.5", "gpt-5.4-mini"]
    assert models[0].reasoning == ("low", "medium", "high", "xhigh")
    assert models[0].context_tokens == 272000
    not_json = ProbeOutcome(argv=("x",), exit_code=0, stdout="not json", stderr="")
    assert parse_codex_models(not_json) is None


def test_codex_posture_is_proven_by_the_real_help_text() -> None:
    text = (PROBES / "codex-exec-help.txt").read_text(encoding="utf-8")
    assert all(flag in text for flag in CODEX.posture.required_help_flags)
    assert CODEX.posture.help_probe is not None
    assert CODEX.posture.help_probe.args == ("exec", "--help")
    version = CODEX.parse_version(
        ProbeOutcome(argv=("x",), exit_code=0, stdout="codex-cli 0.150.1\n", stderr="")
    )
    assert version == "0.150.1"
    assert CODEX.egress == "external" and CODEX.egress_host == "chatgpt.com"
    assert "OPENAI_API_KEY" not in CODEX.env_keep and "CODEX_HOME" in CODEX.env_keep
    assert "0.150.1" in CODEX.verified_versions


# -- claude --------------------------------------------------------------------


def test_claude_argv_disables_every_tool_and_denies_every_prompt() -> None:
    args = claude_args(invocation(model="opus"))
    assert args[0] == "-p"
    assert args[args.index("--tools") : args.index("--tools") + 2] == ("--tools", "")
    mode_at = args.index("--permission-mode")
    assert args[mode_at : mode_at + 2] == ("--permission-mode", "dontAsk")
    prompts_at = args.index("--permission-prompts")
    assert args[prompts_at : prompts_at + 2] == ("--permission-prompts", "none")
    for flag in ("--input-format", "--output-format"):
        assert args[args.index(flag) + 1] == "stream-json"
    assert "--include-partial-messages" in args and "--strict-mcp-config" in args
    assert "--no-session-persistence" in args and "--disable-slash-commands" in args
    assert "--restricted" in args, "restricted mode backs the empty --tools list up"
    assert args[args.index("--model") : args.index("--model") + 2] == ("--model", "opus")
    assert "--bare" not in args, "--bare never reads OAuth and would break the subscription login"
    assert "--output-schema" not in " ".join(args)
    assert not FORBIDDEN_ARGS & set(args)


def test_claude_routes_reasoning_through_the_effort_flag() -> None:
    args = claude_args(invocation(model="opus", reasoning="high"))
    effort_at = args.index("--effort")
    assert args[effort_at : effort_at + 2] == ("--effort", "high")
    assert CLAUDE.reasoning_choices == ("low", "medium", "high", "xhigh", "max")
    assert not FORBIDDEN_ARGS & set(args)
    assert "--effort" not in claude_args(invocation(model="opus"))


def test_claude_auth_status_reads_the_json_and_falls_back_to_text() -> None:
    assert claude_auth(outcome("claude-auth-status-ok.json")) == ("ok", "")
    assert claude_auth(outcome("claude-auth-status-missing.json")) == (
        "missing",
        "run `claude auth login`",
    )
    logged_out = ProbeOutcome(
        argv=("x",), exit_code=1, stdout="", stderr="Not logged in · Please run /login"
    )
    assert claude_auth(logged_out)[0] == "missing"
    assert claude_auth(ProbeOutcome(argv=("x",), exit_code=1, stdout="", stderr="garbage"))[0] == (
        "unknown"
    )


def test_claude_auth_reads_the_json_behind_a_banner_and_never_guesses_ok() -> None:
    """A banner must not downgrade a real subscription, and text must not promote a login.

    `claude auth status` prints its object after whatever the CLI decided to say first.
    Parsing only the whole stream would fail on that and fall to a text match — which can
    see "logged in" and can never see *how*, and only a Claude.ai login is routable here.
    """
    banner = "Claude Code 2.1.259\nChecking credentials…\n"

    def status(stdout: str) -> tuple[str, str]:
        return claude_auth(ProbeOutcome(argv=("x",), exit_code=0, stdout=stdout, stderr=""))

    assert status(banner + json.dumps({"loggedIn": True, "authMethod": "claude.ai"})) == ("ok", "")
    verdict, guidance = status(banner + json.dumps({"loggedIn": True, "authMethod": "console"}))
    assert verdict == "missing" and "console" in guidance
    assert status(banner + json.dumps({"loggedIn": False, "authMethod": None}))[0] == "missing"

    # a JSON-shaped preamble (an update notice) must not shadow the status object
    preamble = '{"update":{"available":false,"latest":"2.1.259"}}\n'
    subscription = json.dumps({"loggedIn": True, "authMethod": "claude.ai"})
    assert status(banner + preamble + subscription) == ("ok", "")
    assert status(preamble + json.dumps({"loggedIn": True, "authMethod": "console"}))[0] == (
        "missing"
    )

    for unparseable in ('Logged in\n"loggedIn": true', '"authenticated": true', "Logged in."):
        assert status(unparseable)[0] == "unknown", "text alone never proves a subscription"
    assert status('Logged in\n"loggedIn": true')[1] == "run `claude auth status`"


def test_claude_non_subscription_login_is_not_routable() -> None:
    status, guidance = claude_auth(outcome("claude-auth-status-console.json"))
    assert status == "missing", "a console login is metered; it is not a Claude.ai subscription"
    assert "console" in guidance and "Claude.ai" in guidance


def test_claude_posture_is_proven_by_the_real_help_text() -> None:
    text = (PROBES / "claude-help.txt").read_text(encoding="utf-8")
    assert all(flag in text for flag in CLAUDE.posture.required_help_flags)
    # flags the posture and reasoning ride on must stay required, or an older build is sent
    # them blind
    assert "--effort" in CLAUDE.posture.required_help_flags
    assert "--restricted" in CLAUDE.posture.required_help_flags
    assert "--restricted" in text
    version = CLAUDE.parse_version(
        ProbeOutcome(argv=("x",), exit_code=0, stdout="2.1.259 (Claude Code)\n", stderr="")
    )
    assert version == "2.1.259"
    assert CLAUDE.transport == "stdin_jsonl" and CLAUDE.protocol == "claude_stream"
    assert CLAUDE.egress_host == "api.anthropic.com"
    assert CLAUDE.fallback_executables == ("openclaude",)
    assert CLAUDE.model_probe is None
    assert [m.id for m in CLAUDE.fallback_models][:3] == ["sonnet", "opus", "haiku"]
    assert "ANTHROPIC_API_KEY" not in CLAUDE.env_keep and "CLAUDE_CONFIG_DIR" in CLAUDE.env_keep


def test_upstream_provenance_is_recorded_on_both() -> None:
    for item in (CODEX, CLAUDE):
        assert item.upstream_source.startswith("open-design@9bb4a7d")
        assert json.dumps(item.upstream_source)
