"""Amp (`amp`) — detected, never routed (CLI providers spec §9, §12).

Ported from open-design@9bb4a7d `runtimes/defs/amp.ts`. Amp's headless mode blocks on
approval unless `--dangerously-allow-all`, which is forbidden here; no deny-tools flag is
documented, so the posture is `none`. Amp selects its model through an agent *mode*
(`smart`, `deep`, `rush`), surfaced as the model choice and sent as `--mode`.
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
)

__all__ = ["AMP", "AMP_MODES", "amp_args"]

AMP_MODES = frozenset({"smart", "deep", "rush"})


def amp_args(invocation: CliInvocation) -> tuple[str, ...]:
    args = ["-x", "--stream-json"]
    if invocation.model and invocation.model in AMP_MODES:
        args += ["--mode", invocation.model]
    return tuple(args)


AMP = CliRuntimeDef(
    id="amp",
    name="Amp",
    executable="amp",
    version_probe=Probe(args=("--version",), timeout_seconds=3.0),
    parse_version=parse_semver,
    fallback_models=(
        CliModelOption(id="smart", label="Smart (mode)"),
        CliModelOption(id="deep", label="Deep (mode)"),
        CliModelOption(id="rush", label="Rush (mode)"),
    ),
    reasoning_choices=(),
    protocol="claude_stream",
    transport="stdin_text",
    build_args=amp_args,
    posture=BoundedPosture(
        kind="none",
        note=(
            "headless Amp waits for approval unless --dangerously-allow-all; "
            "no deny-tools flag is documented"
        ),
    ),
    egress="unknown_external",
    egress_host=UNKNOWN_EXTERNAL_HOST,
    default_context_tokens=128_000,
    login_guidance="run `amp login`",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/amp.ts",
    notes=(
        "Nothing bounds the run: `-x` waits for a human on every tool call unless "
        "--dangerously-allow-all is passed, and Amp documents no flag that removes the tools "
        "instead, so the posture is `none` and the runtime is detected but never spawned for "
        "research. Nothing bounds the login either: Amp ships no side-effect-free auth "
        "command, so auth_probe is None and a scan reports auth_status `unknown` rather than "
        "guessing; `amp login` is the guidance a user acts on, not a verified state. Amp has "
        "no --model flag at all — the picker chooses an agent mode (smart, deep, rush) sent "
        "as --mode, and an id that is not one of the three is dropped rather than passed "
        "through as an invented flag value. Which provider a mode reaches is Amp's own "
        "business, hence unknown_external."
    ),
)
