"""OpenCode (`opencode-cli`, `opencode`) as a bounded worker (CLI providers spec §9).

Ported from open-design@9bb4a7d `runtimes/defs/opencode.ts` and `opencode-permissions.ts`.
Open Design passes `--dangerously-skip-permissions`; this definition injects a deny
permission table through `OPENCODE_CONFIG_CONTENT` (edit, bash, webfetch all `deny`),
disables project-config discovery, and pins the workspace to the empty temp cwd.
"""

from __future__ import annotations

import json
import re

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

__all__ = ["OPENCODE", "opencode_args", "parse_opencode_models"]

_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._/:@-]*$")
_VARIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def parse_opencode_models(outcome: ProbeOutcome) -> tuple[CliModelOption, ...] | None:
    lines = outcome.stdout.splitlines()
    options: list[CliModelOption] = []
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        model_id = lines[index].strip()
        index += 1
        if not _MODEL_ID.match(model_id) or model_id in seen:
            continue
        seen.add(model_id)
        variants: tuple[str, ...] = ()
        if index < len(lines) and lines[index].lstrip().startswith("{"):
            buffer = ""
            while index < len(lines):
                buffer += lines[index] + "\n"
                index += 1
                try:
                    metadata = json.loads(buffer)
                except ValueError:
                    continue
                raw = metadata.get("variants") if isinstance(metadata, dict) else None
                if isinstance(raw, dict):
                    variants = tuple(key for key in raw if _VARIANT.match(key))
                break
        options.append(CliModelOption(id=model_id, label=model_id, reasoning=variants))
    return tuple(options) or None


def opencode_args(invocation: CliInvocation) -> tuple[str, ...]:
    args = ["run", "--format", "json", "--dir", str(invocation.cwd)]
    if invocation.model:
        args += ["-m", invocation.model]
    return tuple(args)


OPENCODE = CliRuntimeDef(
    id="opencode",
    name="OpenCode",
    executable="opencode-cli",
    fallback_executables=("opencode",),
    version_probe=Probe(args=("--version",), timeout_seconds=3.0),
    parse_version=parse_semver,
    model_probe=Probe(args=("models", "--verbose"), timeout_seconds=15.0),
    parse_models=parse_opencode_models,
    fallback_models=(
        CliModelOption(id="anthropic/claude-sonnet-4-5", label="anthropic/claude-sonnet-4-5"),
        CliModelOption(id="openai/gpt-5", label="openai/gpt-5"),
    ),
    reasoning_choices=(),
    protocol="json_events",
    json_events_variant="opencode",
    transport="stdin_text",
    build_args=opencode_args,
    posture=BoundedPosture(
        kind="native_env",
        help_probe=Probe(args=("run", "--help"), timeout_seconds=5.0),
        required_help_flags=("--format", "--dir"),
        note="permission table injected through OPENCODE_CONFIG_CONTENT denies edit, bash, "
        "and webfetch",
    ),
    egress="unknown_external",
    egress_host=UNKNOWN_EXTERNAL_HOST,
    default_context_tokens=128_000,
    login_guidance="run `opencode auth login`",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/opencode.ts",
    env_keep=(),
    env_drop=("OPENCODE_CONFIG",),
    env_set={
        "OPENCODE_CONFIG_CONTENT": json.dumps(
            {"permission": {"edit": "deny", "bash": "deny", "webfetch": "deny"}}
        ),
        "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
    },
    notes=(
        "What the posture claims and what this workstation can prove are two different "
        "things, and the gap is the point. The claim: OPENCODE_CONFIG_CONTENT carries a "
        "permission table denying edit, bash and webfetch, and "
        "OPENCODE_DISABLE_PROJECT_CONFIG stops a checked-in opencode.json from granting them "
        "back. What the help probe proves: only that `run --help` prints `--format` and "
        "`--dir`, the two flags in required_help_flags. It says nothing at all about "
        "permissions — a flag list is not a config layer — and `-m` is sent too whenever a "
        "model is chosen, so required_help_flags is not the full set of flags this "
        "definition sends, only the set the bounded posture depends on. Whether the deny "
        "table is honoured rests on OpenCode's own configuration layering, which no recorded "
        "fixture here has ever verified: no OpenCode was installed when this was ported and "
        "verified_versions is empty. So detection reports the bounded mode as unproven and "
        "the runtime is not routable until someone runs a real OpenCode, records the "
        "fixtures, and adds that version to verified_versions. `--dir` is part of the claim "
        "rather than a convenience: OpenCode does not treat its process cwd as the workspace "
        "but walks up to the nearest enclosing git root, so without it a run started inside "
        "a checkout would adopt the whole repository. Nothing bounds the login either: "
        "OpenCode ships no side-effect-free auth command, so auth_probe is None and "
        "auth_status stays `unknown`, and it reaches whichever provider the user configured "
        "— hence unknown_external rather than a named host. env_keep is empty and "
        "OPENCODE_CONFIG is dropped outright, so a pointer to the user's own configuration "
        "file can never ride into a bounded run and re-grant what the injected table denies. "
        "Variants are read from the catalog for display only; `--variant` is never sent, "
        "because a variant is a per-model name and reasoning_choices is empty."
    ),
)
