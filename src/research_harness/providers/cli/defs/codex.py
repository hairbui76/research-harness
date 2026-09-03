"""Codex CLI (`codex`) as a bounded research worker (CLI providers spec §9).

Ported from open-design@9bb4a7d `apps/daemon/src/runtimes/defs/codex.ts` and compared
with codex-cli 0.150.1. Open Design runs Codex as a full agent (`--sandbox
workspace-write`/`danger-full-access`); this definition runs `codex exec` read-only with
approvals set to `never`, in an empty temp cwd, without the user's config or rules, and
hands Codex the response schema through `--output-schema`.
"""

from __future__ import annotations

import json
import re

from research_harness.providers.cli.types import (
    AuthStatus,
    BoundedPosture,
    CliInvocation,
    CliModelOption,
    CliRuntimeDef,
    Probe,
    ProbeOutcome,
)

__all__ = ["CODEX", "codex_args", "codex_auth", "parse_codex_models", "parse_semver"]

_SEMVER = re.compile(r"(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)")
_LOGGED_IN = re.compile(r"\blogged in\b", re.IGNORECASE)
_LOGGED_IN_CHATGPT = re.compile(r"logged in using chatgpt", re.IGNORECASE)
_API_KEY = re.compile(r"api[ _-]?key", re.IGNORECASE)
_NOT_LOGGED_IN = re.compile(r"\bnot logged in\b|login required|please run .*login", re.IGNORECASE)

_API_KEY_LOGIN = (
    "logged in with an API key, not a ChatGPT subscription: run `codex login` to use the "
    "subscription (an API-key login is metered and talks to api.openai.com, not chatgpt.com)"
)


def parse_semver(outcome: ProbeOutcome) -> str | None:
    match = _SEMVER.search(outcome.text)
    return match.group(1) if match else None


def codex_auth(outcome: ProbeOutcome) -> tuple[AuthStatus, str]:
    """Only a ChatGPT subscription login counts as `ok`.

    A persisted API-key login lives under `$CODEX_HOME`, which `env_keep` preserves, so
    dropping `OPENAI_API_KEY` does not by itself rule metered access out: the probe has to.
    """
    if _NOT_LOGGED_IN.search(outcome.text):
        return "missing", "run `codex login`"
    if _LOGGED_IN.search(outcome.text) and _API_KEY.search(outcome.text):
        return "missing", _API_KEY_LOGIN
    if outcome.exit_code == 0 and _LOGGED_IN_CHATGPT.search(outcome.text):
        return "ok", ""
    if outcome.exit_code not in (0, None):
        return "missing" if not outcome.text.strip() else "unknown", "run `codex login`"
    return "unknown", "run `codex login status`"


def parse_codex_models(outcome: ProbeOutcome) -> tuple[CliModelOption, ...] | None:
    try:
        payload = json.loads(outcome.stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        return None
    options: list[CliModelOption] = []
    for item in payload["models"]:
        if not isinstance(item, dict) or item.get("visibility") == "hide":
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        efforts = tuple(
            level["effort"]
            for level in item.get("supported_reasoning_levels", [])
            if isinstance(level, dict) and isinstance(level.get("effort"), str)
        )
        window = item.get("context_window")
        options.append(
            CliModelOption(
                id=slug,
                label=str(item.get("display_name") or slug),
                reasoning=efforts,
                context_tokens=window if isinstance(window, int) else None,
            )
        )
    return tuple(options) or None


def codex_args(invocation: CliInvocation) -> tuple[str, ...]:
    args = [
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "-c",
        'approval_policy="never"',
        "-C",
        str(invocation.cwd),
    ]
    if invocation.schema_path is not None:
        args += ["--output-schema", str(invocation.schema_path)]
    if invocation.model:
        args += ["--model", invocation.model]
    if invocation.reasoning:
        args += ["-c", f'model_reasoning_effort="{invocation.reasoning}"']
    return tuple(args)


CODEX = CliRuntimeDef(
    id="codex",
    name="Codex CLI",
    executable="codex",
    version_probe=Probe(args=("--version",), timeout_seconds=3.0),
    parse_version=parse_semver,
    auth_probe=Probe(args=("login", "status"), timeout_seconds=5.0),
    classify_auth=codex_auth,
    model_probe=Probe(args=("debug", "models"), timeout_seconds=5.0),
    parse_models=parse_codex_models,
    fallback_models=(
        CliModelOption(id="gpt-5.5", label="gpt-5.5", reasoning=("low", "medium", "high", "xhigh")),
        CliModelOption(id="gpt-5.4", label="gpt-5.4", reasoning=("low", "medium", "high", "xhigh")),
        CliModelOption(
            id="gpt-5.4-mini", label="gpt-5.4-mini", reasoning=("low", "medium", "high")
        ),
    ),
    reasoning_choices=("low", "medium", "high", "xhigh"),
    protocol="json_events",
    json_events_variant="codex",
    transport="stdin_text",
    build_args=codex_args,
    posture=BoundedPosture(
        kind="native_flags",
        help_probe=Probe(args=("exec", "--help"), timeout_seconds=5.0),
        required_help_flags=(
            "--sandbox",
            "--output-schema",
            "--json",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
        ),
        note="read-only sandbox, approvals never, empty temp cwd, user config and rules ignored",
    ),
    egress="external",
    egress_host="chatgpt.com",
    default_context_tokens=272_000,
    login_guidance="run `codex login`",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/codex.ts",
    verified_versions=("0.150.1",),
    env_keep=("CODEX_HOME",),
    notes=(
        "A ChatGPT login talks to chatgpt.com; an API-key login is metered and would talk to "
        "api.openai.com instead. Two things bound that: the bounded environment drops the "
        "API-key variables (env_keep admits only CODEX_HOME), and the auth probe accepts "
        "only a ChatGPT login. Dropping the variables alone would not be enough, because a "
        "persisted API-key login lives under $CODEX_HOME, which env_keep preserves; "
        "codex_auth therefore reports such a login as not routable rather than letting the "
        "run reach a different host."
    ),
)
