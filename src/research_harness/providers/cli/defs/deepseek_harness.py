"""DeepSeek Harness (`dsh`) through its Open Design profile (CLI providers spec §9).

Ported from open-design@9bb4a7d `runtimes/defs/deepseek-harness.ts` and
`agent-protocol/dsh-profile/`. The profile's `execute` command is a full agent turn that
runs the profile's own tools; generation 1 documents no tool-less execution, so the
posture is `none`: detected, catalogued, never routed. Auth is inferred from the probe
frame (a profile that answers is installed and initialised).
"""

from __future__ import annotations

import json
import re

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

__all__ = [
    "DEEPSEEK_HARNESS",
    "dsh_args",
    "dsh_probe_version",
    "parse_dsh_models",
    "parse_dsh_semver",
]

_VERSION = re.compile(r"^v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)$")


def parse_dsh_semver(outcome: ProbeOutcome) -> str | None:
    match = _VERSION.match(outcome.stdout.strip())
    return match.group(1) if match else None


def _single_frame(outcome: ProbeOutcome) -> dict[str, object] | None:
    lines = [line for line in outcome.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    try:
        frame = json.loads(lines[0])
    except ValueError:
        return None
    return frame if isinstance(frame, dict) and frame.get("v") == 1 else None


def dsh_probe_version(outcome: ProbeOutcome) -> tuple[AuthStatus, str]:
    frame = _single_frame(outcome)
    if frame is not None and frame.get("type") == "probe" and frame.get("runtime") == "open-design":
        return "ok", ""
    return "unknown", "install the open-design profile (`dsh --profile open-design --probe`)"


def parse_dsh_models(outcome: ProbeOutcome) -> tuple[CliModelOption, ...] | None:
    frame = _single_frame(outcome)
    if frame is None or frame.get("type") != "models":
        return None
    raw_models = frame.get("models")
    if not isinstance(raw_models, list):
        return None
    options: list[CliModelOption] = []
    for item in raw_models:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(key), str) for key in ("provider", "id", "name", "provider_name")
        ):
            return None
        efforts = tuple(
            effort["id"]
            for effort in item.get("reasoning_options", [])
            if isinstance(effort, dict) and isinstance(effort.get("id"), str)
        )
        options.append(
            CliModelOption(
                id=f"{item['provider']}/{item['id']}",
                label=f"{item['name']} · {item['provider_name']}",
                reasoning=efforts,
            )
        )
    return tuple(options) or None


def dsh_args(invocation: CliInvocation) -> tuple[str, ...]:
    return ("--profile", "open-design", "--stdio")


DEEPSEEK_HARNESS = CliRuntimeDef(
    id="deepseek-harness",
    name="DeepSeek Harness",
    executable="dsh",
    version_probe=Probe(args=("--version",), timeout_seconds=3.0),
    parse_version=parse_dsh_semver,
    auth_probe=Probe(args=("--profile", "open-design", "--probe"), timeout_seconds=10.0),
    classify_auth=dsh_probe_version,
    model_probe=Probe(args=("--profile", "open-design", "--models"), timeout_seconds=10.0),
    parse_models=parse_dsh_models,
    reasoning_choices=("low", "medium", "high"),
    protocol="dsh_profile",
    transport="dsh_profile",
    build_args=dsh_args,
    posture=BoundedPosture(
        kind="none",
        note=(
            "the open-design profile executes its own tools; generation 1 has no tool-less execute"
        ),
    ),
    egress="unknown_external",
    egress_host=UNKNOWN_EXTERNAL_HOST,
    default_context_tokens=128_000,
    login_guidance="configure a provider in `dsh` and install the open-design profile",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/deepseek-harness.ts",
    minimum_version="0.1.0",
    env_keep=("DSH_HOME",),
    notes=(
        "Nothing bounds the run: the profile's `execute` command is one whole agent turn "
        "driven by the profile's own tools, and generation 1 of the protocol has no "
        "tool-less execute to ask for, so the posture is `none` — detected and catalogued, "
        "never spawned for research. The probe frame is the only auth signal there is, and "
        "it is a weak one: a profile that answers with capabilities.structured_events is "
        "installed and initialised, which says nothing about which provider key it would "
        "spend, so the destination stays unknown_external and a failed probe is reported "
        "`unknown` rather than `missing`. env_keep admits only DSH_HOME, the directory the "
        "profile itself lives under; without it the probe would answer for a profile the "
        "user never installed. The version parser is deliberately strict (`v?X.Y.Z[-pre]` "
        "and nothing else) because dsh prints a bare version line and a looser match would "
        "read a release-candidate suffix as a different release."
    ),
)
