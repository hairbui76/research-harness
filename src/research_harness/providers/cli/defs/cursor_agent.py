"""Cursor Agent (`cursor-agent`) — detected, never routed (CLI providers spec §9, §12).

Ported from open-design@9bb4a7d `runtimes/defs/cursor-agent.ts`. Open Design runs it
headless with `--force` (and `--trust` when offered), which is exactly the approval bypass
a bounded worker may not use, and no version documents a deny-tools flag. The definition
keeps detection, auth, and the model catalog honest and declares no bounded posture.
"""

from __future__ import annotations

import re

from research_harness.providers.cli.defs.codex import parse_semver
from research_harness.providers.cli.types import (
    UNKNOWN_EXTERNAL_HOST,
    AuthStatus,
    BoundedPosture,
    CliInvocation,
    CliModelOption,
    CliRuntimeDef,
    Probe,
    ProbeOutcome,
)

__all__ = ["CURSOR_AGENT", "cursor_args", "cursor_auth", "parse_cursor_models"]

_NOT_LOGGED_IN = re.compile(
    r"not (?:logged in|authenticated)|please (?:log|sign) in|run .*login", re.IGNORECASE
)
_LOGGED_IN = re.compile(r"logged in|authenticated as|signed in", re.IGNORECASE)


def cursor_auth(outcome: ProbeOutcome) -> tuple[AuthStatus, str]:
    if _NOT_LOGGED_IN.search(outcome.text):
        return "missing", "run `cursor-agent login`"
    if outcome.exit_code == 0 and _LOGGED_IN.search(outcome.text):
        return "ok", ""
    return "unknown", "run `cursor-agent status`"


def parse_cursor_models(outcome: ProbeOutcome) -> tuple[CliModelOption, ...] | None:
    if re.search(r"no models available", outcome.stdout, re.IGNORECASE):
        return None
    ids = [
        line.strip()
        for line in outcome.stdout.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    seen: list[str] = []
    for item in ids:
        if item not in seen:
            seen.append(item)
    return tuple(CliModelOption(id=item, label=item) for item in seen) or None


def cursor_args(invocation: CliInvocation) -> tuple[str, ...]:
    args = [
        "--print",
        "--output-format",
        "stream-json",
        "--stream-partial-output",
        "--workspace",
        str(invocation.cwd),
    ]
    if invocation.model:
        args += ["--model", invocation.model]
    return tuple(args)


CURSOR_AGENT = CliRuntimeDef(
    id="cursor-agent",
    name="Cursor Agent",
    executable="cursor-agent",
    version_probe=Probe(args=("--version",), timeout_seconds=3.0),
    parse_version=parse_semver,
    auth_probe=Probe(args=("status",), timeout_seconds=5.0),
    classify_auth=cursor_auth,
    model_probe=Probe(args=("models",), timeout_seconds=5.0),
    parse_models=parse_cursor_models,
    fallback_models=(
        CliModelOption(id="auto", label="auto"),
        CliModelOption(id="sonnet-4", label="sonnet-4"),
        CliModelOption(id="gpt-5", label="gpt-5"),
    ),
    reasoning_choices=(),
    protocol="json_events",
    json_events_variant="cursor_agent",
    transport="stdin_text",
    build_args=cursor_args,
    posture=BoundedPosture(
        kind="none",
        note=(
            "headless Cursor Agent runs only with --force (approval bypass); "
            "no deny-tools flag is documented"
        ),
    ),
    egress="unknown_external",
    egress_host=UNKNOWN_EXTERNAL_HOST,
    default_context_tokens=128_000,
    login_guidance="run `cursor-agent login`",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/cursor-agent.ts",
    env_keep=("CURSOR_CONFIG_DIR",),
    notes=(
        "Nothing bounds the run, which is why the posture is `none` and the capability layer "
        "never spawns this runtime for research: `--print` still stops for approval on every "
        "tool call unless `--force` is passed, and no released build documents a flag that "
        "removes the tools instead. Nothing bounds the login either: `cursor-agent status` "
        "proves only that some Cursor account is signed in — it names neither the plan that "
        "pays for the call nor the host it reaches — and env_keep admits CURSOR_CONFIG_DIR, "
        "where a persisted login lives. The destination is therefore unknown_external rather "
        "than a named host. Detection, auth, and the catalog are kept "
        "so the scan can report the runtime honestly, and so a version that documents a "
        "deny-tools flag is a one-line change to the posture."
    ),
)
