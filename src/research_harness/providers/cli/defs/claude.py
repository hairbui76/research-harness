"""Claude Code (`claude`) as a bounded research worker (CLI providers spec §9).

Ported from open-design@9bb4a7d `apps/daemon/src/runtimes/defs/claude.ts` and compared
with Claude Code 2.1.259. Open Design passes `--permission-mode bypassPermissions`; this
definition disables every tool (`--tools ""`), denies every prompt (`dontAsk`,
`--permission-prompts none`), loads no MCP server, keeps no session, and never uses
`--bare`, which would refuse the OAuth login the subscription depends on.
"""

from __future__ import annotations

import json
import re

from research_harness.providers.cli.defs.codex import parse_semver
from research_harness.providers.cli.types import (
    AuthStatus,
    BoundedPosture,
    CliInvocation,
    CliModelOption,
    CliRuntimeDef,
    Probe,
    ProbeOutcome,
)

__all__ = ["CLAUDE", "claude_args", "claude_auth"]

_NOT_LOGGED_IN = re.compile(
    r"not logged[ _-]?in|please run /login|\"loggedIn\"\s*:\s*false", re.IGNORECASE
)
_LOGGED_IN = re.compile(r"\"loggedIn\"\s*:\s*true|\"authenticated\"\s*:\s*true", re.IGNORECASE)


def claude_auth(outcome: ProbeOutcome) -> tuple[AuthStatus, str]:
    try:
        payload = json.loads(outcome.stdout)
    except ValueError:
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("loggedIn"), bool):
        return ("ok", "") if payload["loggedIn"] else ("missing", "run `claude auth login`")
    if _LOGGED_IN.search(outcome.text):
        return "ok", ""
    if _NOT_LOGGED_IN.search(outcome.text):
        return "missing", "run `claude auth login`"
    return "unknown", "run `claude auth status`"


def claude_args(invocation: CliInvocation) -> tuple[str, ...]:
    args = [
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--tools",
        "",
        "--permission-mode",
        "dontAsk",
        "--permission-prompts",
        "none",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]
    if invocation.model:
        args += ["--model", invocation.model]
    return tuple(args)


CLAUDE = CliRuntimeDef(
    id="claude",
    name="Claude Code",
    executable="claude",
    fallback_executables=("openclaude",),
    version_probe=Probe(args=("--version",), timeout_seconds=3.0),
    parse_version=parse_semver,
    auth_probe=Probe(args=("auth", "status"), timeout_seconds=5.0),
    classify_auth=claude_auth,
    fallback_models=(
        CliModelOption(id="sonnet", label="Sonnet (alias)"),
        CliModelOption(id="opus", label="Opus (alias)"),
        CliModelOption(id="haiku", label="Haiku (alias)"),
        CliModelOption(id="claude-opus-5", label="claude-opus-5"),
        CliModelOption(id="claude-sonnet-5", label="claude-sonnet-5"),
        CliModelOption(id="claude-haiku-4-5", label="claude-haiku-4-5"),
    ),
    reasoning_choices=(),
    protocol="claude_stream",
    transport="stdin_jsonl",
    build_args=claude_args,
    posture=BoundedPosture(
        kind="native_flags",
        help_probe=Probe(args=("--help",), timeout_seconds=5.0),
        required_help_flags=(
            "--tools",
            "--permission-mode",
            "--permission-prompts",
            "--output-format",
            "--input-format",
            "--include-partial-messages",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--disable-slash-commands",
        ),
        note="no tools at all, every prompt denied, no MCP servers, no session file",
    ),
    egress="external",
    egress_host="api.anthropic.com",
    default_context_tokens=200_000,
    login_guidance="run `claude auth login`",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/claude.ts",
    verified_versions=("2.1.259",),
    env_keep=("CLAUDE_CONFIG_DIR",),
    notes=(
        "2.1.259 does expose `--effort <low|medium|high|xhigh|max>`, but this definition "
        "does not send it and declares no reasoning_choices, so a requested level only "
        "routes. Wiring it through is a deliberate follow-up, not an oversight."
    ),
)
