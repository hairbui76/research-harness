"""Pi (`pi`) over its RPC mode — detected, never routed (CLI providers spec §9).

Ported from open-design@9bb4a7d `runtimes/defs/pi.ts` and `agent-protocol/pi-rpc/`. Pi
runs its own tools inside the RPC session and documents no flag that removes them, so the
posture is `none`. The catalog and reasoning presets are kept so a future version that
documents a tool-less mode is a one-line change.
"""

from __future__ import annotations

from research_harness.providers.cli.defs.codex import parse_semver
from research_harness.providers.cli.types import (
    UNKNOWN_EXTERNAL_HOST,
    BoundedPosture,
    CliInvocation,
    CliModelOption,
    CliRuntimeDef,
    Probe,
    ProbeOutcome,
)

__all__ = ["PI", "parse_pi_models", "pi_args"]


def parse_pi_models(outcome: ProbeOutcome) -> tuple[CliModelOption, ...] | None:
    rows = [
        line.strip()
        for line in outcome.stdout.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    options: list[CliModelOption] = []
    seen: set[str] = set()
    for row in rows[1:]:
        parts = row.split()
        if len(parts) < 2:
            continue
        model_id = f"{parts[0]}/{parts[1]}"
        if model_id in seen:
            continue
        seen.add(model_id)
        window = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        options.append(CliModelOption(id=model_id, label=model_id, context_tokens=window))
    return tuple(options) or None


def pi_args(invocation: CliInvocation) -> tuple[str, ...]:
    args = ["--mode", "rpc"]
    if invocation.model:
        args += ["--model", invocation.model]
    if invocation.reasoning:
        args += ["--thinking", invocation.reasoning]
    return tuple(args)


PI = CliRuntimeDef(
    id="pi",
    name="Pi",
    executable="pi",
    version_probe=Probe(args=("--version",), timeout_seconds=15.0),
    parse_version=parse_semver,
    model_probe=Probe(args=("--list-models",), timeout_seconds=15.0),
    parse_models=parse_pi_models,
    fallback_models=(
        CliModelOption(id="anthropic/claude-sonnet-4-5", label="Claude Sonnet 4.5 (anthropic)"),
        CliModelOption(id="openai/gpt-5", label="GPT-5 (openai)"),
    ),
    reasoning_choices=("minimal", "low", "medium", "high", "xhigh"),
    protocol="pi_rpc",
    transport="pi_rpc",
    build_args=pi_args,
    posture=BoundedPosture(
        kind="none",
        note="pi runs its own tools inside the RPC session; no tool-less mode is documented",
    ),
    egress="unknown_external",
    egress_host=UNKNOWN_EXTERNAL_HOST,
    default_context_tokens=200_000,
    login_guidance="configure a provider key inside `pi`",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/pi.ts",
    notes=(
        "Nothing bounds the run: the RPC session is a full agent turn with pi's own tools, "
        "and no flag is documented that removes them, so the posture is `none` and the "
        "runtime is detected and catalogued but never spawned for research. Nothing bounds "
        "the login either: pi ships no side-effect-free auth command, so auth_probe is None "
        "and auth_status stays `unknown`; the guidance names what a user does, not a state "
        "this code verified. Pi talks to whichever provider key is configured inside it — "
        "the catalog spans several vendors — so the destination is unknown_external. The "
        "version probe gets 15 s rather than the usual 3 s because pi cold-starts slowly "
        "enough that a tighter budget aborts detection before the catalog is ever read. "
        "Reasoning is sent as --thinking when the harness level names one of "
        "reasoning_choices, which is the one part of this definition that would already be "
        "correct if a future version documented a tool-less mode."
    ),
)
