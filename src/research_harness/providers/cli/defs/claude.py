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


def _status_object(stdout: str) -> dict[str, object] | None:
    """The first `{...}` object in stdout that carries `loggedIn`, or `None` if there is none.

    `claude auth status` prints its object after whatever the build decided to say first --
    a version banner, an update notice, even another JSON line -- and `json.loads` over the
    whole stream fails on that. Scanning for *the status object* (not merely the first
    object) keeps a genuine subscription login readable instead of letting a preamble push
    it onto the text path, which cannot tell one login from another.
    """
    decoder = json.JSONDecoder()
    start = stdout.find("{")
    while start != -1:
        parsed: object
        try:
            parsed, end = decoder.raw_decode(stdout, start)
        except ValueError:
            start = stdout.find("{", start + 1)
            continue
        if isinstance(parsed, dict) and "loggedIn" in parsed:
            return parsed
        start = stdout.find("{", end)
    return None


def claude_auth(outcome: ProbeOutcome) -> tuple[AuthStatus, str]:
    """`ok` only for a parsed `authMethod` of `claude.ai`; unreadable output is `unknown`.

    The text path can see that *some* login exists and can never see which kind, and only a
    Claude.ai subscription is routable here (spec §12) -- an API-key or console login is
    metered access wearing the same words. So it may report `missing` on an explicit refusal
    and otherwise `unknown`; it may never report `ok`, because "logged in" is not evidence
    of the one login this definition accepts.
    """
    payload = _status_object(outcome.stdout)
    if payload is not None and isinstance(payload.get("loggedIn"), bool):
        if not payload["loggedIn"]:
            return "missing", "run `claude auth login`"
        method = payload.get("authMethod")
        if method == "claude.ai":
            return "ok", ""
        return "missing", (
            f"logged in without a Claude.ai subscription (authMethod {method}): "
            "run `claude auth login` with a Claude.ai account"
        )
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
        "--restricted",
    ]
    if invocation.model:
        args += ["--model", invocation.model]
    if invocation.reasoning:
        args += ["--effort", invocation.reasoning]
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
    reasoning_choices=("low", "medium", "high", "xhigh", "max"),
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
            "--effort",
            "--restricted",
        ),
        note=(
            "no tools at all, every prompt denied, no MCP servers, no session file, "
            "and --restricted as a second line of defence"
        ),
    ),
    egress="external",
    egress_host="api.anthropic.com",
    default_context_tokens=200_000,
    login_guidance="run `claude auth login`",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/claude.ts",
    verified_versions=("2.1.259",),
    env_keep=("CLAUDE_CONFIG_DIR",),
    notes=(
        "Reasoning routes through `--effort`, sent whenever the harness level names one of "
        "reasoning_choices (low, medium, high, xhigh, max in 2.1.259). The flag is required "
        "help output, so a build without it is reported unsupported rather than being sent "
        "an unknown flag. `--restricted` backs the empty --tools list up: it removes the "
        "command- and code-running tools outright, ignores user, project and local settings, "
        "and refuses bypassPermissions. Only a Claude.ai subscription counts as logged in: "
        "the environment drops the API-key variables (env_keep admits only CLAUDE_CONFIG_DIR) "
        "and claude_auth reports any other authMethod as not routable, so a metered "
        "console login is never used for research."
    ),
)
