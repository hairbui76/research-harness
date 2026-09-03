# Subscription-backed Local CLI Providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a researcher who is already logged in to Codex CLI, Claude Code, Cursor Agent, Amp, DeepSeek Harness, OpenCode, or Pi route research work through that CLI — with no API key in Research Harness — through the existing provider-neutral contract, privacy policy, traces, and review gates.

**Architecture:** A declarative runtime registry (seven immutable `CliRuntimeDef` records: probes, pure argv builders, parser family, bounded posture, egress declaration) plus one bounded subprocess engine (fresh temp cwd, filtered environment, stdin/RPC prompt delivery, stream parser → small event vocabulary, timeout/cancel/process-tree cleanup). `CliModelProvider` turns one `ModelRequest` into one subprocess run and returns `RawCompletion`, so `ModelProvider.complete()` keeps Pydantic validation authoritative. Four capabilities (`provider.cli.scan|configure|remove|test`) are the single server-side truth the CLI (`research providers …`) and the Web *Models & providers* settings render.

**Tech Stack:** Python 3.12, Pydantic v2, `subprocess` + threads (no new dependencies), pytest with fake executables; React 18 + `@research-harness/design` + vitest/axe in `web/`.

**Spec:** `docs/superpowers/specs/2026-09-03-subscription-local-cli-providers-design.md` — every task below cites the section it implements. Open Design is pinned as a submodule at `open-design` (revision `9bb4a7d66d31a4bb7a678a93c6940d3677774e51`); it is a reading reference only and is never imported.

## Global Constraints

Copied from the spec and `docs/architecture/conventions.md`; every task's requirements include this section.

- **Toolchain.** `export PATH="$HOME/.local/bin:$PATH"` first (uv 0.12, Node 22.23, pnpm 11.25 live there). Python gates: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`. Web gates: `pnpm --filter research-harness-web typecheck`, `… lint`, `… test`, `… build`. Do **not** edit `pyproject.toml`, any `package.json`, or run `uv add`/`pnpm add`.
- **Gate cadence.** The full `uv run pytest -q` takes ~25 minutes on this workstation (4250 tests). A task's *Run the tests and gates* step runs the focused suites it names plus `ruff check`, `ruff format --check`, and `mypy src`; the PM runs the full suite in the background at each wave gate and before every commit that touches shared modules (`router.py`, `egress.py`, `providers.py`, `repository.py`).
- **Commits.** A subagent never commits; it reports. The PM runs each task's *Commit* step after review, with the message given, ending in the session's `Co-Authored-By`/`Claude-Session` trailer.
- **Layering** (conventions.md): `providers/` never imports `cli/`, `server/`, `capabilities/`, or domain-specific rules; `workspace/` never imports `providers/`; `capabilities/` is the only mutation surface; transports (`cli/`, `server/`, `protocol/`) are thin. `domain/` is not touched by this plan.
- **Egress invariant (spec §4).** A CLI-backed provider is never `local`. Its `EgressDeclaration.endpoint_host` must fail `privacy.policy.is_local_endpoint` — no loopback, no `.local`, and it must not start with `(`. Unknown destinations use exactly `UNKNOWN_EXTERNAL_HOST = "unknown.external"`. `sends_source_text = sends_identifiers = True` always.
- **Forbidden argv tokens (spec §12), enforced by the registry:** `--dangerously-skip-permissions`, `--dangerously-allow-all`, `--dangerously-bypass-approvals-and-sandbox`, `--allow-dangerously-skip-permissions`, `--approve-for-me`, `--force`, `--trust`, `bypassPermissions`, `danger-full-access`, `workspace-write`.
- **Research content never in argv (spec §12).** The prompt goes through stdin or the RPC channel. The only file path an argument may name is the schema file the engine writes into the temp cwd (Codex `--output-schema`).
- **Execution cwd** is a fresh `tempfile.mkdtemp(prefix="rh-cli-")` containing at most `response.schema.json`; it is removed in `finally`.
- **Environment (spec §12).** Allowlist + denylist in `environment.py`; every variable matching `*_API_KEY`, `*_TOKEN`, `*_SECRET*`, `AWS_*`, `AZURE_*`, `OPENAI_*`, `ANTHROPIC_*`, `GEMINI_*`, `GOOGLE_APPLICATION_CREDENTIALS`, `CODEX_API_KEY`, `CURSOR_API_KEY`, `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY` is removed, so a subscription login can never silently become metered API-key access.
- **Nothing secret is persisted or printed (spec §19).** Raw stdout/stderr live only in bounded memory; every diagnostic string passes `errors.redact()` (home paths → `~`, `sk-…`/`Bearer …`/`ghp_…` tokens, e-mails, `?signature=`/`X-Amz-Signature` URLs, base64/hex runs ≥ 40 chars). Test fixtures contain no real account identifiers.
- **Bounded authority (spec §13).** A `tool` event (tool call, command execution, file write) in bounded mode cancels the process and raises `ProviderResponseError` with diagnostic `bounded_authority_violation`. There is no prompt-only fallback: a runtime whose `bounded_mode != "safe"` is never spawned for research.
- **No silent failover (spec §11).** The provider raises; it never retries on another runtime or model. The router already refuses to fail over.
- **Limits.** Version probe 3 s; auth/help/model probes 5 s (DeepSeek Harness 10 s, OpenCode models 15 s, Pi list-models 15 s); request default 300 s; cancel grace 2 s; stdout cap 8 MiB; one line ≤ 1 MiB; stderr tail 16 KiB.
- **Tests are offline by default** (conventions.md): fake executables written under `tmp_path`, no real CLI, no network, no key. Live tests run only with `RESEARCH_HARNESS_LIVE_CLI_TESTS=1` and skip when the CLI is absent.
- **Names.** Provider kind `local_cli`; adapter name `local_cli:<runtime>` (e.g. `local_cli:codex`); runtime ids `codex`, `claude`, `cursor-agent`, `amp`, `deepseek-harness`, `opencode`, `pi`; capabilities `provider.cli.scan`, `provider.cli.configure`, `provider.cli.remove`, `provider.cli.test`; CLI family `research providers scan|add|test|remove|list`.
- **Installed CLIs on this workstation** (for the opt-in live task only): `codex` 0.150.1 (`codex login status` → `Logged in using ChatGPT`, exit 0), `claude` 2.1.259 (`claude auth status` → JSON with `"loggedIn": true`). Neither may be invoked by a default test.

---

## File map

| File | Responsibility |
|---|---|
| **Create** `src/research_harness/providers/cli/__init__.py` | Public names of the package |
| **Create** `src/research_harness/providers/cli/types.py` | Immutable runtime/model/probe/detection contracts (§8, §10) |
| **Create** `src/research_harness/providers/cli/errors.py` | Diagnostic codes, the four error subclasses, `redact()`, `classify_failure()` (§15, §19) |
| **Create** `src/research_harness/providers/cli/registry.py` | Definition validation, `RUNTIMES`, `get_runtime()` (§8) |
| **Create** `src/research_harness/providers/cli/prompt.py` | Deterministic prompt rendering, JSONL user message (§12) |
| **Create** `src/research_harness/providers/cli/environment.py` | Allow/deny environment filtering (§12) |
| **Create** `src/research_harness/providers/cli/process.py` | `run_probe`, `BoundedProcess` (spawn, drain, limits, cancel, tree kill) (§14) |
| **Create** `src/research_harness/providers/cli/parsers/__init__.py` | `CliEvent` vocabulary, `EventParser`, `PARSERS`, `parser_for()` (§13) |
| **Create** `src/research_harness/providers/cli/parsers/claude_stream.py` | Claude Code / Amp stream-json → events |
| **Create** `src/research_harness/providers/cli/parsers/json_events.py` | Codex / Cursor Agent / OpenCode JSON event streams → events |
| **Create** `src/research_harness/providers/cli/parsers/dsh_profile.py` | DeepSeek Harness profile JSONL → events |
| **Create** `src/research_harness/providers/cli/parsers/pi_rpc.py` | Pi RPC → events |
| **Create** `src/research_harness/providers/cli/transport.py` | How the prompt is delivered and cancelled per transport (§12, §14) |
| **Create** `src/research_harness/providers/cli/detection.py` | Executable resolution, probes, fault-isolated `scan()`, short cache (§10) |
| **Create** `src/research_harness/providers/cli/provider.py` | `CliModelProvider`, `default_cli_capabilities()` (§12, §13) |
| **Create** `src/research_harness/providers/cli/defs/{__init__,codex,claude,cursor_agent,amp,deepseek_harness,opencode,pi}.py` | The seven definitions (§9) |
| **Modify** `src/research_harness/providers/models/router.py` | `local_cli` kind, `runtime`/`reasoning` fields, entry building (§11) |
| **Modify** `src/research_harness/providers/models/streaming.py` | `NativeStream._record` includes `provider.trace_metadata()` when present (§19) |
| **Modify** `src/research_harness/privacy/egress.py` | No key variable for `local_cli` rows |
| **Modify** `src/research_harness/workspace/repository.py` | `WorkspaceConfig.with_providers()`, `WorkspaceRepository.update_providers()` |
| **Create** `src/research_harness/capabilities/cli_providers.py` | The four capabilities, their DTOs and handlers (§16) |
| **Modify** `src/research_harness/capabilities/providers.py` | Register them; CLI rows in `provider.list` (§16) |
| **Modify** `src/research_harness/cli/commands/provider.py` | `research providers scan|add|test|remove` (§17) |
| **Modify** `src/research_harness/cli/app.py` | `doctor` reports configured CLI runtimes (§23.10) |
| **Modify** `web/src/api/dto.ts`, `web/src/api/client.ts` | Hand-declared DTOs and client methods |
| **Create** `web/src/app/settings/{ProvidersSettings,LocalCliTab,ApiProvidersTab,RuntimeCard}.tsx`, `useCliRuntimes.ts`, `mappers.ts`, `settings.css`, `settings.test.tsx` | The *Models & providers* section (§18) |
| **Modify** `web/src/app/SettingsDialog.tsx` | Appearance + Models & providers tabs |
| **Create** `web/src/test/fixtures/providers/*.json` | Scan/configure/test fixtures matching the Pydantic schemas |
| **Regenerate** `web/openapi.json`, `web/capabilities.json`, `web/src/api/*.gen.ts`, `docs/guide/capabilities.md`, `docs/guide/cli-reference.md` | Through the existing scripts |
| **Create** `tests/fixtures/cli/__init__.py`, `tests/fixtures/cli/fakes.py`, `tests/fixtures/cli/streams/*.jsonl` | Fake executables and sanitized event fixtures |
| **Create** `tests/unit/providers/cli/**`, `tests/contract/providers/test_cli_provider.py`, `tests/contract/providers/test_live_cli_smoke.py`, `tests/contract/capabilities/test_cli_providers.py`, `tests/e2e/test_cli_providers_commands.py` | The test suites |
| **Modify** `tests/e2e/test_cli_capability_parity.py`, `tests/contract/protocol/test_new_capability_parity.py`, `tests/contract/protocol/test_web_routes.py` | Pin the new capabilities and DTOs |
| **Create** `docs/decisions/ADR-030-cli-backed-providers-are-bounded-external-workers.md`; **Modify** `docs/guide/providers.md`, `docs/index.md`, `docs/decisions/README.md`, `docs/architecture/web.md`, `docs/architecture/domain-changelog.md`, `docs/plans/acceptance-matrix.md`, `README.md`, `ROADMAP.md` | Documentation and status |

Waves for the PM (max 3 subagents run at once; every task's tests must be green before the next wave):

| Wave | Tasks |
|---|---|
| A | 1 |
| B | 2, 3, 4 (independent; all consume Task 1) |
| C | 5, 6, 7 (consume A+B) |
| D | 8 |
| E | 9, 10 |
| F | 11, 12 |
| G | 13, 14 |
| H | 15 (PM) |

---

### Task 1: Contracts, errors, event vocabulary, and the validating registry

Spec §8, §13 (vocabulary), §15, §19. Everything later tasks type against.

**Files:**
- Create: `src/research_harness/providers/cli/__init__.py`
- Create: `src/research_harness/providers/cli/types.py`
- Create: `src/research_harness/providers/cli/errors.py`
- Create: `src/research_harness/providers/cli/parsers/__init__.py`
- Create: `src/research_harness/providers/cli/registry.py`
- Create: `src/research_harness/providers/cli/defs/__init__.py`
- Create: `tests/unit/providers/cli/__init__.py`
- Test: `tests/unit/providers/cli/test_types.py`, `tests/unit/providers/cli/test_errors.py`, `tests/unit/providers/cli/test_registry.py`

**Interfaces:**
- Produces (types.py): `AuthStatus`, `BoundedMode`, `Compatibility`, `ModelSource`, `PromptTransport`, `ProtocolFamily`, `JsonEventsVariant`, `EgressKind`, `UNKNOWN_EXTERNAL_HOST`, `DEFAULT_MODEL`, `Probe`, `ProbeOutcome`, `CliModelOption`, `BoundedPosture`, `CliInvocation`, `CliRuntimeDef`, `CliModelView`, `CliRuntimeStatus`, `unavailable_reason()`.
- Produces (errors.py): `DiagnosticCode`, `CliAuthError`, `CliRateLimitError`, `CliTransportError`, `CliResponseError`, `redact()`, `describe_runtime()`, `classify_failure()`.
- Produces (parsers/__init__.py): `EventKind`, `CliEvent`, `EventParser`, `ParserFactory`, `PARSERS` (a mutable `dict` the four parser modules fill in Task 4; Task 1 seeds it with `_UnimplementedParser` entries that raise `NotImplementedError` so registry validation of "parser registered" is meaningful now and real later), `parser_for()`.
- Produces (registry.py): `FORBIDDEN_ARGS`, `SAMPLE_INVOCATIONS`, `RegistryError`, `UnknownRuntimeError`, `validate_definition()`, `build_registry()`, `RUNTIME_DEFS`, `RUNTIMES`, `RUNTIME_IDS`, `get_runtime()`.

- [ ] **Step 1: Write the failing tests for the contracts**

`tests/unit/providers/cli/__init__.py` is empty. `tests/unit/providers/cli/test_types.py`:

```python
"""The immutable CLI runtime contracts (CLI providers spec §8, §10)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from research_harness.providers.cli.types import (
    UNKNOWN_EXTERNAL_HOST,
    CliInvocation,
    CliModelView,
    CliRuntimeStatus,
    Probe,
    ProbeOutcome,
    unavailable_reason,
)


def status(**overrides: object) -> CliRuntimeStatus:
    values: dict[str, object] = {
        "runtime": "codex",
        "name": "Codex CLI",
        "available": True,
        "executable": "~/.local/bin/codex",
        "version": "0.150.1",
        "auth_status": "ok",
        "auth_guidance": "",
        "bounded_mode": "safe",
        "compatibility": "verified",
        "models": (CliModelView(id="default", label="Default (CLI configuration)"),),
        "model_source": "fallback",
        "reasoning_choices": ("low", "medium", "high"),
        "egress_kind": "external",
        "egress_host": "chatgpt.com",
        "diagnostics": (),
        "scanned_at": datetime(2026, 9, 4, tzinfo=UTC),
    }
    values.update(overrides)
    return CliRuntimeStatus.model_validate(values)


def test_a_probe_outcome_knows_whether_the_process_started() -> None:
    started = ProbeOutcome(argv=("codex", "--version"), exit_code=0, stdout="0.1", stderr="")
    missing = ProbeOutcome(
        argv=("codex", "--version"), exit_code=None, stdout="", stderr="", os_error="ENOENT"
    )
    assert started.started and not missing.started
    assert started.text == "0.1\n"


def test_a_probe_has_a_bounded_timeout() -> None:
    assert Probe(args=("--version",)).timeout_seconds == 5.0
    with pytest.raises(ValueError, match="timeout"):
        Probe(args=("--version",), timeout_seconds=0)


def test_an_invocation_is_frozen_data() -> None:
    invocation = CliInvocation(model=None, reasoning=None, cwd=Path("/tmp/x"), request_id="r1")
    with pytest.raises(AttributeError):
        invocation.model = "gpt"  # type: ignore[misc]


def test_a_routable_status_needs_every_gate() -> None:
    assert status().routable
    assert not status(available=False).routable
    assert not status(auth_status="missing").routable
    assert not status(bounded_mode="unsupported").routable
    assert not status(bounded_mode="unknown").routable
    assert not status(compatibility="blocked").routable
    assert status(auth_status="unknown").routable, "unknown auth is verified on first use"
    assert status(compatibility="warning").routable


def test_unavailable_reason_names_the_first_failing_gate() -> None:
    assert unavailable_reason(status()) is None
    assert unavailable_reason(status(available=False)) == "codex is not installed on this workstation"
    assert unavailable_reason(status(auth_status="missing", auth_guidance="run `codex login`")) == (
        "codex is not logged in: run `codex login`"
    )
    assert unavailable_reason(status(bounded_mode="unsupported")) == (
        "codex 0.150.1 has no tested bounded (no-tools, read-only) mode"
    )
    assert unavailable_reason(status(bounded_mode="unknown")) == (
        "codex 0.150.1 could not prove a bounded (no-tools, read-only) mode"
    )
    assert unavailable_reason(status(compatibility="blocked")) == (
        "codex 0.150.1 is a known-incompatible version"
    )


def test_the_unknown_external_host_is_never_local() -> None:
    from research_harness.privacy.policy import is_local_endpoint

    assert not is_local_endpoint(UNKNOWN_EXTERNAL_HOST)
```

`tests/unit/providers/cli/test_errors.py`:

```python
"""Failure classification and redaction (CLI providers spec §15, §19)."""

from __future__ import annotations

import pytest

from research_harness.providers.cli.errors import (
    CliAuthError,
    CliRateLimitError,
    CliResponseError,
    CliTransportError,
    classify_failure,
    describe_runtime,
    redact,
)
from research_harness.providers.models.base import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTransportError,
)


def test_the_four_errors_are_the_existing_provider_errors_with_a_diagnostic() -> None:
    error = CliAuthError("x", runtime="codex", diagnostic="login_missing")
    assert isinstance(error, ProviderAuthError)
    assert error.diagnostic == "login_missing" and error.runtime == "codex"
    assert error.provider == "local_cli:codex"
    assert isinstance(CliRateLimitError("x", runtime="codex", diagnostic="rate_limited"), ProviderRateLimitError)
    assert isinstance(CliTransportError("x", runtime="codex", diagnostic="timeout"), ProviderTransportError)
    assert isinstance(CliResponseError("x", runtime="codex", diagnostic="refusal"), ProviderResponseError)


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        ("/home/alice/.codex/auth.json", "~/.codex/auth.json"),
        ("Authorization: Bearer abcdef0123456789abcdef0123456789abcdef01", "Authorization: Bearer <redacted>"),
        ("key sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd", "key <redacted>"),
        ("mail alice.smith@example.org today", "mail <email> today"),
        ("https://x.test/a?X-Amz-Signature=abc&b=1", "https://x.test/a?<signed-query>"),
        ("token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij12", "token <redacted>"),
        ("plain words stay", "plain words stay"),
    ],
)
def test_redact_strips_credentials_paths_and_identities(raw: str, cleaned: str) -> None:
    assert redact(raw, home="/home/alice") == cleaned


def test_describe_runtime_names_runtime_model_and_version() -> None:
    assert describe_runtime("codex", "gpt-5.5", "0.150.1") == "codex/gpt-5.5 (0.150.1)"
    assert describe_runtime("codex", "default", None) == "codex/default (version unknown)"


def test_classify_failure_maps_conditions_onto_provider_errors() -> None:
    kwargs = {"runtime": "codex", "model": "default", "version": "0.150.1"}
    assert isinstance(classify_failure(os_error="ENOENT", **kwargs), CliTransportError)
    assert classify_failure(os_error="ENOENT", **kwargs).diagnostic == "executable_missing"
    assert classify_failure(timed_out=True, **kwargs).diagnostic == "timeout"
    assert classify_failure(output_limited=True, **kwargs).diagnostic == "output_limit"
    assert classify_failure(exit_code=1, stderr_tail="error: not logged in, run codex login", **kwargs).diagnostic == "login_missing"
    assert isinstance(classify_failure(exit_code=1, stderr_tail="HTTP 429 rate limit exceeded", **kwargs), CliRateLimitError)
    assert classify_failure(exit_code=1, stderr_tail="unknown model 'gpt-nope'", **kwargs).diagnostic == "unsupported_model"
    assert classify_failure(exit_code=2, stderr_tail="error: unexpected argument '--nope'", **kwargs).diagnostic == "invalid_invocation"
    assert classify_failure(exit_code=0, stderr_tail="", **kwargs).diagnostic == "missing_terminal_event"
    assert classify_failure(exit_code=139, stderr_tail="", **kwargs).diagnostic == "crashed"
    assert classify_failure(stream_error="model refused: cannot help", stream_code="refusal", **kwargs).diagnostic == "refusal"
    assert classify_failure(stream_error="Not logged in · Please run /login", stream_code="authentication_failed", **kwargs).diagnostic == "login_missing"


def test_messages_carry_identity_and_a_next_action_but_no_secret() -> None:
    error = classify_failure(
        runtime="codex",
        model="gpt-5.5",
        version="0.150.1",
        exit_code=1,
        stderr_tail="not logged in; token sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd in /home/alice/.codex",
        home="/home/alice",
    )
    assert "codex/gpt-5.5 (0.150.1)" in error.message
    assert "codex login" in error.message
    assert "sk-proj" not in error.message and "/home/alice" not in error.message
```

`tests/unit/providers/cli/test_registry.py`:

```python
"""The registry refuses anything that is not data (CLI providers spec §8, §12)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.providers.cli.registry import (
    FORBIDDEN_ARGS,
    RegistryError,
    UnknownRuntimeError,
    build_registry,
    get_runtime,
    validate_definition,
)
from research_harness.providers.cli.types import (
    UNKNOWN_EXTERNAL_HOST,
    BoundedPosture,
    CliInvocation,
    CliRuntimeDef,
    Probe,
    ProbeOutcome,
)


def build_args(invocation: CliInvocation) -> tuple[str, ...]:
    args = ["exec", "--json"]
    if invocation.model:
        args += ["--model", invocation.model]
    return tuple(args)


def parse_version(outcome: ProbeOutcome) -> str | None:
    return outcome.stdout.strip() or None


def definition(**overrides: object) -> CliRuntimeDef:
    values: dict[str, object] = {
        "id": "fake",
        "name": "Fake CLI",
        "executable": "fake",
        "version_probe": Probe(args=("--version",), timeout_seconds=3.0),
        "parse_version": parse_version,
        "protocol": "json_events",
        "json_events_variant": "codex",
        "transport": "stdin_text",
        "build_args": build_args,
        "posture": BoundedPosture(kind="native_flags", help_probe=Probe(args=("--help",)), required_help_flags=("--json",)),
        "egress": "external",
        "egress_host": "example.test",
        "default_context_tokens": 128_000,
        "login_guidance": "run `fake login`",
        "upstream_source": "open-design@9bb4a7d apps/daemon/src/runtimes/defs/fake.ts",
    }
    values.update(overrides)
    return CliRuntimeDef(**values)  # type: ignore[arg-type]


def test_a_well_formed_definition_validates() -> None:
    validate_definition(definition())


def test_duplicate_ids_are_refused() -> None:
    with pytest.raises(RegistryError, match="duplicate runtime id 'fake'"):
        build_registry([definition(), definition()])


@pytest.mark.parametrize("token", sorted(FORBIDDEN_ARGS))
def test_a_bypass_flag_anywhere_in_argv_is_refused(token: str) -> None:
    def unsafe(invocation: CliInvocation) -> tuple[str, ...]:
        return ("exec", token)

    with pytest.raises(RegistryError, match=f"forbidden argument {token!r}"):
        validate_definition(definition(build_args=unsafe))


def test_argv_must_be_a_tuple_of_plain_strings_without_shell_operators() -> None:
    def shell(invocation: CliInvocation) -> tuple[str, ...]:
        return ("exec", "&&", "rm")

    with pytest.raises(RegistryError, match="shell operator"):
        validate_definition(definition(build_args=shell))
    with pytest.raises(RegistryError, match="must return a tuple"):
        validate_definition(definition(build_args=lambda invocation: "exec --json"))  # type: ignore[arg-type,return-value]


def test_research_content_may_not_reach_argv() -> None:
    def leaks(invocation: CliInvocation) -> tuple[str, ...]:
        return ("exec", invocation.request_id, "PROMPT-MARKER")

    with pytest.raises(RegistryError, match="prompt content in argv"):
        validate_definition(definition(build_args=leaks))


def test_a_local_egress_host_is_refused() -> None:
    for host in ("localhost", "127.0.0.1", "printer.local", "(in-process)"):
        with pytest.raises(RegistryError, match="never local"):
            validate_definition(definition(egress_host=host))


def test_unknown_external_egress_uses_the_marker_host() -> None:
    validate_definition(definition(egress="unknown_external", egress_host=UNKNOWN_EXTERNAL_HOST))
    with pytest.raises(RegistryError, match="unknown_external"):
        validate_definition(definition(egress="unknown_external", egress_host="example.test"))


def test_protocol_and_transport_must_agree() -> None:
    with pytest.raises(RegistryError, match="transport"):
        validate_definition(definition(protocol="pi_rpc", json_events_variant=None, transport="stdin_text"))
    with pytest.raises(RegistryError, match="json_events_variant"):
        validate_definition(definition(json_events_variant=None))
    with pytest.raises(RegistryError, match="json_events_variant"):
        validate_definition(definition(protocol="claude_stream", json_events_variant="codex"))


def test_a_definition_without_a_registered_parser_is_refused() -> None:
    with pytest.raises(RegistryError, match="no parser"):
        validate_definition(definition(protocol="json_events"), parsers={})


def test_lookup_names_the_known_ids() -> None:
    registry = build_registry([definition()])
    assert registry["fake"].name == "Fake CLI"
    with pytest.raises(UnknownRuntimeError, match="unknown runtime 'nope' \\(known: fake\\)"):
        get_runtime("nope", registry=registry)


def test_the_shipped_registry_is_importable_and_ordered() -> None:
    from research_harness.providers.cli.registry import RUNTIME_DEFS, RUNTIME_IDS, RUNTIMES

    assert list(RUNTIMES) == list(RUNTIME_IDS) == [item.id for item in RUNTIME_DEFS]
    assert Path("open-design").is_dir() or True  # the submodule is documentation; never imported
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/providers/cli -q`
Expected: FAIL — `ModuleNotFoundError: research_harness.providers.cli`.

- [ ] **Step 3: Write `types.py`**

```python
"""Immutable contracts for subscription-backed local CLI runtimes (CLI providers spec §8, §10).

A runtime definition is data plus pure builders. Nothing here spawns a process, reads a
credential, or touches the workspace: `detection.py` and `process.py` own behaviour, and
`registry.py` refuses a definition that carries anything but data. "Local CLI" names where
the *client process* starts, not where inference happens (spec §4): every definition
declares an external egress host, and `UNKNOWN_EXTERNAL_HOST` when it cannot name one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "DEFAULT_MODEL",
    "UNKNOWN_EXTERNAL_HOST",
    "ArgBuilder",
    "AuthClassifier",
    "AuthStatus",
    "BoundedMode",
    "BoundedPosture",
    "CliInvocation",
    "CliModelOption",
    "CliModelView",
    "CliRuntimeDef",
    "CliRuntimeStatus",
    "Compatibility",
    "EgressKind",
    "JsonEventsVariant",
    "ModelParser",
    "ModelSource",
    "Probe",
    "ProbeOutcome",
    "PromptTransport",
    "ProtocolFamily",
    "VersionParser",
    "unavailable_reason",
]

AuthStatus = Literal["ok", "missing", "unknown"]
BoundedMode = Literal["safe", "unsupported", "unknown"]
Compatibility = Literal["verified", "warning", "blocked", "unknown"]
ModelSource = Literal["live", "fallback"]
PromptTransport = Literal["stdin_text", "stdin_jsonl", "pi_rpc", "dsh_profile"]
ProtocolFamily = Literal["claude_stream", "json_events", "dsh_profile", "pi_rpc"]
JsonEventsVariant = Literal["codex", "cursor_agent", "opencode"]
EgressKind = Literal["external", "unknown_external"]

UNKNOWN_EXTERNAL_HOST = "unknown.external"
"""The host a definition declares when the exact destination cannot be established before
execution. Host-shaped on purpose: `privacy.policy.is_local_endpoint` treats a value that
starts with `(` as an in-process marker, and this must never read as local."""

DEFAULT_MODEL = "default"
"""The model id meaning "whatever the CLI is configured to use"; no `--model` flag is sent."""


@dataclass(frozen=True, slots=True)
class Probe:
    """One side-effect-free subprocess call: arguments and a bounded timeout."""

    args: tuple[str, ...]
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("a probe timeout must be positive")


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    """What one probe produced. `os_error` set means the process never started."""

    argv: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    os_error: str | None = None

    @property
    def started(self) -> bool:
        return self.os_error is None

    @property
    def text(self) -> str:
        """stdout and stderr together, for classifiers that read either."""
        return f"{self.stdout}\n{self.stderr}"


@dataclass(frozen=True, slots=True)
class CliModelOption:
    """One model a runtime offers; `reasoning` are the effort names it accepts for it."""

    id: str
    label: str
    reasoning: tuple[str, ...] = ()
    context_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class BoundedPosture:
    """How a runtime is kept from touching anything (spec §12).

    `native_flags`: argv flags deny tools/writes; `native_env`: an environment-injected
    configuration denies them; `none`: no tested posture, so the runtime is never spawned
    for research. `required_help_flags` are substrings the help probe must print for the
    posture to count as proven on the installed version.
    """

    kind: Literal["native_flags", "native_env", "none"]
    help_probe: Probe | None = None
    required_help_flags: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class CliInvocation:
    """Everything a pure argument builder may know about one bounded request.

    No prompt and no research content: those travel through stdin or the RPC channel.
    `schema_path` is the one file the engine writes into the temp cwd.
    """

    model: str | None
    reasoning: str | None
    cwd: Path
    request_id: str
    schema_path: Path | None = None


ArgBuilder = Callable[[CliInvocation], tuple[str, ...]]
VersionParser = Callable[[ProbeOutcome], "str | None"]
AuthClassifier = Callable[[ProbeOutcome], "tuple[AuthStatus, str]"]
ModelParser = Callable[[ProbeOutcome], "tuple[CliModelOption, ...] | None"]


@dataclass(frozen=True, slots=True)
class CliRuntimeDef:
    """One supported CLI, as data (spec §8). See `registry.validate_definition`."""

    id: str
    name: str
    executable: str
    version_probe: Probe
    parse_version: VersionParser
    protocol: ProtocolFamily
    transport: PromptTransport
    build_args: ArgBuilder
    posture: BoundedPosture
    egress: EgressKind
    egress_host: str
    default_context_tokens: int
    login_guidance: str
    upstream_source: str
    fallback_executables: tuple[str, ...] = ()
    auth_probe: Probe | None = None
    classify_auth: AuthClassifier | None = None
    model_probe: Probe | None = None
    parse_models: ModelParser | None = None
    fallback_models: tuple[CliModelOption, ...] = ()
    reasoning_choices: tuple[str, ...] = ()
    json_events_variant: JsonEventsVariant | None = None
    structured_output: bool = True
    verified_versions: tuple[str, ...] = ()
    blocked_versions: tuple[str, ...] = ()
    minimum_version: str | None = None
    env_keep: tuple[str, ...] = ()
    env_drop: tuple[str, ...] = ()
    env_set: Mapping[str, str] = field(default_factory=dict)
    notes: str = ""


class CliModelView(BaseModel):
    """One model choice as a scan reports it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    reasoning: tuple[str, ...] = ()
    context_tokens: int | None = None


class CliRuntimeStatus(BaseModel):
    """What one scan found for one runtime (spec §10). Never carries a secret."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime: str
    name: str
    available: bool
    executable: str | None
    """The resolved path with the home directory replaced by `~`."""
    version: str | None
    auth_status: AuthStatus
    auth_guidance: str
    bounded_mode: BoundedMode
    compatibility: Compatibility
    models: tuple[CliModelView, ...]
    model_source: ModelSource
    reasoning_choices: tuple[str, ...]
    egress_kind: EgressKind
    egress_host: str
    diagnostics: tuple[str, ...]
    scanned_at: datetime

    @property
    def routable(self) -> bool:
        """Installed, not known to be logged out, provably bounded, not a blocked version."""
        return (
            self.available
            and self.auth_status != "missing"
            and self.bounded_mode == "safe"
            and self.compatibility != "blocked"
        )


def unavailable_reason(status: CliRuntimeStatus) -> str | None:
    """The first gate that stops this runtime from being routed, as one sentence."""
    label = status.runtime if status.version is None else f"{status.runtime} {status.version}"
    if not status.available:
        return f"{status.runtime} is not installed on this workstation"
    if status.auth_status == "missing":
        return f"{status.runtime} is not logged in: {status.auth_guidance}"
    if status.bounded_mode == "unsupported":
        return f"{label} has no tested bounded (no-tools, read-only) mode"
    if status.bounded_mode == "unknown":
        return f"{label} could not prove a bounded (no-tools, read-only) mode"
    if status.compatibility == "blocked":
        return f"{label} is a known-incompatible version"
    return None
```

- [ ] **Step 4: Write `errors.py`**

```python
"""CLI failure classification and redaction (CLI providers spec §15, §19).

Runtime outcomes map onto the existing provider errors so nothing above `providers/`
learns a new exception; each carries a `diagnostic` code and the runtime id for triage.
Every message passes `redact()`: it names runtime, model, version and a next action, and
never a token, a credential path, a raw environment value, or a whole stderr transcript.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from research_harness.providers.models.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTransportError,
)

__all__ = [
    "PROVIDER_NAME_PREFIX",
    "CliAuthError",
    "CliRateLimitError",
    "CliResponseError",
    "CliTransportError",
    "DiagnosticCode",
    "classify_failure",
    "describe_runtime",
    "provider_name",
    "redact",
]

PROVIDER_NAME_PREFIX = "local_cli"

DiagnosticCode = Literal[
    "executable_missing",
    "not_executable",
    "login_missing",
    "rate_limited",
    "timeout",
    "crashed",
    "malformed_stream",
    "missing_terminal_event",
    "output_limit",
    "refusal",
    "unsupported_model",
    "invalid_invocation",
    "empty_response",
    "bounded_authority_violation",
    "bounded_mode_unsupported",
    "version_blocked",
    "cancelled",
    "protocol_error",
]


def provider_name(runtime: str) -> str:
    """`local_cli:<runtime>` — the adapter name provenance and `--provider` see."""
    return f"{PROVIDER_NAME_PREFIX}:{runtime}"


class CliAuthError(ProviderAuthError):
    def __init__(self, message: str, *, runtime: str, diagnostic: str) -> None:
        super().__init__(message, provider=provider_name(runtime))
        self.runtime = runtime
        self.diagnostic = diagnostic


class CliRateLimitError(ProviderRateLimitError):
    def __init__(
        self, message: str, *, runtime: str, diagnostic: str, retry_after_seconds: float | None = None
    ) -> None:
        super().__init__(message, provider=provider_name(runtime), retry_after_seconds=retry_after_seconds)
        self.runtime = runtime
        self.diagnostic = diagnostic


class CliTransportError(ProviderTransportError):
    def __init__(self, message: str, *, runtime: str, diagnostic: str) -> None:
        super().__init__(message, provider=provider_name(runtime))
        self.runtime = runtime
        self.diagnostic = diagnostic


class CliResponseError(ProviderResponseError):
    def __init__(self, message: str, *, runtime: str, diagnostic: str) -> None:
        super().__init__(message, provider=provider_name(runtime))
        self.runtime = runtime
        self.diagnostic = diagnostic


# -- redaction ---------------------------------------------------------------

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer <redacted>"),
    (re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}"), "<redacted>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "<redacted>"),
    (re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"), "<redacted>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"\?(?=[^\s]*(?:X-Amz-Signature|signature|sig|token)=)[^\s]*"), "?<signed-query>"),
    (re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/=_-]{40,}(?![A-Za-z0-9+/=])"), "<redacted>"),
)


def redact(text: str, *, home: str | None = None) -> str:
    """Strip home paths, tokens, e-mails, and signed URLs from a diagnostic string."""
    cleaned = text
    for candidate in (home, str(Path.home())):
        if candidate and candidate not in ("/", ""):
            cleaned = cleaned.replace(candidate, "~")
    for pattern, replacement in _PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def describe_runtime(runtime: str, model: str, version: str | None) -> str:
    """`codex/gpt-5.5 (0.150.1)` — the identity every message starts with."""
    return f"{runtime}/{model} ({version or 'version unknown'})"


# -- classification -----------------------------------------------------------

_AUTH = re.compile(
    r"not logged[ _-]?in|login required|please (?:sign|log)[ _-]?in|run (?:/login|`?\w+ login)"
    r"|unauthori[sz]ed|authenticat|invalid[ _-]?(?:api[ _-]?)?key|token (?:has )?expired"
    r"|session expired|\b401\b|credentials? (?:are )?(?:missing|invalid|required)",
    re.IGNORECASE,
)
_RATE = re.compile(
    r"rate[ _-]?limit|too many requests|\b429\b|quota|usage limit|over capacity|overloaded|\b503\b",
    re.IGNORECASE,
)
_MODEL = re.compile(
    r"unknown model|model not found|unsupported model|invalid model|no such model|not available for",
    re.IGNORECASE,
)
_INVOCATION = re.compile(
    r"unexpected argument|unknown option|unrecognized (?:option|argument)|invalid value|usage:",
    re.IGNORECASE,
)


def classify_failure(
    *,
    runtime: str,
    model: str,
    version: str | None,
    exit_code: int | None = None,
    stderr_tail: str = "",
    timed_out: bool = False,
    output_limited: bool = False,
    os_error: str | None = None,
    stream_error: str | None = None,
    stream_code: str | None = None,
    login_guidance: str | None = None,
    home: str | None = None,
) -> ProviderError:
    """Map one runtime outcome onto a provider error with a diagnostic code (spec §15).

    Structured evidence first (`os_error`, `timed_out`, `output_limited`, a stream error
    with a code), narrowly tested text patterns second, and a generic transport failure
    last. The message names the runtime, model, and version, and a safe next action.
    """
    who = describe_runtime(runtime, model, version)
    login = login_guidance or f"run `{runtime} login`"
    detail = redact(stderr_tail.strip()[-400:], home=home)
    suffix = f": {detail}" if detail else ""

    if os_error is not None:
        code = "not_executable" if "EACCES" in os_error or "permission" in os_error.lower() else "executable_missing"
        action = "check the file's permissions" if code == "not_executable" else f"install {runtime} or fix PATH"
        return CliTransportError(f"{who}: the executable could not be started ({redact(os_error, home=home)}); {action}", runtime=runtime, diagnostic=code)
    if timed_out:
        return CliTransportError(f"{who}: the request timed out; raise `timeout_seconds` for this provider or try a smaller model{suffix}", runtime=runtime, diagnostic="timeout")
    if output_limited:
        return CliTransportError(f"{who}: the process wrote more output than the harness accepts and was stopped", runtime=runtime, diagnostic="output_limit")

    evidence = f"{stream_error or ''}\n{stderr_tail}"
    if stream_code == "authentication_failed" or _AUTH.search(evidence):
        return CliAuthError(f"{who}: not logged in; {login}", runtime=runtime, diagnostic="login_missing")
    if _RATE.search(evidence):
        return CliRateLimitError(f"{who}: the subscription is rate-limited or over quota; wait and retry{suffix}", runtime=runtime, diagnostic="rate_limited")
    if _MODEL.search(evidence):
        return CliResponseError(f"{who}: the CLI does not offer this model; run `research providers scan` for the models it lists{suffix}", runtime=runtime, diagnostic="unsupported_model")
    if stream_error is not None:
        code = stream_code if stream_code in ("refusal", "protocol_error", "cancelled") else "refusal"
        return CliResponseError(f"{who}: the runtime reported an error: {redact(stream_error, home=home)}", runtime=runtime, diagnostic=code)
    if _INVOCATION.search(evidence):
        return CliResponseError(f"{who}: the installed version rejected the harness's arguments; this version is not compatible with the recorded definition{suffix}", runtime=runtime, diagnostic="invalid_invocation")
    if exit_code == 0:
        return CliTransportError(f"{who}: the process exited before reporting a completed turn{suffix}", runtime=runtime, diagnostic="missing_terminal_event")
    return CliTransportError(f"{who}: the process exited with status {exit_code}{suffix}", runtime=runtime, diagnostic="crashed")
```

- [ ] **Step 5: Write `parsers/__init__.py` (vocabulary and registry; the parsers come in Task 4)**

```python
"""The small event vocabulary every CLI stream is translated into (CLI providers spec §13).

A parser turns one vendor line into zero or more `CliEvent`s. The engine consumes only
this vocabulary, so a new CLI with a known wire format is a definition plus fixtures and
no engine change. Tool calls and file writes are `tool` events: the engine never executes
them and treats one as a bounded-authority violation.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from research_harness.providers.models.base import Usage

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a cycle with types.py consumers
    from research_harness.providers.cli.types import CliRuntimeDef, ProtocolFamily

__all__ = ["PARSERS", "CliEvent", "EventKind", "EventParser", "ParserFactory", "parser_for"]

EventKind = Literal[
    "text_delta", "final_text", "usage", "model", "stop", "status", "error", "tool", "done"
]


@dataclass(frozen=True, slots=True)
class CliEvent:
    kind: EventKind
    text: str = ""
    usage: Usage | None = None
    model: str | None = None
    stop_reason: str | None = None
    status: str | None = None
    message: str | None = None
    code: str | None = None
    tool: str | None = None


class EventParser(Protocol):
    """Stateful per run: `feed` one line at a time, then `finish` at end of stream."""

    def feed(self, line: str) -> Iterable[CliEvent]: ...

    def finish(self) -> Iterable[CliEvent]: ...


ParserFactory = Callable[["CliRuntimeDef"], EventParser]


class _Unimplemented:
    def __init__(self, family: str) -> None:
        self._family = family

    def feed(self, line: str) -> Iterable[CliEvent]:
        raise NotImplementedError(f"the {self._family} parser is not implemented")

    def finish(self) -> Iterable[CliEvent]:
        raise NotImplementedError(f"the {self._family} parser is not implemented")


PARSERS: dict[str, ParserFactory] = {
    family: (lambda definition, family=family: _Unimplemented(family))
    for family in ("claude_stream", "json_events", "dsh_profile", "pi_rpc")
}
"""Protocol family → parser factory. The four parser modules replace their entry on import
(`register` below); `registry.validate_definition` refuses a family with no entry."""


def register(family: ProtocolFamily, factory: ParserFactory) -> None:
    PARSERS[family] = factory


def parser_for(definition: CliRuntimeDef) -> EventParser:
    return PARSERS[definition.protocol](definition)
```

- [ ] **Step 6: Write `registry.py` and `defs/__init__.py`**

`defs/__init__.py` (Task 7 and Task 9 append to it):

```python
"""The shipped runtime definitions, in display order (CLI providers spec §9)."""

from __future__ import annotations

from research_harness.providers.cli.types import CliRuntimeDef

__all__ = ["SHIPPED_DEFS"]

SHIPPED_DEFS: tuple[CliRuntimeDef, ...] = ()
```

`registry.py`:

```python
"""The runtime registry: shipped definitions, validated once, looked up by id (spec §8).

Construction fails immediately on a duplicate id, a missing parser, an argument builder
that is not pure data, a bypass flag, a local egress host, or research content in argv —
so an unsafe definition cannot be loaded, let alone spawned (spec §12).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from research_harness.privacy.policy import is_local_endpoint
from research_harness.providers.cli import parsers as _parsers
from research_harness.providers.cli.types import (
    UNKNOWN_EXTERNAL_HOST,
    CliInvocation,
    CliRuntimeDef,
)

__all__ = [
    "FORBIDDEN_ARGS",
    "RUNTIMES",
    "RUNTIME_DEFS",
    "RUNTIME_IDS",
    "SAMPLE_INVOCATIONS",
    "RegistryError",
    "UnknownRuntimeError",
    "build_registry",
    "get_runtime",
    "validate_definition",
]

FORBIDDEN_ARGS: frozenset[str] = frozenset(
    {
        "--dangerously-skip-permissions",
        "--dangerously-allow-all",
        "--dangerously-bypass-approvals-and-sandbox",
        "--allow-dangerously-skip-permissions",
        "--approve-for-me",
        "--force",
        "--trust",
        "bypassPermissions",
        "danger-full-access",
        "workspace-write",
    }
)
"""Flags Open Design uses to run a *full* agent. Never in a bounded definition (spec §12)."""

_SHELL_OPERATORS = frozenset({";", "&&", "||", "|", ">", ">>", "<", "`"})
_PROMPT_MARKER = "PROMPT-MARKER"

SAMPLE_INVOCATIONS: tuple[CliInvocation, ...] = (
    CliInvocation(model=None, reasoning=None, cwd=Path("/tmp/rh-cli-sample"), request_id="req-sample"),
    CliInvocation(
        model="sample-model",
        reasoning="high",
        cwd=Path("/tmp/rh-cli-sample"),
        request_id="req-sample",
        schema_path=Path("/tmp/rh-cli-sample/response.schema.json"),
    ),
)
"""Invocations every builder is exercised with at registry construction."""

_TRANSPORTS_FOR_PROTOCOL: Mapping[str, frozenset[str]] = {
    "claude_stream": frozenset({"stdin_text", "stdin_jsonl"}),
    "json_events": frozenset({"stdin_text"}),
    "dsh_profile": frozenset({"dsh_profile"}),
    "pi_rpc": frozenset({"pi_rpc"}),
}


class RegistryError(ValueError):
    """A definition is not pure, bounded data."""


class UnknownRuntimeError(KeyError):
    """No definition with that id."""

    def __init__(self, runtime: str, known: Sequence[str]) -> None:
        super().__init__(runtime)
        self.runtime = runtime
        self.message = f"unknown runtime {runtime!r} (known: {', '.join(known) or 'none'})"

    def __str__(self) -> str:
        return self.message


def validate_definition(
    definition: CliRuntimeDef, *, parsers: Mapping[str, object] | None = None
) -> None:
    """Refuse a definition that is not data, or not bounded (spec §8, §12)."""
    known_parsers = _parsers.PARSERS if parsers is None else parsers
    name = definition.id
    if not name or not name.replace("-", "").isalnum() or not name[0].isalpha() or name != name.lower():
        raise RegistryError(f"runtime id {name!r} must be lowercase letters, digits and dashes")
    if definition.protocol not in known_parsers:
        raise RegistryError(f"runtime {name!r}: no parser is registered for protocol {definition.protocol!r}")
    if definition.transport not in _TRANSPORTS_FOR_PROTOCOL[definition.protocol]:
        raise RegistryError(
            f"runtime {name!r}: transport {definition.transport!r} does not carry protocol {definition.protocol!r}"
        )
    if (definition.protocol == "json_events") != (definition.json_events_variant is not None):
        raise RegistryError(f"runtime {name!r}: json_events_variant is required exactly when the protocol is json_events")
    if is_local_endpoint(definition.egress_host):
        raise RegistryError(f"runtime {name!r}: egress host {definition.egress_host!r} reads as local; a CLI provider is never local (spec §4)")
    if (definition.egress == "unknown_external") != (definition.egress_host == UNKNOWN_EXTERNAL_HOST):
        raise RegistryError(f"runtime {name!r}: unknown_external egress must use host {UNKNOWN_EXTERNAL_HOST!r} and nothing else may")
    if set(definition.verified_versions) & set(definition.blocked_versions):
        raise RegistryError(f"runtime {name!r}: a version cannot be both verified and blocked")
    if definition.posture.kind != "none" and definition.posture.help_probe is None:
        raise RegistryError(f"runtime {name!r}: a bounded posture must declare the help probe that proves it")
    for invocation in SAMPLE_INVOCATIONS:
        _check_args(name, definition.build_args(invocation), invocation)


def _check_args(name: str, args: object, invocation: CliInvocation) -> None:
    if not isinstance(args, tuple) or not all(isinstance(item, str) for item in args):
        raise RegistryError(f"runtime {name!r}: build_args must return a tuple of strings")
    for item in args:
        if item in FORBIDDEN_ARGS or any(token in item.split("=") for token in FORBIDDEN_ARGS):
            raise RegistryError(f"runtime {name!r}: forbidden argument {item!r}")
        if item in _SHELL_OPERATORS:
            raise RegistryError(f"runtime {name!r}: shell operator {item!r} in argv")
        if _PROMPT_MARKER in item:
            raise RegistryError(f"runtime {name!r}: prompt content in argv")
    _ = invocation


def build_registry(definitions: Sequence[CliRuntimeDef]) -> Mapping[str, CliRuntimeDef]:
    """Validate every definition and index them by id, in the order given."""
    registry: dict[str, CliRuntimeDef] = {}
    for definition in definitions:
        if definition.id in registry:
            raise RegistryError(f"duplicate runtime id {definition.id!r}")
        validate_definition(definition)
        registry[definition.id] = definition
    return MappingProxyType(registry)


def get_runtime(runtime: str, *, registry: Mapping[str, CliRuntimeDef] | None = None) -> CliRuntimeDef:
    table = RUNTIMES if registry is None else registry
    try:
        return table[runtime]
    except KeyError:
        raise UnknownRuntimeError(runtime, tuple(table)) from None


def _shipped() -> tuple[CliRuntimeDef, ...]:
    from research_harness.providers.cli.defs import SHIPPED_DEFS

    return SHIPPED_DEFS


RUNTIME_DEFS: tuple[CliRuntimeDef, ...] = _shipped()
RUNTIMES: Mapping[str, CliRuntimeDef] = build_registry(RUNTIME_DEFS)
RUNTIME_IDS: tuple[str, ...] = tuple(RUNTIMES)
```

`providers/cli/__init__.py`:

```python
"""Subscription-backed local CLI providers (CLI providers spec).

Import the contract from here::

    from research_harness.providers.cli import CliRuntimeDef, RUNTIMES, get_runtime
"""

from __future__ import annotations

from research_harness.providers.cli.errors import (
    CliAuthError,
    CliRateLimitError,
    CliResponseError,
    CliTransportError,
    provider_name,
    redact,
)
from research_harness.providers.cli.registry import (
    RUNTIME_DEFS,
    RUNTIME_IDS,
    RUNTIMES,
    RegistryError,
    UnknownRuntimeError,
    get_runtime,
)
from research_harness.providers.cli.types import (
    DEFAULT_MODEL,
    UNKNOWN_EXTERNAL_HOST,
    CliModelView,
    CliRuntimeDef,
    CliRuntimeStatus,
    unavailable_reason,
)

__all__ = [
    "DEFAULT_MODEL",
    "RUNTIMES",
    "RUNTIME_DEFS",
    "RUNTIME_IDS",
    "UNKNOWN_EXTERNAL_HOST",
    "CliAuthError",
    "CliModelView",
    "CliRateLimitError",
    "CliResponseError",
    "CliRuntimeDef",
    "CliRuntimeStatus",
    "CliTransportError",
    "RegistryError",
    "UnknownRuntimeError",
    "get_runtime",
    "provider_name",
    "redact",
    "unavailable_reason",
]
```

- [ ] **Step 7: Run the tests and the gates**

Run: `uv run pytest tests/unit/providers/cli -q && uv run ruff check src/research_harness/providers/cli tests/unit/providers/cli && uv run ruff format --check src/research_harness/providers/cli tests/unit/providers/cli && uv run mypy src`
Expected: all PASS. If `redact` misses a parametrised case, adjust the regex, not the test.

- [ ] **Step 8: Commit**

```bash
git add src/research_harness/providers/cli tests/unit/providers/cli
git commit -m "feat(cli-providers): immutable runtime contracts, diagnostics, and the validating registry"
```

---

### Task 2: Prompt rendering and environment filtering

Spec §12 (prompt, environment), §19.

**Files:**
- Create: `src/research_harness/providers/cli/prompt.py`
- Create: `src/research_harness/providers/cli/environment.py`
- Test: `tests/unit/providers/cli/test_prompt.py`, `tests/unit/providers/cli/test_environment.py`

**Interfaces:**
- Consumes: `render_inputs`, `canonical_json`, `ModelRequest` from `providers.models.base`; `CliRuntimeDef` from Task 1.
- Produces: `render_prompt(request, schema_json) -> str`, `render_chat_prompt(request) -> str`, `stream_json_user_message(prompt) -> str`, `BOUNDARY`, `OUTPUT_RULE`, `NO_INPUTS_PROMPT`; `bounded_environment(definition, base, *, executable=None) -> dict[str, str]`, `BASE_KEEP`, `ALWAYS_DROP`, `FIXED_ENV`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/providers/cli/test_prompt.py`:

```python
"""The prompt is deterministic and complete (CLI providers spec §12)."""

from __future__ import annotations

import json

from pydantic import BaseModel

from research_harness.providers.cli.prompt import (
    BOUNDARY,
    OUTPUT_RULE,
    render_chat_prompt,
    render_prompt,
    stream_json_user_message,
)
from research_harness.providers.models.base import InputEnvelope, ModelRequest, ModelRequirements


class Verdict(BaseModel):
    supported: bool
    rationale: str


def request() -> ModelRequest[Verdict]:
    return ModelRequest(
        role="evidence_verifier",
        requirements=ModelRequirements(structured_output=True, context_tokens=1000, reasoning="low"),
        instructions="Decide whether the span supports the candidate.",
        inputs=[
            InputEnvelope(object_id="W0001", kind="source_text", content="Table 3 reports 1.4 Gbps."),
            InputEnvelope(object_id=None, kind="candidate", content="throughput=1.4 Gbps"),
        ],
        response_schema=Verdict,
    )


def test_the_prompt_has_the_five_sections_in_order() -> None:
    text = render_prompt(request(), request().wire_schema())
    positions = [
        text.index("# Role: evidence_verifier"),
        text.index("Decide whether the span supports the candidate."),
        text.index("[input 1] kind=source_text object_id=W0001\nTable 3 reports 1.4 Gbps."),
        text.index("[input 2] kind=candidate\nthroughput=1.4 Gbps"),
        text.index("# Response schema (JSON Schema)"),
        text.index(json.dumps(request().wire_schema(), sort_keys=True, separators=(",", ":"))),
        text.index(OUTPUT_RULE),
        text.index(BOUNDARY),
    ]
    assert positions == sorted(positions)


def test_the_prompt_is_deterministic_and_does_not_change_the_fingerprint() -> None:
    first, second = request(), request()
    assert render_prompt(first, first.wire_schema()) == render_prompt(second, second.wire_schema())
    assert first.fingerprint() == second.fingerprint()


def test_the_boundary_forbids_every_kind_of_side_effect() -> None:
    for word in ("file system", "run commands", "edit", "create files", "URL", "tool"):
        assert word in BOUNDARY


def test_no_inputs_is_said_rather_than_left_blank() -> None:
    bare = request().model_copy(update={"inputs": []})
    assert "No research inputs were provided" in render_prompt(bare, bare.wire_schema())


def test_a_chat_prompt_asks_for_prose_and_no_schema() -> None:
    text = render_chat_prompt(request())
    assert "# Response schema" not in text and OUTPUT_RULE not in text
    assert "Answer in plain prose" in text and BOUNDARY in text


def test_the_jsonl_user_message_is_one_line_of_claude_stream_json() -> None:
    line = stream_json_user_message("hello\nworld")
    assert line.endswith("\n") and line.count("\n") == 1
    assert json.loads(line) == {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": "hello\nworld"}]},
    }
```

`tests/unit/providers/cli/test_environment.py`:

```python
"""The child environment: enough to log in, nothing that pays by the token (spec §12)."""

from __future__ import annotations

from pathlib import Path

from research_harness.providers.cli.environment import ALWAYS_DROP, FIXED_ENV, bounded_environment
from tests.unit.providers.cli.test_registry import definition

BASE = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/home/alice",
    "USER": "alice",
    "LANG": "en_US.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TMPDIR": "/tmp",
    "HTTPS_PROXY": "http://proxy.test:3128",
    "OPENAI_API_KEY": "sk-metered",
    "ANTHROPIC_API_KEY": "sk-ant-metered",
    "ANTHROPIC_AUTH_TOKEN": "tok",
    "CODEX_API_KEY": "k",
    "CURSOR_API_KEY": "k",
    "AWS_SECRET_ACCESS_KEY": "k",
    "AZURE_OPENAI_API_KEY": "k",
    "GOOGLE_APPLICATION_CREDENTIALS": "/home/alice/creds.json",
    "GITHUB_TOKEN": "ghp_x",
    "MY_SERVICE_SECRET_VALUE": "s",
    "DATABASE_URL": "postgres://u:p@h/db",
    "CODEX_HOME": "/home/alice/.codex",
    "RANDOM_THING": "1",
}


def test_only_the_allowlist_survives_and_every_credential_is_removed() -> None:
    env = bounded_environment(definition(), BASE)
    assert set(env) == {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "HTTPS_PROXY", *FIXED_ENV}
    for key in BASE:
        if any(pattern.match(key) for pattern in ALWAYS_DROP):
            assert key not in env


def test_a_definition_may_keep_its_own_config_variables_but_never_a_key() -> None:
    env = bounded_environment(definition(env_keep=("CODEX_HOME", "OPENAI_API_KEY")), BASE)
    assert env["CODEX_HOME"] == "/home/alice/.codex"
    assert "OPENAI_API_KEY" not in env, "the deny list wins over a definition's keep list"


def test_a_definition_may_drop_and_set_variables() -> None:
    env = bounded_environment(definition(env_drop=("HTTPS_PROXY",), env_set={"OPENCODE_DISABLE_PROJECT_CONFIG": "true"}), BASE)
    assert "HTTPS_PROXY" not in env
    assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "true"


def test_the_executable_directory_leads_path() -> None:
    env = bounded_environment(definition(), BASE, executable=Path("/opt/tools/bin/fake"))
    assert env["PATH"].split(":")[0] == "/opt/tools/bin"


def test_fixed_values_make_output_machine_readable() -> None:
    env = bounded_environment(definition(), BASE)
    assert env["NO_COLOR"] == "1" and env["TERM"] == "dumb" and env["RESEARCH_HARNESS_BOUNDED"] == "1"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/providers/cli/test_prompt.py tests/unit/providers/cli/test_environment.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write `prompt.py`**

```python
"""Deterministic, provider-neutral rendering of one request for a CLI (spec §12).

The same request renders to the same bytes on every runtime, and the rendering never
touches the fingerprint: `ModelRequest.fingerprint()` is computed from the request, not
from what any adapter puts on the wire. The prompt is delivered over stdin or RPC and is
never placed in argv.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from research_harness.providers.models.base import ModelRequest, canonical_json, render_inputs

__all__ = ["BOUNDARY", "NO_INPUTS_PROMPT", "OUTPUT_RULE", "render_chat_prompt", "render_prompt", "stream_json_user_message"]

NO_INPUTS_PROMPT = "No research inputs were provided; answer from the instructions alone."

OUTPUT_RULE = (
    "Return exactly one JSON object that validates against the schema above. "
    "Do not wrap it in a Markdown fence and do not write anything before or after it."
)

BOUNDARY = (
    "You are running as a bounded research worker inside Research Harness. Do not inspect "
    "the file system, do not run commands, do not edit or create files, do not open any URL, "
    "and do not call any tool. Answer only from the instructions and the inputs above."
)


def render_prompt(request: ModelRequest[Any], schema_json: Mapping[str, Any]) -> str:
    """The five sections of spec §12: role, inputs, schema, output rule, boundary."""
    return "\n\n".join(
        (
            f"# Role: {request.role}\n{request.instructions}",
            f"# Inputs\n{render_inputs(request.inputs) or NO_INPUTS_PROMPT}",
            f"# Response schema (JSON Schema)\n{canonical_json(dict(schema_json))}",
            f"# Output rule\n{OUTPUT_RULE}",
            f"# Boundary\n{BOUNDARY}",
        )
    )


def render_chat_prompt(request: ModelRequest[Any]) -> str:
    """A conversation turn: the same role, inputs and boundary, answered in prose."""
    return "\n\n".join(
        (
            f"# Role: {request.role}\n{request.instructions}",
            f"# Inputs\n{render_inputs(request.inputs) or NO_INPUTS_PROMPT}",
            "# Output rule\nAnswer in plain prose. Do not return JSON.",
            f"# Boundary\n{BOUNDARY}",
        )
    )


def stream_json_user_message(prompt: str) -> str:
    """One Claude Code `--input-format stream-json` user message, newline-terminated."""
    body = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}}
    return json.dumps(body, ensure_ascii=False) + "\n"
```

- [ ] **Step 4: Write `environment.py`**

```python
"""The environment a bounded CLI process receives (spec §12).

Allow-list first — enough to find the executable, load the user's existing CLI login, and
operate on the host — then a deny-list that always wins: provider API-key variables and
unrelated cloud credentials are removed so a subscription login never silently becomes
metered API-key access, and nothing unrelated to the run rides along.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from research_harness.providers.cli.types import CliRuntimeDef

__all__ = ["ALWAYS_DROP", "BASE_KEEP", "FIXED_ENV", "bounded_environment"]

BASE_KEEP: frozenset[str] = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TMP", "TEMP", "LANG", "LANGUAGE",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
        "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
        "SYSTEMROOT", "SystemRoot", "COMSPEC", "ComSpec", "USERPROFILE", "APPDATA",
        "LOCALAPPDATA", "PROGRAMDATA", "ProgramData", "PATHEXT", "WINDIR", "windir",
    }
)

ALWAYS_DROP: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r".*_API_KEY$", r".*_TOKEN$", r".*_SECRET.*", r"^AWS_.*", r"^AZURE_.*", r"^OPENAI_.*",
        r"^ANTHROPIC_.*", r"^GEMINI_.*", r"^GOOGLE_APPLICATION_CREDENTIALS$", r"^CODEX_API_KEY$",
        r"^CURSOR_API_KEY$", r"^DEEPSEEK_API_KEY$", r"^OPENROUTER_API_KEY$",
    )
)

FIXED_ENV: Mapping[str, str] = {"NO_COLOR": "1", "TERM": "dumb", "RESEARCH_HARNESS_BOUNDED": "1"}


def _dropped(key: str) -> bool:
    return any(pattern.match(key) for pattern in ALWAYS_DROP)


def bounded_environment(
    definition: CliRuntimeDef, base: Mapping[str, str], *, executable: Path | None = None
) -> dict[str, str]:
    """Allow-list, then deny-list (which wins), then the fixed and per-runtime values."""
    keep = BASE_KEEP | set(definition.env_keep)
    env = {
        key: value
        for key, value in base.items()
        if (key in keep or key.startswith("LC_"))
        and key not in definition.env_drop
        and not _dropped(key)
    }
    env.update(FIXED_ENV)
    env.update({key: value for key, value in definition.env_set.items() if not _dropped(key)})
    if executable is not None:
        parent = str(executable.parent)
        parts = [part for part in env.get("PATH", "").split(os.pathsep) if part and part != parent]
        env["PATH"] = os.pathsep.join([parent, *parts])
    return env
```

- [ ] **Step 5: Run the tests and gates**

Run: `uv run pytest tests/unit/providers/cli -q && uv run ruff check src tests/unit/providers/cli && uv run ruff format --check src tests/unit/providers/cli && uv run mypy src`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/research_harness/providers/cli/prompt.py src/research_harness/providers/cli/environment.py tests/unit/providers/cli/test_prompt.py tests/unit/providers/cli/test_environment.py
git commit -m "feat(cli-providers): deterministic prompt rendering and the bounded child environment"
```

---

### Task 3: The bounded process engine

Spec §12 (temp cwd), §14 (timeouts, cancellation, drain, output cap, process-tree cleanup).

**Files:**
- Create: `src/research_harness/providers/cli/process.py`
- Create: `tests/fixtures/cli/__init__.py`, `tests/fixtures/cli/fakes.py`
- Test: `tests/unit/providers/cli/test_process.py`

**Interfaces:**
- Produces: `run_probe(argv, *, env, timeout, cwd=None) -> ProbeOutcome`; `BoundedProcess` with `spawn(argv, *, env, cwd, timeout, output_limit=DEFAULT_OUTPUT_LIMIT_BYTES)`, `.write(text)`, `.close_stdin()`, `.lines() -> Iterator[str]`, `.stderr_tail() -> str`, `.wait(timeout) -> int | None`, `.cancel(grace=CANCEL_GRACE_SECONDS)`, `.exit_code`, `.running`, context manager (exit cancels if still running); exceptions `ProcessTimeout`, `OutputLimitExceeded`; constants `DEFAULT_OUTPUT_LIMIT_BYTES = 8 MiB`, `MAX_LINE_BYTES = 1 MiB`, `STDERR_TAIL_BYTES = 16 KiB`, `CANCEL_GRACE_SECONDS = 2.0`.
- Produces (`tests/fixtures/cli/fakes.py`): `FakeCli` — writes an executable Python script under `<root>/bin/<name>` driven by `<root>/script.json`, records every call to `<root>/calls.jsonl`; `FakeCli.install(tmp_path, name, *, version_stdout="fake 1.2.3", version_exit=0, probes=[...], run={...}) -> FakeCli`; `.env(base) -> dict` (PATH with `bin` first); `.calls() -> list[dict]` (each `{"kind","argv","cwd","env","stdin"}`); `.set_run(**fields)`.

- [ ] **Step 1: Write the fake executable helper**

`tests/fixtures/cli/__init__.py` is empty. `tests/fixtures/cli/fakes.py`:

```python
"""Fake CLI executables for offline tests (CLI providers spec §20).

`FakeCli.install` writes a small Python program under `<root>/bin/<name>` and a
`script.json` it reads on every invocation, so a test can decide what `--version`, an
auth probe, or a run prints, how long it takes, and whether it hangs. Every invocation
appends `{"kind", "argv", "cwd", "env", "stdin"}` to `calls.jsonl`, which is how a test
proves the prompt travelled on stdin, the API key was stripped, and the cwd was a temp dir.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROGRAM = r'''#!/usr/bin/env python3
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = json.load(open(os.path.join(ROOT, "script.json"), encoding="utf-8"))

def record(kind, stdin=None):
    with open(os.path.join(ROOT, "calls.jsonl"), "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": kind, "argv": sys.argv[1:], "cwd": os.getcwd(),
                                 "env": dict(os.environ), "stdin": stdin}) + "\n")

def emit(lines):
    for line in lines:
        if isinstance(line, dict) and "sleep" in line:
            time.sleep(line["sleep"]); continue
        sys.stdout.write(line if isinstance(line, str) else json.dumps(line))
        sys.stdout.write("\n"); sys.stdout.flush()

args = sys.argv[1:]
if args == ["--version"]:
    record("version"); sys.stdout.write(SCRIPT.get("version_stdout", "fake 1.2.3") + "\n")
    sys.stderr.write(SCRIPT.get("version_stderr", "")); sys.exit(SCRIPT.get("version_exit", 0))
for probe in SCRIPT.get("probes", []):
    if args == probe["args"]:
        record("probe"); time.sleep(probe.get("sleep", 0))
        sys.stdout.write(probe.get("stdout", "")); sys.stderr.write(probe.get("stderr", ""))
        sys.exit(probe.get("exit", 0))
run = SCRIPT.get("run", {})
emit(run.get("before_input", []))
stdin = None
if run.get("read_stdin", True):
    stdin = sys.stdin.readline() if run.get("read_one_line") else sys.stdin.read()
record("run", stdin)
emit(run.get("lines", []))
if run.get("hang"):
    time.sleep(3600)
sys.stderr.write(run.get("stderr", ""))
sys.exit(run.get("exit", 0))
'''


@dataclass
class FakeCli:
    root: Path
    name: str

    @property
    def bin_dir(self) -> Path:
        return self.root / "bin"

    @property
    def executable(self) -> Path:
        return self.bin_dir / self.name

    @classmethod
    def install(
        cls,
        root: Path,
        name: str,
        *,
        version_stdout: str = "fake 1.2.3",
        version_exit: int = 0,
        version_stderr: str = "",
        probes: list[dict[str, Any]] | None = None,
        run: dict[str, Any] | None = None,
    ) -> FakeCli:
        fake = cls(root=root, name=name)
        fake.bin_dir.mkdir(parents=True, exist_ok=True)
        fake.executable.write_text(PROGRAM.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1), encoding="utf-8")
        fake.executable.chmod(fake.executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        fake.write_script(
            {
                "version_stdout": version_stdout,
                "version_exit": version_exit,
                "version_stderr": version_stderr,
                "probes": probes or [],
                "run": run or {"lines": [], "exit": 0},
            }
        )
        return fake

    def write_script(self, script: Mapping[str, Any]) -> None:
        (self.root / "script.json").write_text(json.dumps(script), encoding="utf-8")

    def script(self) -> dict[str, Any]:
        return dict(json.loads((self.root / "script.json").read_text(encoding="utf-8")))

    def set_run(self, **fields: Any) -> None:
        script = self.script()
        script["run"] = {**script.get("run", {}), **fields}
        self.write_script(script)

    def env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        source = dict(os.environ if base is None else base)
        source["PATH"] = os.pathsep.join([str(self.bin_dir), source.get("PATH", "")])
        source.setdefault("HOME", str(self.root / "home"))
        return source

    def calls(self) -> list[dict[str, Any]]:
        path = self.root / "calls.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def runs(self) -> list[dict[str, Any]]:
        return [call for call in self.calls() if call["kind"] == "run"]
```

- [ ] **Step 2: Write the failing process tests**

`tests/unit/providers/cli/test_process.py`:

```python
"""Bounded spawn, drain, limits, cancellation, and cleanup (CLI providers spec §14)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from research_harness.providers.cli.process import (
    CANCEL_GRACE_SECONDS,
    BoundedProcess,
    OutputLimitExceeded,
    ProcessTimeout,
    run_probe,
)
from tests.fixtures.cli.fakes import FakeCli


@pytest.fixture
def fake(tmp_path: Path) -> FakeCli:
    return FakeCli.install(tmp_path, "fake", probes=[{"args": ["slow"], "stdout": "late", "sleep": 5}])


def test_run_probe_captures_exit_code_and_both_streams(fake: FakeCli) -> None:
    outcome = run_probe((str(fake.executable), "--version"), env=fake.env(), timeout=5)
    assert outcome.started and outcome.exit_code == 0
    assert outcome.stdout.strip() == "fake 1.2.3" and not outcome.timed_out


def test_run_probe_reports_a_missing_executable_as_an_os_error(tmp_path: Path) -> None:
    outcome = run_probe((str(tmp_path / "missing"), "--version"), env={"PATH": ""}, timeout=5)
    assert not outcome.started and outcome.os_error and "ENOENT" in outcome.os_error


def test_run_probe_reports_a_non_executable_file(tmp_path: Path) -> None:
    path = tmp_path / "plain"
    path.write_text("not a program", encoding="utf-8")
    outcome = run_probe((str(path), "--version"), env={"PATH": ""}, timeout=5)
    assert not outcome.started and outcome.os_error and "EACCES" in outcome.os_error


def test_run_probe_times_out_and_kills(fake: FakeCli) -> None:
    started = time.monotonic()
    outcome = run_probe((str(fake.executable), "slow"), env=fake.env(), timeout=0.5)
    assert outcome.timed_out and time.monotonic() - started < 4


def test_lines_arrive_in_order_and_stdin_is_delivered(fake: FakeCli, tmp_path: Path) -> None:
    fake.set_run(lines=["one", "two", "three"])
    with BoundedProcess.spawn((str(fake.executable), "run"), env=fake.env(), cwd=tmp_path, timeout=10) as process:
        process.write("the prompt\n")
        process.close_stdin()
        assert list(process.lines()) == ["one", "two", "three"]
        assert process.wait(5) == 0
    assert fake.runs()[0]["stdin"] == "the prompt\n"


def test_stderr_is_drained_concurrently_and_only_a_tail_is_kept(fake: FakeCli, tmp_path: Path) -> None:
    fake.set_run(lines=["ok"], stderr="x" * 100_000)
    with BoundedProcess.spawn((str(fake.executable), "run"), env=fake.env(), cwd=tmp_path, timeout=10) as process:
        process.close_stdin()
        assert list(process.lines()) == ["ok"]
        process.wait(5)
        assert 0 < len(process.stderr_tail()) <= 16_384


def test_the_output_cap_stops_a_runaway_process(fake: FakeCli, tmp_path: Path) -> None:
    fake.set_run(lines=["y" * 1000] * 200)
    with BoundedProcess.spawn((str(fake.executable), "run"), env=fake.env(), cwd=tmp_path, timeout=10, output_limit=50_000) as process:
        process.close_stdin()
        with pytest.raises(OutputLimitExceeded):
            for _ in process.lines():
                pass
    assert not process.running


def test_a_deadline_raises_and_the_tree_is_gone(fake: FakeCli, tmp_path: Path) -> None:
    fake.set_run(lines=["partial"], hang=True)
    with BoundedProcess.spawn((str(fake.executable), "run"), env=fake.env(), cwd=tmp_path, timeout=0.8) as process:
        process.close_stdin()
        seen: list[str] = []
        with pytest.raises(ProcessTimeout):
            for line in process.lines():
                seen.append(line)
        assert seen == ["partial"]
        process.cancel(grace=0.2)
        assert not process.running and process.exit_code is not None


def test_cancel_terminates_grandchildren(tmp_path: Path) -> None:
    """The fake spawns a child that would outlive it; the process group takes both."""
    parent = tmp_path / "parent.py"
    marker = tmp_path / "grandchild.pid"
    parent.write_text(
        "import subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(3600)'])\n"
        f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
        "print('spawned', flush=True)\n"
        "time.sleep(3600)\n",
        encoding="utf-8",
    )
    import sys

    with BoundedProcess.spawn((sys.executable, str(parent)), env={"PATH": os.environ["PATH"]}, cwd=tmp_path, timeout=10) as process:
        assert next(process.lines()) == "spawned"
        pid = int(marker.read_text())
        process.cancel(grace=0.2)
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_exiting_the_context_cancels_a_running_process(fake: FakeCli, tmp_path: Path) -> None:
    fake.set_run(hang=True)
    with BoundedProcess.spawn((str(fake.executable), "run"), env=fake.env(), cwd=tmp_path, timeout=10) as process:
        process.close_stdin()
    assert not process.running


def test_the_default_grace_is_short() -> None:
    assert CANCEL_GRACE_SECONDS == 2.0
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/unit/providers/cli/test_process.py -q`
Expected: FAIL — `ModuleNotFoundError: research_harness.providers.cli.process`.

- [ ] **Step 4: Write `process.py`**

```python
"""One bounded subprocess: spawn, drain, limit, cancel, clean up (CLI providers spec §14).

Both pipes are drained by threads so a chatty stderr cannot deadlock stdout. Output is
capped, every read has a deadline, and cancellation closes stdin, terminates the whole
process group (POSIX) or tree (Windows), and kills after a short grace. Nothing here
persists a byte: stdout lines go to the caller, stderr keeps only a bounded tail.
"""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import TracebackType
from typing import IO, Self

from research_harness.providers.cli.types import ProbeOutcome

__all__ = [
    "CANCEL_GRACE_SECONDS",
    "DEFAULT_OUTPUT_LIMIT_BYTES",
    "MAX_LINE_BYTES",
    "STDERR_TAIL_BYTES",
    "BoundedProcess",
    "OutputLimitExceeded",
    "ProcessTimeout",
    "run_probe",
]

DEFAULT_OUTPUT_LIMIT_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 1024 * 1024
STDERR_TAIL_BYTES = 16 * 1024
CANCEL_GRACE_SECONDS = 2.0
_WINDOWS = sys.platform == "win32"


class ProcessTimeout(Exception):
    """The deadline passed before the stream ended."""


class OutputLimitExceeded(Exception):
    """The process wrote more than the cap allows."""


def _os_error_text(exc: OSError) -> str:
    name = getattr(exc, "strerror", None) or type(exc).__name__
    code = os.strerror(exc.errno) if exc.errno else ""
    tag = {2: "ENOENT", 13: "EACCES", 20: "ENOTDIR", 8: "ENOEXEC"}.get(exc.errno or 0, "OSError")
    return f"{tag}: {name or code}"


def _popen_kwargs() -> dict[str, object]:
    if _WINDOWS:  # pragma: no cover - exercised on Windows only
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree(process: subprocess.Popen[bytes], *, force: bool) -> None:
    if process.poll() is not None and not force:
        return
    if _WINDOWS:  # pragma: no cover - exercised on Windows only
        flag = ["/F"] if force else []
        subprocess.run(["taskkill", "/T", *flag, "/PID", str(process.pid)], capture_output=True, check=False)
        return
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return
    except PermissionError:  # pragma: no cover - a foreign group; fall back to the child
        process.send_signal(sig)


def run_probe(
    argv: tuple[str, ...], *, env: Mapping[str, str], timeout: float, cwd: Path | None = None
) -> ProbeOutcome:
    """Run a short side-effect-free probe to completion, killing its tree on timeout."""
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd) if cwd else None,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_popen_kwargs(),  # type: ignore[arg-type]
        )
    except OSError as exc:
        return ProbeOutcome(argv=argv, exit_code=None, stdout="", stderr="", os_error=_os_error_text(exc))
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(process, force=True)
        out, err = process.communicate()
        return ProbeOutcome(argv=argv, exit_code=process.returncode, stdout=_text(out), stderr=_text(err), timed_out=True)
    return ProbeOutcome(argv=argv, exit_code=process.returncode, stdout=_text(out), stderr=_text(err))


def _text(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace")


class BoundedProcess:
    """A running CLI with a deadline, an output cap, and process-tree cancellation."""

    def __init__(self, process: subprocess.Popen[bytes], *, timeout: float, output_limit: int) -> None:
        self._process = process
        self._deadline = time.monotonic() + timeout
        self._limit = output_limit
        self._lines: queue.Queue[str | Exception | None] = queue.Queue()
        self._stderr: deque[bytes] = deque()
        self._stderr_bytes = 0
        self._bytes_read = 0
        self._stdin_closed = False
        assert process.stdout is not None and process.stderr is not None
        self._readers = (
            threading.Thread(target=self._drain_stdout, args=(process.stdout,), daemon=True),
            threading.Thread(target=self._drain_stderr, args=(process.stderr,), daemon=True),
        )
        for reader in self._readers:
            reader.start()

    @classmethod
    def spawn(
        cls,
        argv: tuple[str, ...],
        *,
        env: Mapping[str, str],
        cwd: Path,
        timeout: float,
        output_limit: int = DEFAULT_OUTPUT_LIMIT_BYTES,
    ) -> BoundedProcess:
        process = subprocess.Popen(
            list(argv),
            cwd=str(cwd),
            env=dict(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_popen_kwargs(),  # type: ignore[arg-type]
        )
        return cls(process, timeout=timeout, output_limit=output_limit)

    # -- stdin ---------------------------------------------------------------

    def write(self, text: str) -> None:
        stdin = self._process.stdin
        if stdin is None or self._stdin_closed:
            return
        try:
            stdin.write(text.encode("utf-8"))
            stdin.flush()
        except (BrokenPipeError, OSError):
            self._stdin_closed = True

    def close_stdin(self) -> None:
        stdin = self._process.stdin
        if stdin is not None and not self._stdin_closed:
            self._stdin_closed = True
            try:
                stdin.close()
            except OSError:
                pass

    # -- stdout --------------------------------------------------------------

    def _drain_stdout(self, stream: IO[bytes]) -> None:
        try:
            for raw in iter(stream.readline, b""):
                self._bytes_read += len(raw)
                if len(raw) > MAX_LINE_BYTES or self._bytes_read > self._limit:
                    self._lines.put(OutputLimitExceeded())
                    return
                self._lines.put(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        finally:
            self._lines.put(None)

    def _drain_stderr(self, stream: IO[bytes]) -> None:
        for chunk in iter(lambda: stream.read(4096), b""):
            self._stderr.append(chunk)
            self._stderr_bytes += len(chunk)
            while self._stderr_bytes > STDERR_TAIL_BYTES and len(self._stderr) > 1:
                self._stderr_bytes -= len(self._stderr.popleft())

    def lines(self) -> Iterator[str]:
        """Yield stdout lines until EOF; raise on the deadline or the output cap."""
        while True:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise ProcessTimeout()
            try:
                item = self._lines.get(timeout=min(remaining, 0.25))
            except queue.Empty:
                continue
            if item is None:
                return
            if isinstance(item, Exception):
                self.cancel()
                raise item
            yield item

    def stderr_tail(self) -> str:
        return b"".join(self._stderr).decode("utf-8", errors="replace")[-STDERR_TAIL_BYTES:]

    # -- lifecycle -----------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._process.poll() is None

    @property
    def exit_code(self) -> int | None:
        return self._process.poll()

    def wait(self, timeout: float) -> int | None:
        try:
            return self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def cancel(self, *, grace: float = CANCEL_GRACE_SECONDS) -> None:
        """Close stdin, terminate the tree, kill it after ``grace`` seconds."""
        self.close_stdin()
        if not self.running:
            _kill_tree(self._process, force=True)  # reap grandchildren that outlived the child
            return
        _kill_tree(self._process, force=False)
        if self.wait(grace) is None:
            _kill_tree(self._process, force=True)
            self.wait(grace)
        for reader in self._readers:
            reader.join(timeout=1.0)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None) -> None:
        del exc_type, exc, tb
        if self.running:
            self.cancel()
        for stream in (self._process.stdout, self._process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
```

Notes for the implementer: `os.killpg(process.pid, …)` is correct because `start_new_session=True` makes the child its own group leader; the grandchild test proves it. If `_kill_tree` with `force=True` on an already-exited leader raises `ProcessLookupError`, that is the normal "group already gone" case and is swallowed.

- [ ] **Step 5: Run the tests and gates**

Run: `uv run pytest tests/unit/providers/cli/test_process.py -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`
Expected: PASS. The two timing tests must finish in under 5 s each.

- [ ] **Step 6: Commit**

```bash
git add src/research_harness/providers/cli/process.py tests/fixtures/cli tests/unit/providers/cli/test_process.py
git commit -m "feat(cli-providers): bounded subprocess engine with deadlines, output caps, and process-tree cancellation"
```

---
### Task 4: The four stream parsers and their fixtures

Spec §13. Vendor events become the `CliEvent` vocabulary; tool calls become `tool` events; nothing is executed.

**Files:**
- Create: `src/research_harness/providers/cli/parsers/claude_stream.py`, `json_events.py`, `dsh_profile.py`, `pi_rpc.py`
- Create: `tests/fixtures/cli/streams/claude-success.jsonl`, `claude-partial.jsonl`, `claude-tool.jsonl`, `claude-auth-failed.jsonl`, `claude-error-result.jsonl`, `amp-success.jsonl`, `codex-success.jsonl`, `codex-tool.jsonl`, `codex-failed.jsonl`, `cursor-success.jsonl`, `cursor-tool.jsonl`, `opencode-success.jsonl`, `opencode-error.jsonl`, `opencode-tool.jsonl`, `dsh-success.jsonl`, `dsh-tool.jsonl`, `dsh-failed.jsonl`, `pi-success.jsonl`, `pi-tool.jsonl`, `pi-error.jsonl`
- Test: `tests/unit/providers/cli/test_parsers.py`

**Interfaces:**
- Consumes: `CliEvent`, `register`, `EventParser` (Task 1); `usage_from`, `first_mapping`, `iter_mappings` from `providers.models.base`.
- Produces: `ClaudeStreamParser`, `JsonEventsParser(variant)`, `DshProfileParser`, `PiRpcParser`; each module calls `register(<family>, factory)` at import; `parsers/__init__.py` imports the four modules at the bottom so `PARSERS` is complete whenever the package is imported.

Fixture provenance: event shapes are ported from the pinned Open Design parsers and tests (`apps/daemon/src/runtimes/claude-stream.ts`, `json-event-stream.ts`, `agent-protocol/dsh-profile/`, `agent-protocol/pi-rpc/`, `tests/runtimes/json-event-stream.test.ts`, `tests/pi-rpc.test.ts`, `tests/agent-protocol/dsh-profile.test.ts`). Text, ids, paths and accounts are replaced; the JSON answer every success fixture carries is `{"supported": true, "confidence": 0.82, "rationale": "Table 3 states the throughput directly.", "evidence_ids": ["ev-001", "ev-002"]}` (the contract tests' `CANONICAL_JSON`). Each fixture file starts with a comment line `# source: <upstream path>@9bb4a7d; sanitized` — the parsers skip lines starting with `#`.

- [ ] **Step 1: Write the fixtures**

`claude-success.jsonl`:
```
# source: apps/daemon/src/runtimes/claude-stream.ts@9bb4a7d; sanitized
{"type":"system","subtype":"init","session_id":"sess-x","model":"claude-opus-5","tools":[]}
{"type":"assistant","message":{"id":"msg-1","role":"assistant","model":"claude-opus-5","content":[{"type":"text","text":"{\"supported\": true, \"confidence\": 0.82, \"rationale\": \"Table 3 states the throughput directly.\", \"evidence_ids\": [\"ev-001\", \"ev-002\"]}"}],"stop_reason":"end_turn","usage":{"input_tokens":1200,"output_tokens":95,"cache_read_input_tokens":400,"cache_creation_input_tokens":0}},"session_id":"sess-x"}
{"type":"result","subtype":"success","is_error":false,"duration_ms":1410,"num_turns":1,"result":"{\"supported\": true, \"confidence\": 0.82, \"rationale\": \"Table 3 states the throughput directly.\", \"evidence_ids\": [\"ev-001\", \"ev-002\"]}","session_id":"sess-x","usage":{"input_tokens":1200,"output_tokens":95,"cache_read_input_tokens":400,"cache_creation_input_tokens":0}}
```

`claude-partial.jsonl` (with `--include-partial-messages`; the answer is prose, three deltas):
```
# source: apps/daemon/src/runtimes/claude-stream.ts@9bb4a7d; sanitized
{"type":"system","subtype":"init","session_id":"sess-x","model":"claude-opus-5","tools":[]}
{"type":"stream_event","event":{"type":"message_start","message":{"id":"msg-1","model":"claude-opus-5","role":"assistant","content":[],"usage":{"input_tokens":812,"output_tokens":1}}}}
{"type":"stream_event","event":{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}}
{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Batching "}}}
{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"reduces tail latency "}}}
{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"across the pilot corpus."}}}
{"type":"stream_event","event":{"type":"content_block_stop","index":0}}
{"type":"stream_event","event":{"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":41}}}
{"type":"stream_event","event":{"type":"message_stop"}}
{"type":"assistant","message":{"id":"msg-1","role":"assistant","model":"claude-opus-5","content":[{"type":"text","text":"Batching reduces tail latency across the pilot corpus."}],"stop_reason":"end_turn","usage":{"input_tokens":812,"output_tokens":41,"cache_read_input_tokens":128}},"session_id":"sess-x"}
{"type":"result","subtype":"success","is_error":false,"duration_ms":900,"num_turns":1,"result":"Batching reduces tail latency across the pilot corpus.","session_id":"sess-x","usage":{"input_tokens":812,"output_tokens":41,"cache_read_input_tokens":128,"cache_creation_input_tokens":0}}
```

`claude-tool.jsonl`:
```
# source: apps/daemon/src/runtimes/claude-stream.ts@9bb4a7d; sanitized
{"type":"system","subtype":"init","session_id":"sess-x","model":"claude-opus-5","tools":["Bash"]}
{"type":"assistant","message":{"id":"msg-1","role":"assistant","model":"claude-opus-5","content":[{"type":"tool_use","id":"toolu-1","name":"Bash","input":{"command":"ls"}}],"stop_reason":"tool_use","usage":{"input_tokens":10,"output_tokens":5}},"session_id":"sess-x"}
```

`claude-auth-failed.jsonl`:
```
# source: apps/daemon/tests/runtimes/claude-stream-thinking.test.ts@9bb4a7d; sanitized
{"type":"assistant","error":"authentication_failed","message":{"id":"msg-auth","role":"assistant","stop_reason":"stop_sequence","content":[{"type":"text","text":"Not logged in · Please run /login"}]}}
```

`claude-error-result.jsonl`:
```
# source: apps/daemon/src/runtimes/claude-stream.ts@9bb4a7d; sanitized
{"type":"system","subtype":"init","session_id":"sess-x","model":"claude-opus-5","tools":[]}
{"type":"result","subtype":"error_during_execution","is_error":true,"duration_ms":30,"num_turns":0,"result":"Error: usage limit reached (HTTP 429)","session_id":"sess-x","usage":{"input_tokens":0,"output_tokens":0}}
```

`amp-success.jsonl` — identical structure to `claude-success.jsonl` with `"model":"amp-smart"` and `session_id` `"thread-x"`.

`codex-success.jsonl`:
```
# source: apps/daemon/src/runtimes/json-event-stream.ts@9bb4a7d (codex); sanitized
{"type":"thread.started","thread_id":"thread-x"}
{"type":"turn.started"}
{"type":"item.started","item":{"id":"item-0","type":"reasoning","text":""}}
{"type":"item.completed","item":{"id":"item-0","type":"reasoning","text":"summary"}}
{"type":"item.completed","item":{"id":"item-1","type":"agent_message","text":"{\"supported\": true, \"confidence\": 0.82, \"rationale\": \"Table 3 states the throughput directly.\", \"evidence_ids\": [\"ev-001\", \"ev-002\"]}"}}
{"type":"turn.completed","usage":{"input_tokens":1200,"cached_input_tokens":400,"output_tokens":95,"reasoning_output_tokens":64}}
```

`codex-tool.jsonl`:
```
# source: apps/daemon/src/runtimes/json-event-stream.ts@9bb4a7d (codex); sanitized
{"type":"thread.started","thread_id":"thread-x"}
{"type":"turn.started"}
{"type":"item.started","item":{"id":"item-1","type":"command_execution","command":"ls -la","status":"in_progress"}}
```

`codex-failed.jsonl`:
```
# source: apps/daemon/src/runtimes/json-event-stream.ts@9bb4a7d (codex); sanitized
{"type":"thread.started","thread_id":"thread-x"}
{"type":"turn.started"}
{"type":"error","message":"The model `gpt-nope` does not exist or you do not have access to it."}
{"type":"turn.failed","error":{"message":"The model `gpt-nope` does not exist or you do not have access to it."}}
```

`cursor-success.jsonl`:
```
# source: apps/daemon/src/runtimes/json-event-stream.ts@9bb4a7d (cursor-agent); sanitized
{"type":"system","subtype":"init","session_id":"sess-x","model":"sonnet-4","cwd":"/tmp/rh-cli-x"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"{\"supported\": true, "}]},"timestamp_ms":1}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"\"confidence\": 0.82, \"rationale\": \"Table 3 states the throughput directly.\", \"evidence_ids\": [\"ev-001\", \"ev-002\"]}"}]},"timestamp_ms":2}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"{\"supported\": true, \"confidence\": 0.82, \"rationale\": \"Table 3 states the throughput directly.\", \"evidence_ids\": [\"ev-001\", \"ev-002\"]}"}]},"model_call_id":"call-1"}
{"type":"result","subtype":"success","is_error":false,"duration_ms":1200,"result":"{\"supported\": true, \"confidence\": 0.82, \"rationale\": \"Table 3 states the throughput directly.\", \"evidence_ids\": [\"ev-001\", \"ev-002\"]}","usage":{"inputTokens":1200,"outputTokens":95,"cacheReadTokens":400,"cacheWriteTokens":0}}
```

`cursor-tool.jsonl`:
```
# source: apps/daemon/src/runtimes/json-event-stream.ts@9bb4a7d (cursor-agent); sanitized
{"type":"system","subtype":"init","session_id":"sess-x","model":"sonnet-4"}
{"type":"tool_call","subtype":"started","call_id":"call-1","tool_call":{"shellToolCall":{"args":{"command":"ls"}}}}
```

`opencode-success.jsonl`:
```
# source: apps/daemon/tests/runtimes/json-event-stream.test.ts@9bb4a7d (opencode); sanitized
{"type":"step_start","sessionID":"ses-x","part":{"type":"step-start"}}
{"type":"text","sessionID":"ses-x","part":{"type":"text","text":"{\"supported\": true, \"confidence\": 0.82, "}}
{"type":"text","sessionID":"ses-x","part":{"type":"text","text":"\"rationale\": \"Table 3 states the throughput directly.\", \"evidence_ids\": [\"ev-001\", \"ev-002\"]}"}}
{"type":"step_finish","sessionID":"ses-x","part":{"type":"step-finish","tokens":{"input":1200,"output":95,"reasoning":64,"cache":{"read":400,"write":0}},"cost":0}}
```

`opencode-error.jsonl`:
```
# source: apps/daemon/tests/runtimes/json-event-stream.test.ts@9bb4a7d (opencode); sanitized
{"type":"step_start","sessionID":"ses-x","part":{"type":"step-start"}}
{"type":"error","sessionID":"ses-x","error":{"name":"ProviderAuthError","data":{"message":"OpenCode auth failed: login required"}}}
```

`opencode-tool.jsonl`:
```
# source: apps/daemon/tests/runtimes/json-event-stream.test.ts@9bb4a7d (opencode); sanitized
{"type":"step_start","sessionID":"ses-x","part":{"type":"step-start"}}
{"type":"tool_use","sessionID":"ses-x","part":{"type":"tool","tool":"bash","callID":"call-1","state":{"status":"running","input":{"command":"ls"}}}}
```

`dsh-success.jsonl`:
```
# source: apps/daemon/src/agent-protocol/dsh-profile/types.ts@9bb4a7d; sanitized
{"v":1,"type":"ready","runtime":"open-design","protocol_version":1,"plugin_version":"0.1.1","capabilities":{"session_resume":true,"session_cancel":true,"structured_events":true}}
{"v":1,"type":"session","request_id":"req-1","session_id":"sess-x","resumed":false}
{"v":1,"type":"thinking","request_id":"req-1","content":"checking"}
{"v":1,"type":"text","request_id":"req-1","content":"{\"supported\": true, \"confidence\": 0.82, "}
{"v":1,"type":"text","request_id":"req-1","content":"\"rationale\": \"Table 3 states the throughput directly.\", \"evidence_ids\": [\"ev-001\", \"ev-002\"]}"}
{"v":1,"type":"usage","request_id":"req-1","provider":"deepseek","model":"deepseek-v3","input_tokens":1200,"output_tokens":95,"cache_read_tokens":400}
{"v":1,"type":"result","request_id":"req-1","status":"completed","session_id":"sess-x","output":"{\"supported\": true, \"confidence\": 0.82, \"rationale\": \"Table 3 states the throughput directly.\", \"evidence_ids\": [\"ev-001\", \"ev-002\"]}","stop_reason":"end_turn","resume_rejected":false}
```

`dsh-tool.jsonl`: the `ready`, `session` lines above, then
```
{"v":1,"type":"tool_call","request_id":"req-1","call_id":"call-1","name":"bash","arguments":"{\"command\":\"ls\"}"}
```

`dsh-failed.jsonl`: the `ready`, `session` lines, then
```
{"v":1,"type":"result","request_id":"req-1","status":"failed","session_id":"sess-x","resume_rejected":false,"error":{"code":"provider_error","message":"rate limit exceeded"}}
```

`pi-success.jsonl`:
```
# source: apps/daemon/tests/pi-rpc.test.ts@9bb4a7d; sanitized
{"type":"agent_start"}
{"type":"turn_start"}
{"type":"message_update","assistantMessageEvent":{"type":"text_delta","contentIndex":0,"delta":"{\"supported\": true, \"confidence\": 0.82, "}}
{"type":"message_update","assistantMessageEvent":{"type":"text_delta","contentIndex":0,"delta":"\"rationale\": \"Table 3 states the throughput directly.\", \"evidence_ids\": [\"ev-001\", \"ev-002\"]}"}}
{"type":"message_end"}
{"type":"turn_end","message":{"role":"assistant","stopReason":"stop","model":"anthropic/claude-sonnet-4-5","usage":{"input":1200,"output":95,"cacheRead":400,"cacheWrite":0,"totalTokens":1295}}}
{"type":"agent_end"}
```

`pi-tool.jsonl`:
```
# source: apps/daemon/src/agent-protocol/pi-rpc/events.ts@9bb4a7d; sanitized
{"type":"agent_start"}
{"type":"turn_start"}
{"type":"tool_execution_start","toolCallId":"call-1","toolName":"bash","args":{"command":"ls"}}
```

`pi-error.jsonl`:
```
# source: apps/daemon/src/agent-protocol/pi-rpc/events.ts@9bb4a7d; sanitized
{"type":"agent_start"}
{"type":"turn_start"}
{"type":"turn_end","message":{"role":"assistant","stopReason":"error","errorMessage":"401 unauthorized: not logged in"}}
{"type":"agent_end"}
```

- [ ] **Step 2: Write the failing parser tests**

`tests/unit/providers/cli/test_parsers.py`:

```python
"""Every vendor stream becomes the same small vocabulary (CLI providers spec §13)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.providers.cli.parsers import PARSERS, CliEvent, EventParser
from research_harness.providers.cli.parsers.claude_stream import ClaudeStreamParser
from research_harness.providers.cli.parsers.dsh_profile import DshProfileParser
from research_harness.providers.cli.parsers.json_events import JsonEventsParser
from research_harness.providers.cli.parsers.pi_rpc import PiRpcParser

STREAMS = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "cli" / "streams"
CANONICAL = (
    '{"supported": true, "confidence": 0.82, "rationale": "Table 3 states the throughput '
    'directly.", "evidence_ids": ["ev-001", "ev-002"]}'
)


def run(parser: EventParser, name: str) -> list[CliEvent]:
    events: list[CliEvent] = []
    for line in (STREAMS / name).read_text(encoding="utf-8").splitlines():
        events.extend(parser.feed(line))
    events.extend(parser.finish())
    return events


def kinds(events: list[CliEvent]) -> list[str]:
    return [event.kind for event in events]


def text_of(events: list[CliEvent]) -> str:
    finals = [event.text for event in events if event.kind == "final_text"]
    return finals[-1] if finals else "".join(e.text for e in events if e.kind == "text_delta")


SUCCESS = [
    ("claude-success.jsonl", ClaudeStreamParser, "claude-opus-5"),
    ("amp-success.jsonl", ClaudeStreamParser, "amp-smart"),
    ("codex-success.jsonl", lambda: JsonEventsParser("codex"), None),
    ("cursor-success.jsonl", lambda: JsonEventsParser("cursor_agent"), "sonnet-4"),
    ("opencode-success.jsonl", lambda: JsonEventsParser("opencode"), None),
    ("dsh-success.jsonl", DshProfileParser, "deepseek-v3"),
    ("pi-success.jsonl", PiRpcParser, "anthropic/claude-sonnet-4-5"),
]


@pytest.mark.parametrize(("name", "factory", "model"), SUCCESS, ids=[case[0] for case in SUCCESS])
def test_a_successful_stream_yields_the_answer_usage_and_a_terminal_event(name: str, factory: object, model: str | None) -> None:
    events = run(factory(), name)  # type: ignore[operator]

    assert text_of(events) == CANONICAL
    assert kinds(events)[-1] == "done"
    usage = [event.usage for event in events if event.kind == "usage"][-1]
    assert usage is not None and usage.input_tokens == 1200 and usage.output_tokens == 95
    assert usage.cached_input_tokens == 400
    if model is not None:
        assert model in {event.model for event in events if event.kind == "model"}
    assert "tool" not in kinds(events)


def test_partial_claude_messages_stream_deltas_that_concatenate_to_the_final_text() -> None:
    events = run(ClaudeStreamParser(), "claude-partial.jsonl")
    deltas = [event.text for event in events if event.kind == "text_delta"]
    assert deltas == ["Batching ", "reduces tail latency ", "across the pilot corpus."]
    assert text_of(events) == "".join(deltas)
    assert [event.stop_reason for event in events if event.kind == "stop"] == ["end_turn"]


TOOLS = [
    ("claude-tool.jsonl", ClaudeStreamParser, "Bash"),
    ("codex-tool.jsonl", lambda: JsonEventsParser("codex"), "command_execution"),
    ("cursor-tool.jsonl", lambda: JsonEventsParser("cursor_agent"), "tool_call"),
    ("opencode-tool.jsonl", lambda: JsonEventsParser("opencode"), "bash"),
    ("dsh-tool.jsonl", DshProfileParser, "bash"),
    ("pi-tool.jsonl", PiRpcParser, "bash"),
]


@pytest.mark.parametrize(("name", "factory", "tool"), TOOLS, ids=[case[0] for case in TOOLS])
def test_a_tool_call_is_reported_and_never_executed(name: str, factory: object, tool: str) -> None:
    events = run(factory(), name)  # type: ignore[operator]
    assert [event.tool for event in events if event.kind == "tool"] == [tool]
    assert "done" not in kinds(events)


ERRORS = [
    ("claude-auth-failed.jsonl", ClaudeStreamParser, "authentication_failed", "Not logged in"),
    ("claude-error-result.jsonl", ClaudeStreamParser, "error_during_execution", "429"),
    ("codex-failed.jsonl", lambda: JsonEventsParser("codex"), None, "gpt-nope"),
    ("opencode-error.jsonl", lambda: JsonEventsParser("opencode"), None, "login required"),
    ("dsh-failed.jsonl", DshProfileParser, "provider_error", "rate limit"),
    ("pi-error.jsonl", PiRpcParser, None, "401"),
]


@pytest.mark.parametrize(("name", "factory", "code", "needle"), ERRORS, ids=[case[0] for case in ERRORS])
def test_a_runtime_error_is_a_structured_error_event(name: str, factory: object, code: str | None, needle: str) -> None:
    events = run(factory(), name)  # type: ignore[operator]
    errors = [event for event in events if event.kind == "error"]
    assert errors and needle in (errors[0].message or "")
    if code is not None:
        assert errors[0].code == code
    assert "done" not in kinds(events)


def test_codex_reports_one_error_for_a_failed_turn_not_two() -> None:
    events = run(JsonEventsParser("codex"), "codex-failed.jsonl")
    assert kinds(events).count("error") == 1


def test_malformed_and_comment_lines_are_skipped_not_fatal() -> None:
    parser = JsonEventsParser("codex")
    assert list(parser.feed("# a comment")) == []
    assert list(parser.feed("not json at all")) == []
    assert list(parser.feed("")) == []


def test_opencode_needs_a_finished_step_before_it_is_done() -> None:
    parser = JsonEventsParser("opencode")
    list(parser.feed('{"type":"step_start","sessionID":"s","part":{"type":"step-start"}}'))
    list(parser.feed('{"type":"text","sessionID":"s","part":{"type":"text","text":"x"}}'))
    assert list(parser.finish()) == [], "no step_finish means no terminal event"


def test_dsh_frames_are_validated_strictly() -> None:
    parser = DshProfileParser()
    events = list(parser.feed('{"v":2,"type":"text","request_id":"r","content":"x"}'))
    assert events and events[0].kind == "error" and events[0].code == "protocol_error"


def test_every_family_is_registered() -> None:
    assert set(PARSERS) == {"claude_stream", "json_events", "dsh_profile", "pi_rpc"}
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/unit/providers/cli/test_parsers.py -q`
Expected: FAIL — the parser modules do not exist.

- [ ] **Step 4: Write the parsers**

Shared helper at the top of each module (copy it; four small modules beat a fifth import):

```python
def _load(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    try:
        value = json.loads(stripped)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None
```

`parsers/claude_stream.py`:

```python
"""Claude Code (and Amp) `--output-format stream-json` → `CliEvent` (spec §13).

Ported from the pinned Open Design `runtimes/claude-stream.ts`. Text arrives either as
`stream_event` deltas (`--include-partial-messages`) or only in the final `assistant`
wrapper; both are handled. `tool_use` blocks are `tool` events. A `result` with
`is_error` is an error, never a usage event.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from research_harness.providers.cli.parsers import CliEvent, register
from research_harness.providers.models.base import first_mapping, iter_mappings, usage_from

__all__ = ["ClaudeStreamParser"]


def _load(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    try:
        value = json.loads(stripped)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _usage(payload: Any) -> CliEvent:
    usage = first_mapping(payload)
    return CliEvent(
        kind="usage",
        usage=usage_from(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cached_input_tokens=usage.get("cache_read_input_tokens"),
        ),
    )


class ClaudeStreamParser:
    def __init__(self) -> None:
        self._final_seen = False

    def feed(self, line: str) -> Iterable[CliEvent]:
        obj = _load(line)
        if obj is None:
            return []
        kind = obj.get("type")
        if kind == "system":
            events = [CliEvent(kind="status", status=str(obj.get("subtype") or "system"))]
            if isinstance(obj.get("model"), str):
                events.append(CliEvent(kind="model", model=obj["model"]))
            return events
        if kind == "stream_event":
            return self._stream_event(first_mapping(obj.get("event")))
        if kind == "assistant":
            return self._assistant(obj)
        if kind == "result":
            return self._result(obj)
        return []

    def _stream_event(self, event: dict[str, Any]) -> list[CliEvent]:
        kind = event.get("type")
        if kind == "message_start":
            model = first_mapping(event.get("message")).get("model")
            return [CliEvent(kind="model", model=model)] if isinstance(model, str) else []
        if kind == "content_block_start":
            block = first_mapping(event.get("content_block"))
            if block.get("type") == "tool_use":
                return [CliEvent(kind="tool", tool=str(block.get("name") or "tool_use"))]
            return []
        if kind == "content_block_delta":
            delta = first_mapping(event.get("delta"))
            if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                return [CliEvent(kind="text_delta", text=delta["text"])]
            return []
        if kind == "message_delta":
            stop = first_mapping(event.get("delta")).get("stop_reason")
            return [CliEvent(kind="stop", stop_reason=stop)] if isinstance(stop, str) else []
        return []

    def _assistant(self, obj: dict[str, Any]) -> list[CliEvent]:
        message = first_mapping(obj.get("message"))
        events: list[CliEvent] = []
        if isinstance(message.get("model"), str):
            events.append(CliEvent(kind="model", model=message["model"]))
        texts: list[str] = []
        for block in iter_mappings(message.get("content")):
            if block.get("type") == "tool_use":
                events.append(CliEvent(kind="tool", tool=str(block.get("name") or "tool_use")))
            elif block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
        if isinstance(obj.get("error"), str):
            events.append(CliEvent(kind="error", message="".join(texts) or obj["error"], code=obj["error"]))
            return events
        if texts:
            self._final_seen = True
            events.append(CliEvent(kind="final_text", text="".join(texts)))
        if isinstance(message.get("stop_reason"), str):
            events.append(CliEvent(kind="stop", stop_reason=message["stop_reason"]))
        return events

    def _result(self, obj: dict[str, Any]) -> list[CliEvent]:
        if obj.get("is_error") is True:
            text = obj.get("result") if isinstance(obj.get("result"), str) else None
            code = str(obj.get("subtype") or "result_error")
            return [CliEvent(kind="error", message=text or f"Claude run failed: {code}", code=code)]
        events = [_usage(obj.get("usage"))]
        if not self._final_seen and isinstance(obj.get("result"), str) and obj["result"].strip():
            events.append(CliEvent(kind="final_text", text=obj["result"]))
        events.append(CliEvent(kind="done"))
        return events

    def finish(self) -> Iterable[CliEvent]:
        return []


register("claude_stream", lambda definition: ClaudeStreamParser())
```

`parsers/json_events.py`:

```python
"""Codex, Cursor Agent, and OpenCode JSON event streams → `CliEvent` (spec §13).

Ported from the pinned Open Design `runtimes/json-event-stream.ts`, one variant per CLI.
Codex reports its answer as `item.completed` agent messages and closes with
`turn.completed` (usage); Cursor streams timestamped assistant chunks and replays the turn
in a terminal assistant message; OpenCode has no terminal event of its own, so a finished
step at end of stream is the terminal signal.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from research_harness.providers.cli.parsers import CliEvent, register
from research_harness.providers.cli.types import JsonEventsVariant
from research_harness.providers.models.base import first_mapping, iter_mappings, usage_from

__all__ = ["JsonEventsParser"]

_CODEX_TOOL_ITEMS = frozenset({"command_execution", "file_change", "mcp_tool_call", "web_search", "tool_call"})


def _load(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    try:
        value = json.loads(stripped)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _message(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    mapping = first_mapping(value)
    for key in ("message", "error", "data", "detail"):
        inner = mapping.get(key)
        if isinstance(inner, str) and inner.strip():
            return inner
        if isinstance(inner, dict):
            found = _message(inner, "")
            if found:
                return found
    return fallback


class JsonEventsParser:
    def __init__(self, variant: JsonEventsVariant) -> None:
        self._variant = variant
        self._error_emitted = False
        self._codex_messages: list[str] = []
        self._cursor_text = ""
        self._opencode_finished = False
        self._opencode_failed = False

    def feed(self, line: str) -> Iterable[CliEvent]:
        obj = _load(line)
        if obj is None:
            return []
        if self._variant == "codex":
            return self._codex(obj)
        if self._variant == "cursor_agent":
            return self._cursor(obj)
        return self._opencode(obj)

    def finish(self) -> Iterable[CliEvent]:
        if self._variant == "opencode" and self._opencode_finished and not self._opencode_failed:
            return [CliEvent(kind="done")]
        return []

    # -- codex ---------------------------------------------------------------

    def _error_once(self, message: str, code: str | None = None) -> list[CliEvent]:
        if self._error_emitted:
            return []
        self._error_emitted = True
        return [CliEvent(kind="error", message=message, code=code)]

    def _codex(self, obj: dict[str, Any]) -> list[CliEvent]:
        kind = obj.get("type")
        if kind in ("thread.started", "turn.started"):
            return [CliEvent(kind="status", status=str(kind))]
        if kind == "error":
            return self._error_once(_message(obj.get("message") or obj.get("error"), "Codex error"))
        if kind == "turn.failed":
            return self._error_once(_message(obj.get("error") or obj.get("message"), "Codex turn failed"))
        if kind in ("item.started", "item.updated", "item.completed"):
            item = first_mapping(obj.get("item"))
            item_type = item.get("type")
            if item_type in _CODEX_TOOL_ITEMS:
                return [CliEvent(kind="tool", tool=str(item_type))]
            if kind == "item.completed" and item_type == "agent_message" and isinstance(item.get("text"), str):
                self._codex_messages.append(item["text"])
                return [CliEvent(kind="final_text", text="\n".join(self._codex_messages))]
            if kind == "item.completed" and item_type == "error" and isinstance(item.get("message"), str):
                return [CliEvent(kind="status", status=f"warning: {item['message']}")]
            return []
        if kind == "turn.completed":
            usage = first_mapping(obj.get("usage"))
            return [
                CliEvent(
                    kind="usage",
                    usage=usage_from(
                        input_tokens=usage.get("input_tokens"),
                        output_tokens=usage.get("output_tokens"),
                        cached_input_tokens=usage.get("cached_input_tokens"),
                        reasoning_tokens=usage.get("reasoning_output_tokens"),
                    ),
                ),
                CliEvent(kind="done"),
            ]
        return []

    # -- cursor agent --------------------------------------------------------

    def _cursor(self, obj: dict[str, Any]) -> list[CliEvent]:
        kind = obj.get("type")
        if kind == "system":
            events = [CliEvent(kind="status", status=str(obj.get("subtype") or "system"))]
            if isinstance(obj.get("model"), str):
                events.append(CliEvent(kind="model", model=obj["model"]))
            return events
        if kind == "tool_call":
            return [CliEvent(kind="tool", tool="tool_call")]
        if kind == "assistant":
            text = "".join(
                block["text"]
                for block in iter_mappings(first_mapping(obj.get("message")).get("content"))
                if block.get("type") == "text" and isinstance(block.get("text"), str)
            )
            if not text:
                return []
            if isinstance(obj.get("timestamp_ms"), int | float) and "model_call_id" not in obj:
                self._cursor_text += text
                return [CliEvent(kind="text_delta", text=text)]
            return [CliEvent(kind="final_text", text=text)]
        if kind == "result":
            if obj.get("is_error") is True:
                return self._error_once(_message(obj.get("result") or obj.get("error"), "Cursor Agent error"))
            usage = first_mapping(obj.get("usage"))
            events = [
                CliEvent(
                    kind="usage",
                    usage=usage_from(
                        input_tokens=usage.get("inputTokens"),
                        output_tokens=usage.get("outputTokens"),
                        cached_input_tokens=usage.get("cacheReadTokens"),
                    ),
                )
            ]
            if isinstance(obj.get("result"), str) and obj["result"].strip():
                events.append(CliEvent(kind="final_text", text=obj["result"]))
            events.append(CliEvent(kind="done"))
            return events
        return []

    # -- opencode ------------------------------------------------------------

    def _opencode(self, obj: dict[str, Any]) -> list[CliEvent]:
        kind = obj.get("type")
        part = first_mapping(obj.get("part"))
        if kind == "step_start":
            return [CliEvent(kind="status", status="running")]
        if kind == "text" and isinstance(part.get("text"), str) and part["text"]:
            return [CliEvent(kind="text_delta", text=part["text"])]
        if kind == "tool_use":
            return [CliEvent(kind="tool", tool=str(part.get("tool") or "tool"))]
        if kind == "step_finish":
            self._opencode_finished = True
            tokens = first_mapping(part.get("tokens"))
            return [
                CliEvent(
                    kind="usage",
                    usage=usage_from(
                        input_tokens=tokens.get("input"),
                        output_tokens=tokens.get("output"),
                        cached_input_tokens=first_mapping(tokens.get("cache")).get("read"),
                        reasoning_tokens=tokens.get("reasoning"),
                    ),
                )
            ]
        if kind == "error":
            self._opencode_failed = True
            return self._error_once(_message(obj.get("error") or obj.get("message"), "OpenCode error"))
        return []


register("json_events", lambda definition: JsonEventsParser(definition.json_events_variant or "codex"))
```

`parsers/dsh_profile.py`:

```python
"""DeepSeek Harness `--profile open-design --stdio` frames → `CliEvent` (spec §13).

Ported from the pinned Open Design `agent-protocol/dsh-profile/`: stdout is a
protocol-only channel, so a frame that is not generation-1 JSON is a `protocol_error`
rather than something to skip. `tool_call` frames are `tool` events.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from research_harness.providers.cli.parsers import CliEvent, register
from research_harness.providers.models.base import first_mapping, usage_from

__all__ = ["DshProfileParser"]

PROTOCOL_VERSION = 1
_TYPES = frozenset({"probe", "ready", "session", "thinking", "text", "tool_call", "tool_result", "usage", "result", "protocol_error", "models"})


class DshProfileParser:
    def feed(self, line: str) -> Iterable[CliEvent]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return []
        try:
            frame: Any = json.loads(stripped)
        except ValueError:
            return [CliEvent(kind="error", message="DeepSeek Harness profile emitted malformed JSON", code="protocol_error")]
        if not isinstance(frame, dict) or frame.get("v") != PROTOCOL_VERSION or frame.get("type") not in _TYPES:
            return [CliEvent(kind="error", message="DeepSeek Harness profile emitted an invalid frame", code="protocol_error")]
        kind = frame["type"]
        if kind in ("ready", "probe", "session"):
            return [CliEvent(kind="status", status=kind)]
        if kind == "text" and isinstance(frame.get("content"), str):
            return [CliEvent(kind="text_delta", text=frame["content"])]
        if kind == "tool_call":
            return [CliEvent(kind="tool", tool=str(frame.get("name") or "tool_call"))]
        if kind == "usage":
            events = [
                CliEvent(
                    kind="usage",
                    usage=usage_from(
                        input_tokens=frame.get("input_tokens"),
                        output_tokens=frame.get("output_tokens"),
                        cached_input_tokens=frame.get("cache_read_tokens"),
                    ),
                )
            ]
            if isinstance(frame.get("model"), str):
                events.append(CliEvent(kind="model", model=frame["model"]))
            return events
        if kind == "result":
            status = frame.get("status")
            if status == "completed":
                events: list[CliEvent] = []
                if isinstance(frame.get("output"), str) and frame["output"].strip():
                    events.append(CliEvent(kind="final_text", text=frame["output"]))
                if isinstance(frame.get("stop_reason"), str):
                    events.append(CliEvent(kind="stop", stop_reason=frame["stop_reason"]))
                events.append(CliEvent(kind="done"))
                return events
            error = first_mapping(frame.get("error"))
            code = str(error.get("code") or ("cancelled" if status == "cancelled" else "failed"))
            message = str(error.get("message") or f"DeepSeek Harness run {status}")
            return [CliEvent(kind="error", message=message, code=code)]
        if kind == "protocol_error":
            return [CliEvent(kind="error", message=str(frame.get("message") or "protocol error"), code="protocol_error")]
        return []

    def finish(self) -> Iterable[CliEvent]:
        return []


register("dsh_profile", lambda definition: DshProfileParser())
```

`parsers/pi_rpc.py`:

```python
"""Pi `--mode rpc` events → `CliEvent` (spec §13).

Ported from the pinned Open Design `agent-protocol/pi-rpc/events.ts`. The answer streams
as `message_update` text deltas; `turn_end` carries usage and the model; `agent_end` is
the terminal event. `tool_execution_start` is a `tool` event.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from research_harness.providers.cli.parsers import CliEvent, register
from research_harness.providers.models.base import first_mapping, usage_from

__all__ = ["PiRpcParser"]


def _load(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    try:
        value = json.loads(stripped)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


class PiRpcParser:
    def __init__(self) -> None:
        self._failed = False

    def feed(self, line: str) -> Iterable[CliEvent]:
        obj = _load(line)
        if obj is None:
            return []
        kind = obj.get("type")
        if kind in ("agent_start", "turn_start", "compaction_start", "auto_retry_start"):
            return [CliEvent(kind="status", status=str(kind))]
        if kind == "message_update":
            event = first_mapping(obj.get("assistantMessageEvent"))
            if event.get("type") == "text_delta" and isinstance(event.get("delta"), str):
                return [CliEvent(kind="text_delta", text=event["delta"])]
            if event.get("type") == "error":
                self._failed = True
                return [CliEvent(kind="error", message=str(event.get("reason") or event.get("delta") or "Pi agent error"))]
            return []
        if kind == "tool_execution_start":
            return [CliEvent(kind="tool", tool=str(obj.get("toolName") or "tool"))]
        if kind == "turn_end":
            message = first_mapping(obj.get("message"))
            usage = first_mapping(message.get("usage"))
            events: list[CliEvent] = []
            if usage:
                events.append(
                    CliEvent(
                        kind="usage",
                        usage=usage_from(
                            input_tokens=usage.get("input"),
                            output_tokens=usage.get("output"),
                            cached_input_tokens=usage.get("cacheRead"),
                        ),
                    )
                )
            if isinstance(message.get("model"), str):
                events.append(CliEvent(kind="model", model=message["model"]))
            if message.get("stopReason") == "error":
                self._failed = True
                events.append(CliEvent(kind="error", message=str(message.get("errorMessage") or "Pi agent error")))
            elif isinstance(message.get("stopReason"), str):
                events.append(CliEvent(kind="stop", stop_reason=message["stopReason"]))
            return events
        if kind in ("extension_error",) or (kind == "auto_retry_end" and obj.get("success") is False):
            self._failed = True
            return [CliEvent(kind="error", message=str(obj.get("error") or obj.get("finalError") or "Pi error"))]
        if kind == "agent_end":
            return [] if self._failed else [CliEvent(kind="done")]
        return []

    def finish(self) -> Iterable[CliEvent]:
        return []


register("pi_rpc", lambda definition: PiRpcParser())
```

Then, at the very bottom of `parsers/__init__.py`, add (after `parser_for`):

```python
# Register the four parsers by importing them; each module calls `register` on import.
from research_harness.providers.cli.parsers import (  # noqa: E402 - registration side effect
    claude_stream as _claude_stream,
    dsh_profile as _dsh_profile,
    json_events as _json_events,
    pi_rpc as _pi_rpc,
)

del _claude_stream, _dsh_profile, _json_events, _pi_rpc
```

Remove the `_Unimplemented` seeding from Task 1 once the four modules exist (the registry test `test_a_definition_without_a_registered_parser_is_refused` passes `parsers={}` explicitly, so it still holds).

- [ ] **Step 5: Run the tests and gates**

Run: `uv run pytest tests/unit/providers/cli -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/research_harness/providers/cli/parsers tests/fixtures/cli/streams tests/unit/providers/cli/test_parsers.py
git commit -m "feat(cli-providers): stream parsers for Claude/Amp, Codex/Cursor/OpenCode, DeepSeek Harness, and Pi with sanitized fixtures"
```

---

### Task 5: Prompt transports

Spec §12 (stdin / JSONL / RPC delivery), §14 (protocol-level cancel before the tree kill).

**Files:**
- Create: `src/research_harness/providers/cli/transport.py`
- Test: `tests/unit/providers/cli/test_transport.py`

**Interfaces:**
- Consumes: `BoundedProcess` (`write`, `close_stdin`), `CliEvent`, `CliInvocation`, `stream_json_user_message`.
- Produces: `Transport` protocol — `start(process, prompt, invocation)`, `observe(process, event)`, `intercept(process, line) -> bool`, `cancel(process)`; classes `StdinTextTransport`, `StdinJsonlTransport`, `PiRpcTransport`, `DshProfileTransport`; `transport_for(definition) -> Transport`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/providers/cli/test_transport.py`:

```python
"""How the prompt reaches each runtime, and how a run is asked to stop (spec §12, §14)."""

from __future__ import annotations

import json
from pathlib import Path

from research_harness.providers.cli.parsers import CliEvent
from research_harness.providers.cli.transport import (
    DshProfileTransport,
    PiRpcTransport,
    StdinJsonlTransport,
    StdinTextTransport,
    transport_for,
)
from research_harness.providers.cli.types import CliInvocation
from tests.unit.providers.cli.test_registry import definition


class FakeProcess:
    def __init__(self) -> None:
        self.written: list[str] = []
        self.closed = False

    def write(self, text: str) -> None:
        self.written.append(text)

    def close_stdin(self) -> None:
        self.closed = True


def invocation(**overrides: object) -> CliInvocation:
    values: dict[str, object] = {"model": None, "reasoning": None, "cwd": Path("/tmp/rh-cli-x"), "request_id": "req-1"}
    values.update(overrides)
    return CliInvocation(**values)  # type: ignore[arg-type]


def test_plain_stdin_writes_the_prompt_and_closes() -> None:
    process = FakeProcess()
    StdinTextTransport().start(process, "the prompt", invocation())  # type: ignore[arg-type]
    assert process.written == ["the prompt"] and process.closed


def test_jsonl_stdin_writes_one_user_message_and_closes() -> None:
    process = FakeProcess()
    StdinJsonlTransport().start(process, "the prompt", invocation())  # type: ignore[arg-type]
    assert json.loads(process.written[0])["message"]["content"][0]["text"] == "the prompt"
    assert process.closed


def test_pi_sends_a_prompt_command_keeps_stdin_open_and_aborts_on_cancel() -> None:
    process = FakeProcess()
    transport = PiRpcTransport()
    transport.start(process, "the prompt", invocation())  # type: ignore[arg-type]
    assert json.loads(process.written[0]) == {"id": "req-1", "type": "prompt", "message": "the prompt"}
    assert not process.closed
    transport.cancel(process)  # type: ignore[arg-type]
    assert json.loads(process.written[-1]) == {"id": "req-1-abort", "type": "abort"}


def test_pi_answers_an_extension_ui_request_with_cancelled_and_swallows_it() -> None:
    process = FakeProcess()
    transport = PiRpcTransport()
    line = json.dumps({"type": "extension_ui_request", "id": "ui-1", "method": "confirm"})
    assert transport.intercept(process, line)  # type: ignore[arg-type]
    assert json.loads(process.written[-1]) == {"type": "extension_ui_response", "id": "ui-1", "cancelled": True}
    assert not transport.intercept(process, json.dumps({"type": "agent_start"}))  # type: ignore[arg-type]


def test_dsh_waits_for_ready_then_sends_execute_with_no_mcp_servers() -> None:
    process = FakeProcess()
    transport = DshProfileTransport()
    transport.start(process, "the prompt", invocation(model="deepseek/deepseek-v3", reasoning="high"))  # type: ignore[arg-type]
    assert process.written == [], "nothing is sent before the runtime says ready"
    transport.observe(process, CliEvent(kind="status", status="ready"))  # type: ignore[arg-type]
    command = json.loads(process.written[0])
    assert command == {
        "v": 1,
        "type": "execute",
        "request_id": "req-1",
        "cwd": "/tmp/rh-cli-x",
        "prompt": "the prompt",
        "mcp_servers": [],
        "model": {"provider": "deepseek", "id": "deepseek-v3"},
        "reasoning_effort": "high",
    }
    transport.cancel(process)  # type: ignore[arg-type]
    assert json.loads(process.written[-1]) == {"v": 1, "type": "cancel", "request_id": "req-1"}


def test_dsh_omits_model_and_reasoning_when_default() -> None:
    process = FakeProcess()
    transport = DshProfileTransport()
    transport.start(process, "p", invocation())  # type: ignore[arg-type]
    transport.observe(process, CliEvent(kind="status", status="ready"))  # type: ignore[arg-type]
    assert set(json.loads(process.written[0])) == {"v", "type", "request_id", "cwd", "prompt", "mcp_servers"}


def test_transport_for_follows_the_definition() -> None:
    assert isinstance(transport_for(definition(transport="stdin_text")), StdinTextTransport)
    assert isinstance(transport_for(definition(protocol="claude_stream", json_events_variant=None, transport="stdin_jsonl")), StdinJsonlTransport)
    assert isinstance(transport_for(definition(protocol="pi_rpc", json_events_variant=None, transport="pi_rpc")), PiRpcTransport)
    assert isinstance(transport_for(definition(protocol="dsh_profile", json_events_variant=None, transport="dsh_profile")), DshProfileTransport)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/providers/cli/test_transport.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write `transport.py`**

```python
"""How one prompt reaches a runtime and how a run is asked to stop (spec §12, §14).

Research content never touches argv: plain text or one JSONL user message on stdin, or a
command on an RPC channel. Every transport also knows the protocol's own cancel message,
which the engine sends before it terminates the process tree.
"""

from __future__ import annotations

import json
from typing import Protocol

from research_harness.providers.cli.parsers import CliEvent
from research_harness.providers.cli.prompt import stream_json_user_message
from research_harness.providers.cli.types import CliInvocation, CliRuntimeDef

__all__ = ["DshProfileTransport", "PiRpcTransport", "StdinJsonlTransport", "StdinTextTransport", "Transport", "transport_for"]


class _Stdin(Protocol):
    def write(self, text: str) -> None: ...

    def close_stdin(self) -> None: ...


class Transport(Protocol):
    def start(self, process: _Stdin, prompt: str, invocation: CliInvocation) -> None: ...

    def observe(self, process: _Stdin, event: CliEvent) -> None: ...

    def intercept(self, process: _Stdin, line: str) -> bool: ...

    def cancel(self, process: _Stdin) -> None: ...


class StdinTextTransport:
    def start(self, process: _Stdin, prompt: str, invocation: CliInvocation) -> None:
        process.write(prompt)
        process.close_stdin()

    def observe(self, process: _Stdin, event: CliEvent) -> None:
        return None

    def intercept(self, process: _Stdin, line: str) -> bool:
        return False

    def cancel(self, process: _Stdin) -> None:
        process.close_stdin()


class StdinJsonlTransport(StdinTextTransport):
    def start(self, process: _Stdin, prompt: str, invocation: CliInvocation) -> None:
        process.write(stream_json_user_message(prompt))
        process.close_stdin()


class PiRpcTransport:
    def __init__(self) -> None:
        self._request_id = ""

    def start(self, process: _Stdin, prompt: str, invocation: CliInvocation) -> None:
        self._request_id = invocation.request_id
        process.write(json.dumps({"id": invocation.request_id, "type": "prompt", "message": prompt}) + "\n")

    def observe(self, process: _Stdin, event: CliEvent) -> None:
        return None

    def intercept(self, process: _Stdin, line: str) -> bool:
        """Refuse every extension dialog: a bounded worker has nobody to ask."""
        try:
            obj = json.loads(line)
        except ValueError:
            return False
        if not isinstance(obj, dict) or obj.get("type") != "extension_ui_request":
            return False
        if obj.get("id") is not None:
            process.write(json.dumps({"type": "extension_ui_response", "id": obj["id"], "cancelled": True}) + "\n")
        return True

    def cancel(self, process: _Stdin) -> None:
        process.write(json.dumps({"id": f"{self._request_id}-abort", "type": "abort"}) + "\n")
        process.close_stdin()


class DshProfileTransport:
    def __init__(self) -> None:
        self._prompt = ""
        self._invocation: CliInvocation | None = None
        self._sent = False

    def start(self, process: _Stdin, prompt: str, invocation: CliInvocation) -> None:
        self._prompt = prompt
        self._invocation = invocation

    def observe(self, process: _Stdin, event: CliEvent) -> None:
        if self._sent or event.kind != "status" or event.status != "ready" or self._invocation is None:
            return
        self._sent = True
        command: dict[str, object] = {
            "v": 1,
            "type": "execute",
            "request_id": self._invocation.request_id,
            "cwd": str(self._invocation.cwd),
            "prompt": self._prompt,
            "mcp_servers": [],
        }
        model = self._invocation.model
        if model and "/" in model:
            provider, _, model_id = model.partition("/")
            command["model"] = {"provider": provider, "id": model_id}
        if self._invocation.reasoning:
            command["reasoning_effort"] = self._invocation.reasoning
        process.write(json.dumps(command) + "\n")

    def intercept(self, process: _Stdin, line: str) -> bool:
        return False

    def cancel(self, process: _Stdin) -> None:
        if self._invocation is not None:
            process.write(json.dumps({"v": 1, "type": "cancel", "request_id": self._invocation.request_id}) + "\n")
        process.close_stdin()


def transport_for(definition: CliRuntimeDef) -> Transport:
    if definition.transport == "stdin_jsonl":
        return StdinJsonlTransport()
    if definition.transport == "pi_rpc":
        return PiRpcTransport()
    if definition.transport == "dsh_profile":
        return DshProfileTransport()
    return StdinTextTransport()
```

- [ ] **Step 4: Run the tests and gates**

Run: `uv run pytest tests/unit/providers/cli -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research_harness/providers/cli/transport.py tests/unit/providers/cli/test_transport.py
git commit -m "feat(cli-providers): stdin, JSONL, Pi RPC, and DeepSeek Harness prompt transports"
```

---
### Task 6: Detection — executables, probes, fault-isolated scan, short cache

Spec §10, §21.

**Files:**
- Create: `src/research_harness/providers/cli/detection.py`
- Test: `tests/unit/providers/cli/test_detection.py`

**Interfaces:**
- Consumes: `run_probe` (Task 3), `bounded_environment` (Task 2), `redact` (Task 1), the `CliRuntimeDef` fields.
- Produces: `ProbeRunner` (the `run_probe` signature), `resolve_executable(definition, env, *, platform=sys.platform) -> Path | None`, `detect(definition, *, env=None, runner=run_probe, platform=sys.platform, now=None) -> CliRuntimeStatus`, `scan(definitions=None, *, env=None, runner=run_probe, fresh=False, max_workers=4, cache=None) -> tuple[CliRuntimeStatus, ...]`, `ScanCache(ttl_seconds=30.0)`, `DEFAULT_CACHE`, `compatibility_of(definition, version) -> Compatibility`, `DEFAULT_MODEL_OPTION`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/providers/cli/test_detection.py`:

```python
"""A scan is fresh, bounded, fault-isolated, ordered, and secret-free (spec §10, §21)."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from research_harness.providers.cli.detection import (
    DEFAULT_MODEL_OPTION,
    ScanCache,
    compatibility_of,
    detect,
    resolve_executable,
    scan,
)
from research_harness.providers.cli.types import (
    BoundedPosture,
    CliModelOption,
    Probe,
    ProbeOutcome,
)
from tests.fixtures.cli.fakes import FakeCli
from tests.unit.providers.cli.test_registry import definition


def classify_auth(outcome: ProbeOutcome) -> tuple[str, str]:
    if "logged in" in outcome.stdout.lower():
        return "ok", ""
    return "missing", "run `fake login`"


def parse_models(outcome: ProbeOutcome) -> tuple[CliModelOption, ...] | None:
    ids = [line.strip() for line in outcome.stdout.splitlines() if line.strip()]
    return tuple(CliModelOption(id=item, label=item) for item in ids) or None


def full_definition(**overrides: object):  # noqa: ANN201 - a test builder
    values: dict[str, object] = {
        "auth_probe": Probe(args=("login", "status")),
        "classify_auth": classify_auth,
        "model_probe": Probe(args=("models",)),
        "parse_models": parse_models,
        "fallback_models": (CliModelOption(id="fallback-1", label="Fallback"),),
        "posture": BoundedPosture(kind="native_flags", help_probe=Probe(args=("exec", "--help")), required_help_flags=("--sandbox", "--json")),
        "verified_versions": ("1.2.3",),
        "blocked_versions": ("0.9.0",),
        "minimum_version": "1.0.0",
    }
    values.update(overrides)
    return definition(**values)


def installed(tmp_path: Path, **script: object) -> FakeCli:
    probes = [
        {"args": ["login", "status"], "stdout": "Logged in using Fake\n"},
        {"args": ["models"], "stdout": "fake-large\nfake-small\n"},
        {"args": ["exec", "--help"], "stdout": "Usage: fake exec [--sandbox MODE] [--json]\n"},
    ]
    return FakeCli.install(tmp_path, "fake", probes=probes, **script)  # type: ignore[arg-type]


# -- executables -------------------------------------------------------------


def test_the_executable_is_found_on_the_effective_path_and_fallbacks_are_tried(tmp_path: Path) -> None:
    fake = FakeCli.install(tmp_path, "fake-alt")
    assert resolve_executable(definition(), fake.env({"PATH": ""})) is None
    assert resolve_executable(definition(fallback_executables=("fake-alt",)), fake.env({"PATH": ""})) == fake.executable


def test_windows_resolution_uses_pathext(tmp_path: Path) -> None:
    (tmp_path / "fake.CMD").write_text("@echo off", encoding="utf-8")
    env = {"PATH": str(tmp_path), "PATHEXT": ".EXE;.CMD"}
    assert resolve_executable(definition(), env, platform="win32") == tmp_path / "fake.CMD"
    assert resolve_executable(definition(), env, platform="linux") is None


def test_a_non_executable_file_is_not_a_resolution(tmp_path: Path) -> None:
    plain = tmp_path / "fake"
    plain.write_text("x", encoding="utf-8")
    plain.chmod(plain.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    assert resolve_executable(definition(), {"PATH": str(tmp_path)}) is None


# -- one runtime ---------------------------------------------------------------


def test_a_missing_runtime_is_unavailable_and_probes_nothing_else(tmp_path: Path) -> None:
    status = detect(full_definition(), env={"PATH": str(tmp_path), "HOME": str(tmp_path)})
    assert not status.available and status.executable is None and status.version is None
    assert status.auth_status == "unknown" and status.bounded_mode == "unknown"
    assert status.compatibility == "unknown" and status.model_source == "fallback"
    assert status.diagnostics == ("fake is not installed: no 'fake' on PATH",)


def test_an_installed_logged_in_runtime_is_fully_described(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    status = detect(full_definition(), env=fake.env({"PATH": "", "HOME": str(tmp_path)}), now=datetime(2026, 9, 4, tzinfo=UTC))
    assert status.available and status.version == "fake 1.2.3"
    assert status.executable == "~/bin/fake" or status.executable == str(fake.executable), "home is replaced by ~"
    assert status.auth_status == "ok" and status.bounded_mode == "safe"
    assert [item.id for item in status.models] == ["default", "fake-large", "fake-small"]
    assert status.models[0] == DEFAULT_MODEL_OPTION.as_view()
    assert status.model_source == "live" and status.reasoning_choices == ()
    assert status.egress_kind == "external" and status.egress_host == "example.test"
    assert status.scanned_at == datetime(2026, 9, 4, tzinfo=UTC)


def test_a_rejected_version_flag_is_still_installed(tmp_path: Path) -> None:
    fake = installed(tmp_path, version_exit=2, version_stdout="", version_stderr="unknown flag --version")
    status = detect(full_definition(), env=fake.env({"PATH": ""}))
    assert status.available and status.version is None
    assert status.compatibility == "unknown"
    assert any("--version" in line for line in status.diagnostics)


def test_a_logged_out_runtime_is_missing_auth_with_guidance(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    fake.write_script({**fake.script(), "probes": [{"args": ["login", "status"], "stdout": "Not logged in\n", "exit": 1}]})
    status = detect(full_definition(), env=fake.env({"PATH": ""}))
    assert status.auth_status == "missing" and status.auth_guidance == "run `fake login`"


def test_no_auth_probe_means_unknown_not_missing(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    status = detect(full_definition(auth_probe=None, classify_auth=None), env=fake.env({"PATH": ""}))
    assert status.auth_status == "unknown" and "first request" in status.auth_guidance


def test_bounded_mode_needs_every_required_flag_in_the_help_output(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    fake.write_script({**fake.script(), "probes": [{"args": ["exec", "--help"], "stdout": "Usage: fake exec [--json]\n"}]})
    status = detect(full_definition(), env=fake.env({"PATH": ""}))
    assert status.bounded_mode == "unsupported"
    assert any("--sandbox" in line for line in status.diagnostics)


def test_a_failed_help_probe_is_unknown_and_a_none_posture_is_unsupported(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    fake.write_script({**fake.script(), "probes": []})
    assert detect(full_definition(), env=fake.env({"PATH": ""})).bounded_mode == "unknown"
    assert detect(full_definition(posture=BoundedPosture(kind="none")), env=fake.env({"PATH": ""})).bounded_mode == "unsupported"


def test_models_fall_back_and_say_so_when_the_probe_fails(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    fake.write_script({**fake.script(), "probes": [{"args": ["models"], "stdout": "", "exit": 1}]})
    status = detect(full_definition(), env=fake.env({"PATH": ""}))
    assert [item.id for item in status.models] == ["default", "fallback-1"] and status.model_source == "fallback"


def test_compatibility_is_a_table_of_versions() -> None:
    d = full_definition()
    assert compatibility_of(d, "1.2.3") == "verified"
    assert compatibility_of(d, "1.3.0") == "warning"
    assert compatibility_of(d, "0.9.0") == "blocked"
    assert compatibility_of(d, "0.9.9") == "blocked", "below the minimum"
    assert compatibility_of(d, None) == "unknown"


def test_a_diagnostic_never_carries_a_home_path_or_a_token(tmp_path: Path) -> None:
    fake = installed(tmp_path, version_exit=1, version_stdout="", version_stderr=f"token sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 at {tmp_path}/home/.fake\n")
    status = detect(full_definition(), env=fake.env({"PATH": "", "HOME": str(tmp_path / "home")}))
    joined = " ".join(status.diagnostics)
    assert "sk-proj" not in joined and str(tmp_path / "home") not in joined


# -- the scan ------------------------------------------------------------------


def test_scan_keeps_registry_order_and_isolates_a_broken_runtime(tmp_path: Path) -> None:
    good = installed(tmp_path / "good")
    env = good.env({"PATH": "", "HOME": str(tmp_path)})

    def exploding(outcome: ProbeOutcome) -> str | None:
        raise RuntimeError("boom")

    results = scan(
        [full_definition(id="broken", executable="fake", parse_version=exploding), full_definition(id="fake")],
        env=env,
        fresh=True,
        cache=ScanCache(),
    )
    assert [item.runtime for item in results] == ["broken", "fake"]
    assert not results[0].available and results[0].diagnostics == ("detection failed: RuntimeError: boom",)
    assert results[1].available


def test_scan_never_edits_the_workspace_or_makes_a_model_request(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    scan([full_definition()], env=fake.env({"PATH": ""}), fresh=True, cache=ScanCache())
    assert [call["kind"] for call in fake.calls()] == ["version", "probe", "probe", "probe"]
    assert fake.runs() == []


def test_the_cache_answers_repeat_scans_and_rescan_bypasses_it(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    cache = ScanCache(ttl_seconds=60)
    env = fake.env({"PATH": ""})
    first = scan([full_definition()], env=env, cache=cache)
    second = scan([full_definition()], env=env, cache=cache)
    assert first == second and len([c for c in fake.calls() if c["kind"] == "version"]) == 1
    scan([full_definition()], env=env, cache=cache, fresh=True)
    assert len([c for c in fake.calls() if c["kind"] == "version"]) == 2


def test_probes_run_from_a_neutral_cwd_with_a_bounded_environment(tmp_path: Path) -> None:
    fake = installed(tmp_path)
    detect(full_definition(), env=fake.env({"PATH": "", "OPENAI_API_KEY": "sk-x"}))
    for call in fake.calls():
        assert "OPENAI_API_KEY" not in call["env"]
        assert not call["cwd"].startswith(os.getcwd()) or call["cwd"] != os.getcwd()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/unit/providers/cli/test_detection.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write `detection.py`**

```python
"""Detection: is the CLI here, which version, logged in, bounded, which models (spec §10).

A scan is fresh by default, bounded per probe, fault-isolated per runtime, ordered like
the registry, and free of secrets. It edits nothing and never sends a model request. A
short in-memory cache keeps a settings screen responsive; an explicit rescan bypasses it,
and nothing here is canonical state.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from research_harness.providers.cli.environment import bounded_environment
from research_harness.providers.cli.errors import redact
from research_harness.providers.cli.process import run_probe
from research_harness.providers.cli.types import (
    DEFAULT_MODEL,
    AuthStatus,
    BoundedMode,
    CliModelOption,
    CliModelView,
    CliRuntimeDef,
    CliRuntimeStatus,
    Compatibility,
    ModelSource,
    ProbeOutcome,
)

__all__ = [
    "DEFAULT_CACHE",
    "DEFAULT_MODEL_OPTION",
    "ProbeRunner",
    "ScanCache",
    "compatibility_of",
    "detect",
    "resolve_executable",
    "scan",
]

ProbeRunner = Callable[..., ProbeOutcome]
VERSION_PROBE_TIMEOUT = 3.0
UNKNOWN_AUTH_GUIDANCE = "authentication is verified on the first request; {login} if it fails"


class _DefaultModelOption:
    """`default`: no `--model` flag; the CLI's own configured model answers."""

    id = DEFAULT_MODEL
    label = "Default (CLI configuration)"

    def as_option(self) -> CliModelOption:
        return CliModelOption(id=self.id, label=self.label)

    def as_view(self) -> CliModelView:
        return CliModelView(id=self.id, label=self.label)


DEFAULT_MODEL_OPTION = _DefaultModelOption()


# -- executables ---------------------------------------------------------------


def _candidates(name: str, env: Mapping[str, str], platform: str) -> list[str]:
    if platform == "win32":
        exts = [ext for ext in env.get("PATHEXT", ".EXE;.CMD;.BAT").split(";") if ext]
        return [name + ext for ext in exts] + [name]
    return [name]


def resolve_executable(
    definition: CliRuntimeDef, env: Mapping[str, str], *, platform: str = sys.platform
) -> Path | None:
    """The first executable file on the effective PATH, trying fallbacks in order."""
    directories = [part for part in env.get("PATH", "").split(os.pathsep) if part]
    for name in (definition.executable, *definition.fallback_executables):
        for directory in directories:
            for candidate in _candidates(name, env, platform):
                path = Path(directory) / candidate
                if not path.is_file():
                    continue
                if platform == "win32" or os.access(path, os.X_OK):
                    return path
    return None


def _display_path(path: Path, env: Mapping[str, str]) -> str:
    home = env.get("HOME") or env.get("USERPROFILE")
    text = str(path)
    if home and text.startswith(home):
        return "~" + text[len(home) :]
    return redact(text)


# -- versions ------------------------------------------------------------------


def _version_tuple(version: str) -> tuple[int, ...]:
    digits: list[int] = []
    for part in version.split("-")[0].split("+")[0].lstrip("v").split("."):
        if not part.isdigit():
            break
        digits.append(int(part))
    return tuple(digits)


def compatibility_of(definition: CliRuntimeDef, version: str | None) -> Compatibility:
    """`verified` with fixtures, `blocked` when known bad or below the floor, else `warning`."""
    if version is None:
        return "unknown"
    if version in definition.blocked_versions:
        return "blocked"
    if definition.minimum_version and _version_tuple(version) < _version_tuple(definition.minimum_version):
        return "blocked"
    if version in definition.verified_versions:
        return "verified"
    return "warning"


# -- one runtime ---------------------------------------------------------------


def detect(
    definition: CliRuntimeDef,
    *,
    env: Mapping[str, str] | None = None,
    runner: ProbeRunner = run_probe,
    platform: str = sys.platform,
    now: datetime | None = None,
) -> CliRuntimeStatus:
    """Probe one runtime: executable, version, then auth, help, and models (spec §10)."""
    base: Mapping[str, str] = os.environ if env is None else env
    scanned_at = now or datetime.now(UTC)
    diagnostics: list[str] = []
    fallback = (DEFAULT_MODEL_OPTION.as_option(), *definition.fallback_models)

    def status(**fields: object) -> CliRuntimeStatus:
        values: dict[str, object] = {
            "runtime": definition.id,
            "name": definition.name,
            "available": False,
            "executable": None,
            "version": None,
            "auth_status": "unknown",
            "auth_guidance": UNKNOWN_AUTH_GUIDANCE.format(login=definition.login_guidance),
            "bounded_mode": "unknown",
            "compatibility": "unknown",
            "models": tuple(_view(item) for item in fallback),
            "model_source": "fallback",
            "reasoning_choices": definition.reasoning_choices,
            "egress_kind": definition.egress,
            "egress_host": definition.egress_host,
            "diagnostics": tuple(diagnostics),
            "scanned_at": scanned_at,
        }
        values.update(fields)
        return CliRuntimeStatus.model_validate(values)

    executable = resolve_executable(definition, base, platform=platform)
    if executable is None:
        diagnostics.append(f"{definition.id} is not installed: no {definition.executable!r} on PATH")
        return status()

    child_env = bounded_environment(definition, base, executable=executable)
    cwd = Path(tempfile.gettempdir())

    def probe(args: Sequence[str], timeout: float) -> ProbeOutcome:
        return runner((str(executable), *args), env=child_env, timeout=timeout, cwd=cwd)

    outcome = probe(definition.version_probe.args, definition.version_probe.timeout_seconds)
    if not outcome.started:
        diagnostics.append(f"{definition.id} could not be started: {redact(outcome.os_error or '', home=base.get('HOME'))}")
        return status(executable=_display_path(executable, base))
    version: str | None = None
    if outcome.timed_out or outcome.exit_code != 0:
        diagnostics.append(
            f"{definition.id} rejected {' '.join(definition.version_probe.args)} "
            f"(exit {outcome.exit_code}); the version is unknown: {redact(outcome.text.strip()[:200], home=base.get('HOME'))}"
        )
    else:
        version = definition.parse_version(outcome)

    auth, guidance = _auth(definition, probe, base.get("HOME"))
    bounded = _bounded(definition, probe, diagnostics)
    models, source = _models(definition, probe, fallback)
    return status(
        available=True,
        executable=_display_path(executable, base),
        version=version,
        auth_status=auth,
        auth_guidance=guidance,
        bounded_mode=bounded,
        compatibility=compatibility_of(definition, version),
        models=tuple(_view(item) for item in models),
        model_source=source,
    )


def _auth(
    definition: CliRuntimeDef, probe: Callable[[Sequence[str], float], ProbeOutcome], home: str | None
) -> tuple[AuthStatus, str]:
    if definition.auth_probe is None or definition.classify_auth is None:
        return "unknown", UNKNOWN_AUTH_GUIDANCE.format(login=definition.login_guidance)
    outcome = probe(definition.auth_probe.args, definition.auth_probe.timeout_seconds)
    if not outcome.started or outcome.timed_out:
        return "unknown", UNKNOWN_AUTH_GUIDANCE.format(login=definition.login_guidance)
    verdict, guidance = definition.classify_auth(outcome)
    return verdict, redact(guidance, home=home)


def _bounded(
    definition: CliRuntimeDef, probe: Callable[[Sequence[str], float], ProbeOutcome], diagnostics: list[str]
) -> BoundedMode:
    posture = definition.posture
    if posture.kind == "none" or posture.help_probe is None:
        return "unsupported"
    outcome = probe(posture.help_probe.args, posture.help_probe.timeout_seconds)
    if not outcome.started or outcome.timed_out:
        diagnostics.append(f"{definition.id}: the help probe did not answer, so the bounded mode is unproven")
        return "unknown"
    missing = [flag for flag in posture.required_help_flags if flag not in outcome.text]
    if missing:
        diagnostics.append(
            f"{definition.id}: this version does not offer {', '.join(missing)}, which the bounded mode needs"
        )
        return "unsupported"
    return "safe"


def _models(
    definition: CliRuntimeDef,
    probe: Callable[[Sequence[str], float], ProbeOutcome],
    fallback: tuple[CliModelOption, ...],
) -> tuple[tuple[CliModelOption, ...], ModelSource]:
    if definition.model_probe is None or definition.parse_models is None:
        return fallback, "fallback"
    outcome = probe(definition.model_probe.args, definition.model_probe.timeout_seconds)
    live = definition.parse_models(outcome) if outcome.started and not outcome.timed_out and outcome.exit_code == 0 else None
    if not live:
        return fallback, "fallback"
    seen = {DEFAULT_MODEL}
    ordered = [DEFAULT_MODEL_OPTION.as_option()]
    for item in live:
        if item.id not in seen:
            seen.add(item.id)
            ordered.append(item)
    return tuple(ordered), "live"


def _view(option: CliModelOption) -> CliModelView:
    return CliModelView(id=option.id, label=option.label, reasoning=option.reasoning, context_tokens=option.context_tokens)


# -- the scan ------------------------------------------------------------------


class ScanCache:
    """Recent scan results, keyed by runtime id and PATH; never canonical state."""

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[tuple[str, str], tuple[float, CliRuntimeStatus]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> CliRuntimeStatus | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or time.monotonic() - entry[0] > self._ttl:
                return None
            return entry[1]

    def put(self, key: tuple[str, str], value: CliRuntimeStatus) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


DEFAULT_CACHE = ScanCache()


def scan(
    definitions: Sequence[CliRuntimeDef] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    runner: ProbeRunner = run_probe,
    fresh: bool = False,
    max_workers: int = 4,
    cache: ScanCache | None = None,
    now: datetime | None = None,
) -> tuple[CliRuntimeStatus, ...]:
    """Detect every definition with bounded concurrency; results in the order given."""
    from research_harness.providers.cli.registry import RUNTIME_DEFS

    targets = tuple(RUNTIME_DEFS if definitions is None else definitions)
    base: Mapping[str, str] = os.environ if env is None else env
    store = DEFAULT_CACHE if cache is None else cache
    path_key = base.get("PATH", "")

    def one(definition: CliRuntimeDef) -> CliRuntimeStatus:
        key = (definition.id, path_key)
        if not fresh:
            cached = store.get(key)
            if cached is not None:
                return cached
        try:
            result = detect(definition, env=base, runner=runner, now=now)
        except Exception as exc:  # fault isolation: one broken CLI cannot empty the catalog
            result = CliRuntimeStatus(
                runtime=definition.id,
                name=definition.name,
                available=False,
                executable=None,
                version=None,
                auth_status="unknown",
                auth_guidance=UNKNOWN_AUTH_GUIDANCE.format(login=definition.login_guidance),
                bounded_mode="unknown",
                compatibility="unknown",
                models=(DEFAULT_MODEL_OPTION.as_view(),),
                model_source="fallback",
                reasoning_choices=definition.reasoning_choices,
                egress_kind=definition.egress,
                egress_host=definition.egress_host,
                diagnostics=(f"detection failed: {type(exc).__name__}: {redact(str(exc), home=base.get('HOME'))}",),
                scanned_at=now or datetime.now(UTC),
            )
        store.put(key, result)
        return result

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(targets) or 1))) as pool:
        return tuple(pool.map(one, targets))
```

- [ ] **Step 4: Run the tests and gates**

Run: `uv run pytest tests/unit/providers/cli -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research_harness/providers/cli/detection.py tests/unit/providers/cli/test_detection.py
git commit -m "feat(cli-providers): executable resolution, bounded probes, and the fault-isolated scan"
```

---

### Task 7: Codex CLI and Claude Code definitions (the first vertical slice)

Spec §9, §21. Flags below were compared against the installed `codex` 0.150.1 (`codex exec --help`, `codex login status`, `codex debug models`) and `claude` 2.1.259 (`claude --help`, `claude auth status`) and against the pinned Open Design defs; the bypass flags Open Design passes (`--permission-mode bypassPermissions`, `--sandbox danger-full-access`/`workspace-write`) are replaced by the bounded ones.

**Files:**
- Create: `src/research_harness/providers/cli/defs/codex.py`, `src/research_harness/providers/cli/defs/claude.py`
- Modify: `src/research_harness/providers/cli/defs/__init__.py` (`SHIPPED_DEFS = (CODEX, CLAUDE)`)
- Create: `tests/fixtures/cli/probes/codex-login-status-ok.txt`, `codex-login-status-missing.txt`, `codex-debug-models.json`, `codex-exec-help.txt`, `claude-auth-status-ok.json`, `claude-auth-status-missing.json`, `claude-help.txt`
- Test: `tests/unit/providers/cli/test_defs_codex_claude.py`

**Interfaces:**
- Produces: `CODEX: CliRuntimeDef` (id `codex`), `CLAUDE: CliRuntimeDef` (id `claude`); helpers `parse_semver(outcome)`, `codex_auth(outcome)`, `parse_codex_models(outcome)`, `claude_auth(outcome)`, `codex_args(invocation)`, `claude_args(invocation)`.

- [ ] **Step 1: Write the probe fixtures**

`codex-login-status-ok.txt`: `Logged in using ChatGPT` + newline. `codex-login-status-missing.txt`: `Not logged in` + newline. `codex-exec-help.txt`: the `codex exec --help` text as printed by 0.150.1 (the implementer runs `codex exec --help > tests/fixtures/cli/probes/codex-exec-help.txt` when `codex` is on PATH, else pastes the copy in this plan's Global Constraints source, `docs/superpowers/plans/…`; it must contain the lines for `--sandbox`, `--output-schema`, `--json`, `--ephemeral`, `--skip-git-repo-check`, `--ignore-user-config`, `--ignore-rules`, `-C, --cd`). `codex-debug-models.json` (two visible models, one hidden, sanitized from the real output):

```json
{"models":[
 {"slug":"gpt-5.5","display_name":"GPT-5.5","default_reasoning_level":"xhigh","supported_reasoning_levels":[{"effort":"low"},{"effort":"medium"},{"effort":"high"},{"effort":"xhigh"}],"visibility":"list","context_window":272000,"input_modalities":["text","image"]},
 {"slug":"gpt-5.4-mini","display_name":"GPT-5.4-Mini","default_reasoning_level":"medium","supported_reasoning_levels":[{"effort":"low"},{"effort":"medium"},{"effort":"high"}],"visibility":"list","context_window":272000,"input_modalities":["text"]},
 {"slug":"codex-auto-review","display_name":"Codex Auto Review","default_reasoning_level":"medium","supported_reasoning_levels":[{"effort":"low"}],"visibility":"hide","context_window":272000,"input_modalities":["text"]}
]}
```

`claude-auth-status-ok.json`: `{"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max"}`. `claude-auth-status-missing.json`: `{"loggedIn": false, "authMethod": null}`. `claude-help.txt`: the `claude --help` text from 2.1.259 (implementer captures it the same way); it must contain `--tools`, `--permission-mode`, `--permission-prompts`, `--output-format`, `--input-format`, `--include-partial-messages`, `--strict-mcp-config`, `--no-session-persistence`, `--disable-slash-commands`.

- [ ] **Step 2: Write the failing tests**

`tests/unit/providers/cli/test_defs_codex_claude.py`:

```python
"""The Codex CLI and Claude Code definitions are bounded, complete, and honest (spec §9)."""

from __future__ import annotations

import json
from pathlib import Path

from research_harness.providers.cli.defs.claude import CLAUDE, claude_args, claude_auth
from research_harness.providers.cli.defs.codex import CODEX, codex_args, codex_auth, parse_codex_models
from research_harness.providers.cli.registry import FORBIDDEN_ARGS, RUNTIMES, validate_definition
from research_harness.providers.cli.types import CliInvocation, ProbeOutcome

PROBES = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "cli" / "probes"


def outcome(name: str, exit_code: int = 0) -> ProbeOutcome:
    return ProbeOutcome(argv=("x",), exit_code=exit_code, stdout=(PROBES / name).read_text(encoding="utf-8"), stderr="")


def invocation(model: str | None = None, reasoning: str | None = None) -> CliInvocation:
    cwd = Path("/tmp/rh-cli-x")
    return CliInvocation(model=model, reasoning=reasoning, cwd=cwd, request_id="req-1", schema_path=cwd / "response.schema.json")


def test_both_definitions_are_registered_and_valid() -> None:
    assert RUNTIMES["codex"] is CODEX and RUNTIMES["claude"] is CLAUDE
    validate_definition(CODEX)
    validate_definition(CLAUDE)


# -- codex ---------------------------------------------------------------------


def test_codex_argv_is_read_only_never_approves_and_delivers_the_schema_by_file() -> None:
    args = codex_args(invocation(model="gpt-5.5", reasoning="high"))
    assert args[:2] == ("exec", "--json")
    assert ("--sandbox", "read-only") == args[args.index("--sandbox") : args.index("--sandbox") + 2]
    assert 'approval_policy="never"' in args
    assert "--ephemeral" in args and "--skip-git-repo-check" in args and "--ignore-user-config" in args
    assert ("-C", "/tmp/rh-cli-x") == args[args.index("-C") : args.index("-C") + 2]
    assert ("--output-schema", "/tmp/rh-cli-x/response.schema.json") == args[args.index("--output-schema") : args.index("--output-schema") + 2]
    assert ("--model", "gpt-5.5") == args[args.index("--model") : args.index("--model") + 2]
    assert 'model_reasoning_effort="high"' in args
    assert not FORBIDDEN_ARGS & set(args)


def test_codex_default_model_sends_no_model_flag_and_no_schema_without_a_path() -> None:
    args = codex_args(CliInvocation(model=None, reasoning=None, cwd=Path("/tmp/x"), request_id="r"))
    assert "--model" not in args and "--output-schema" not in args and "model_reasoning_effort" not in " ".join(args)


def test_codex_login_status_classifies_both_ways() -> None:
    assert codex_auth(outcome("codex-login-status-ok.txt")) == ("ok", "")
    assert codex_auth(outcome("codex-login-status-missing.txt", exit_code=1)) == ("missing", "run `codex login`")
    assert codex_auth(ProbeOutcome(argv=("x",), exit_code=3, stdout="", stderr="unexpected"))[0] == "unknown"


def test_codex_debug_models_lists_only_visible_models_with_their_efforts() -> None:
    models = parse_codex_models(outcome("codex-debug-models.json"))
    assert models is not None
    assert [item.id for item in models] == ["gpt-5.5", "gpt-5.4-mini"]
    assert models[0].reasoning == ("low", "medium", "high", "xhigh") and models[0].context_tokens == 272000
    assert parse_codex_models(ProbeOutcome(argv=("x",), exit_code=0, stdout="not json", stderr="")) is None


def test_codex_posture_is_proven_by_the_real_help_text() -> None:
    text = (PROBES / "codex-exec-help.txt").read_text(encoding="utf-8")
    assert all(flag in text for flag in CODEX.posture.required_help_flags)
    assert CODEX.posture.help_probe is not None and CODEX.posture.help_probe.args == ("exec", "--help")
    assert CODEX.parse_version(ProbeOutcome(argv=("x",), exit_code=0, stdout="codex-cli 0.150.1\n", stderr="")) == "0.150.1"
    assert CODEX.egress == "external" and CODEX.egress_host == "chatgpt.com"
    assert "OPENAI_API_KEY" not in CODEX.env_keep and "CODEX_HOME" in CODEX.env_keep
    assert "0.150.1" in CODEX.verified_versions


# -- claude --------------------------------------------------------------------


def test_claude_argv_disables_every_tool_and_denies_every_prompt() -> None:
    args = claude_args(invocation(model="opus"))
    assert args[0] == "-p"
    assert ("--tools", "") == args[args.index("--tools") : args.index("--tools") + 2]
    assert ("--permission-mode", "dontAsk") == args[args.index("--permission-mode") : args.index("--permission-mode") + 2]
    assert ("--permission-prompts", "none") == args[args.index("--permission-prompts") : args.index("--permission-prompts") + 2]
    for flag in ("--input-format", "--output-format"):
        assert "stream-json" == args[args.index(flag) + 1]
    assert "--include-partial-messages" in args and "--strict-mcp-config" in args
    assert "--no-session-persistence" in args and "--disable-slash-commands" in args
    assert ("--model", "opus") == args[args.index("--model") : args.index("--model") + 2]
    assert "--bare" not in args, "--bare never reads OAuth and would break the subscription login"
    assert "--output-schema" not in " ".join(args)
    assert not FORBIDDEN_ARGS & set(args)


def test_claude_auth_status_reads_the_json_and_falls_back_to_text() -> None:
    assert claude_auth(outcome("claude-auth-status-ok.json")) == ("ok", "")
    assert claude_auth(outcome("claude-auth-status-missing.json")) == ("missing", "run `claude auth login`")
    assert claude_auth(ProbeOutcome(argv=("x",), exit_code=1, stdout="", stderr="Not logged in · Please run /login"))[0] == "missing"
    assert claude_auth(ProbeOutcome(argv=("x",), exit_code=1, stdout="", stderr="garbage"))[0] == "unknown"


def test_claude_posture_is_proven_by_the_real_help_text() -> None:
    text = (PROBES / "claude-help.txt").read_text(encoding="utf-8")
    assert all(flag in text for flag in CLAUDE.posture.required_help_flags)
    assert CLAUDE.parse_version(ProbeOutcome(argv=("x",), exit_code=0, stdout="2.1.259 (Claude Code)\n", stderr="")) == "2.1.259"
    assert CLAUDE.transport == "stdin_jsonl" and CLAUDE.protocol == "claude_stream"
    assert CLAUDE.egress_host == "api.anthropic.com" and CLAUDE.fallback_executables == ("openclaude",)
    assert CLAUDE.model_probe is None and [m.id for m in CLAUDE.fallback_models][:3] == ["sonnet", "opus", "haiku"]
    assert "ANTHROPIC_API_KEY" not in CLAUDE.env_keep and "CLAUDE_CONFIG_DIR" in CLAUDE.env_keep


def test_upstream_provenance_is_recorded_on_both() -> None:
    for item in (CODEX, CLAUDE):
        assert item.upstream_source.startswith("open-design@9bb4a7d")
        assert json.dumps(item.upstream_source)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/unit/providers/cli/test_defs_codex_claude.py -q`
Expected: FAIL — the def modules do not exist.

- [ ] **Step 4: Write `defs/codex.py`**

```python
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
_NOT_LOGGED_IN = re.compile(r"\bnot logged in\b|login required|please run .*login", re.IGNORECASE)


def parse_semver(outcome: ProbeOutcome) -> str | None:
    match = _SEMVER.search(outcome.text)
    return match.group(1) if match else None


def codex_auth(outcome: ProbeOutcome) -> tuple[AuthStatus, str]:
    if _NOT_LOGGED_IN.search(outcome.text):
        return "missing", "run `codex login`"
    if outcome.exit_code == 0 and _LOGGED_IN.search(outcome.text):
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
        CliModelOption(id="gpt-5.4-mini", label="gpt-5.4-mini", reasoning=("low", "medium", "high")),
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
    notes="A ChatGPT login talks to chatgpt.com; an API-key login would use api.openai.com, which the bounded environment prevents by dropping OPENAI_API_KEY.",
)
```

- [ ] **Step 5: Write `defs/claude.py`**

```python
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

_NOT_LOGGED_IN = re.compile(r"not logged[ _-]?in|please run /login|\"loggedIn\"\s*:\s*false", re.IGNORECASE)
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
    notes="Claude Code has no reasoning-effort flag in 2.1.259; the requested level routes only.",
)
```

`defs/__init__.py` becomes:

```python
"""The shipped runtime definitions, in display order (CLI providers spec §9)."""

from __future__ import annotations

from research_harness.providers.cli.defs.claude import CLAUDE
from research_harness.providers.cli.defs.codex import CODEX
from research_harness.providers.cli.types import CliRuntimeDef

__all__ = ["SHIPPED_DEFS"]

SHIPPED_DEFS: tuple[CliRuntimeDef, ...] = (CODEX, CLAUDE)
```

- [ ] **Step 6: Run the tests and gates**

Run: `uv run pytest tests/unit/providers/cli -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`
Expected: PASS, including `test_the_shipped_registry_is_importable_and_ordered` from Task 1.

- [ ] **Step 7: Commit**

```bash
git add src/research_harness/providers/cli/defs tests/fixtures/cli/probes tests/unit/providers/cli/test_defs_codex_claude.py
git commit -m "feat(cli-providers): bounded Codex CLI and Claude Code definitions with probe fixtures"
```

---

### Task 8: `CliModelProvider`, router integration, and the provider contract tests

Spec §11, §12, §13, §14, §15, §19 (traces). The end-to-end seam: a configured `local_cli` entry answers the same `ModelRequest` as every HTTP adapter.

**Files:**
- Create: `src/research_harness/providers/cli/provider.py`
- Modify: `src/research_harness/providers/models/router.py`, `src/research_harness/providers/models/streaming.py`, `src/research_harness/privacy/egress.py`, `src/research_harness/providers/cli/__init__.py`
- Test: `tests/contract/providers/test_cli_provider.py`, `tests/unit/providers/cli/test_router_config.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7; `ModelProvider`, `RawCompletion`, `Usage`, `trace_payload`, `StreamDelta`, `ChatReply`.
- Produces: `CliModelProvider(runtime, model=DEFAULT_MODEL, *, reasoning=None, timeout=300.0, capabilities=None, env=None, executable=None, spawn=BoundedProcess.spawn)` with `.name`, `.model`, `.runtime`, `.capabilities()`, `.trace_metadata()`, `.stream(request)`, `._execute(request, schema_json)`; `default_cli_capabilities(definition, model=None)`; `SpawnFactory`.
- Router: `ProviderKind` gains `"local_cli"`; `RouterProviderConfig` gains `runtime: str | None` and `reasoning: str | None`; `entry_capabilities()` answers for `local_cli` without spawning; `entry_base_url()` returns `""` for `local_cli`; `_build_entry` constructs `CliModelProvider`.
- `egress.MODEL_KEY_ENV_VARS` is looked up with `.get`, so a `local_cli` row has `key_env=None`.
- `streaming.NativeStream._record` merges `provider.trace_metadata()` under the `"cli"` key when the provider has it.

- [ ] **Step 1: Write the failing contract tests**

`tests/contract/providers/test_cli_provider.py`:

```python
"""A CLI-backed provider honours the same contract as every HTTP adapter (spec §20).

Driven entirely through fake executables: the real `codex` definition is used, but the
`codex` on PATH is `tests/fixtures/cli/fakes.py` replaying the sanitized event fixtures.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from research_harness.privacy.policy import EgressPolicy
from research_harness.providers.cli.errors import CliResponseError, CliTransportError
from research_harness.providers.cli.provider import CliModelProvider, default_cli_capabilities
from research_harness.providers.cli.registry import RUNTIMES
from research_harness.providers.models.base import ModelRequest, StructuredOutputError
from research_harness.providers.models.router import RouterConfig, build_router
from research_harness.providers.models.streaming import ChatReply, chat_request, streaming_provider
from tests.contract.providers.conftest import CANONICAL_JSON, EXPECTED_VERDICT, Verdict
from tests.fixtures.cli.fakes import FakeCli

STREAMS = Path(__file__).resolve().parents[2] / "fixtures" / "cli" / "streams"


def lines(name: str) -> list[str]:
    return [line for line in (STREAMS / name).read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]


@pytest.fixture
def codex(tmp_path: Path) -> FakeCli:
    return FakeCli.install(
        tmp_path,
        "codex",
        version_stdout="codex-cli 0.150.1",
        probes=[{"args": ["login", "status"], "stdout": "Logged in using ChatGPT\n"}, {"args": ["exec", "--help"], "stdout": "--sandbox --output-schema --json --ephemeral --skip-git-repo-check --ignore-user-config --ignore-rules"}],
        run={"lines": lines("codex-success.jsonl")},
    )


def provider(codex: FakeCli, **kwargs: object) -> CliModelProvider:
    env = codex.env({"PATH": "", "HOME": str(codex.root / "home"), "OPENAI_API_KEY": "sk-metered", "CODEX_HOME": str(codex.root / "home" / ".codex")})
    return CliModelProvider("codex", "gpt-5.5", env=env, timeout=10, **kwargs)  # type: ignore[arg-type]


# -- the contract --------------------------------------------------------------


def test_the_same_request_yields_the_same_validated_object(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    response = provider(codex).complete(model_request)

    assert response.parsed == EXPECTED_VERDICT
    assert response.provider == "local_cli:codex" and response.model == "gpt-5.5"
    assert response.request_fingerprint == model_request.fingerprint()
    assert response.usage.input_tokens == 1200 and response.usage.output_tokens == 95
    assert response.usage.cached_input_tokens == 400 and response.usage.reasoning_tokens == 64
    assert response.raw_text == CANONICAL_JSON


def test_research_content_travels_on_stdin_never_argv(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    provider(codex).complete(model_request)
    run = codex.runs()[0]

    assert "work:0a1b2c" in run["stdin"] and "Table 3 reports" in run["stdin"]
    assert not any("Table 3" in arg or "work:0a1b2c" in arg for arg in run["argv"])
    assert "--sandbox" in run["argv"] and "read-only" in run["argv"]
    schema = run["argv"][run["argv"].index("--output-schema") + 1]
    assert schema.startswith(run["cwd"]) and os.path.basename(schema) == "response.schema.json"


def test_the_process_runs_in_an_empty_temp_cwd_that_is_removed_afterwards(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    provider(codex).complete(model_request)
    run = codex.runs()[0]

    assert os.path.basename(run["cwd"]).startswith("rh-cli-")
    assert not os.path.exists(run["cwd"]), "the temp cwd is deleted in finally"
    assert run["cwd"] != os.getcwd()


def test_the_child_environment_keeps_the_login_and_drops_the_api_key(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    provider(codex).complete(model_request)
    env = codex.runs()[0]["env"]

    assert "OPENAI_API_KEY" not in env and env["CODEX_HOME"].endswith(".codex")
    assert env["NO_COLOR"] == "1" and env["RESEARCH_HARNESS_BOUNDED"] == "1"


def test_invalid_json_fails_through_the_shared_structured_output_path(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    codex.set_run(lines=[json.dumps({"type": "item.completed", "item": {"id": "i", "type": "agent_message", "text": "not json"}}), json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}})])
    with pytest.raises(StructuredOutputError) as caught:
        provider(codex).complete(model_request)
    assert caught.value.raw_text == "not json"


def test_a_schema_violation_never_returns_a_partial_object(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    codex.set_run(lines=[json.dumps({"type": "item.completed", "item": {"id": "i", "type": "agent_message", "text": '{"supported": true}'}}), json.dumps({"type": "turn.completed", "usage": {}})])
    with pytest.raises(StructuredOutputError):
        provider(codex).complete(model_request)


def test_a_tool_event_cancels_the_process_and_is_a_bounded_authority_violation(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    codex.set_run(lines=[*lines("codex-tool.jsonl"), {"sleep": 30}], hang=True)
    with pytest.raises(CliResponseError) as caught:
        provider(codex).complete(model_request)
    assert caught.value.diagnostic == "bounded_authority_violation"
    assert "command_execution" in caught.value.message


def test_a_missing_terminal_event_is_a_transport_failure_even_with_text(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    codex.set_run(lines=lines("codex-success.jsonl")[:-1])
    with pytest.raises(CliTransportError) as caught:
        provider(codex).complete(model_request)
    assert caught.value.diagnostic == "missing_terminal_event"


def test_a_timeout_terminates_the_tree(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    codex.set_run(lines=["{\"type\":\"thread.started\",\"thread_id\":\"t\"}"], hang=True)
    with pytest.raises(CliTransportError) as caught:
        CliModelProvider("codex", "gpt-5.5", env=codex.env({"PATH": ""}), timeout=1).complete(model_request)
    assert caught.value.diagnostic == "timeout"


def test_an_empty_answer_is_a_response_error(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    codex.set_run(lines=[json.dumps({"type": "turn.completed", "usage": {}})])
    with pytest.raises(CliResponseError) as caught:
        provider(codex).complete(model_request)
    assert caught.value.diagnostic == "empty_response"


def test_a_failed_turn_is_classified_from_the_stream(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    codex.set_run(lines=lines("codex-failed.jsonl"))
    with pytest.raises(CliResponseError) as caught:
        provider(codex).complete(model_request)
    assert caught.value.diagnostic == "unsupported_model"


def test_a_missing_executable_is_a_transport_error(tmp_path: Path, model_request: ModelRequest[Verdict]) -> None:
    with pytest.raises(CliTransportError) as caught:
        CliModelProvider("codex", "gpt-5.5", env={"PATH": str(tmp_path)}).complete(model_request)
    assert caught.value.diagnostic == "executable_missing"


def test_media_inputs_are_refused_before_anything_is_spawned(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    from research_harness.providers.models.media import MediaPart

    request = model_request.model_copy(update={"inputs": [*model_request.inputs, model_request.inputs[0].model_copy(update={"media": MediaPart(media_type="image/png", data=b"x", filename="x.png")})]})
    with pytest.raises(CliResponseError) as caught:
        provider(codex).complete(request)
    assert caught.value.diagnostic == "invalid_invocation" and codex.runs() == []


# -- capabilities and egress ---------------------------------------------------


def test_capabilities_are_external_text_only_and_structured() -> None:
    caps = default_cli_capabilities(RUNTIMES["codex"], "gpt-5.5")
    assert caps.structured_output and caps.max_context_tokens == 272_000
    assert caps.reasoning_levels == {"low", "medium", "high"} and not caps.vision and caps.input_media == frozenset()
    assert caps.egress.endpoint_host == "chatgpt.com" and caps.egress.sends_source_text and caps.egress.sends_identifiers
    assert "leaves this workstation" in caps.egress.description


def test_the_privacy_policy_refuses_before_any_process_is_spawned(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    from research_harness.privacy.policy import EgressDeniedError

    config = RouterConfig.model_validate({"providers": [{"name": "codex-sub", "kind": "local_cli", "runtime": "codex", "model": "gpt-5.5"}]})
    router = build_router(config, codex.env({"PATH": ""}), policy=EgressPolicy(external_models="disabled"))
    with pytest.raises(EgressDeniedError):
        router.complete(model_request)
    assert codex.calls() == []


def test_the_router_builds_a_cli_provider_from_configuration(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    config = RouterConfig.model_validate({"providers": [{"name": "codex-sub", "kind": "local_cli", "runtime": "codex", "model": "gpt-5.5", "reasoning": "high", "timeout_seconds": 20}]})
    router = build_router(config, codex.env({"PATH": ""}))
    response = router.complete(model_request)
    assert response.parsed == EXPECTED_VERDICT and response.provider == "local_cli:codex"
    assert 'model_reasoning_effort="high"' in codex.runs()[0]["argv"]
    assert "codex-sub" in router.entries[0].tags


# -- streaming -----------------------------------------------------------------


def test_a_chat_turn_streams_prose_deltas_that_concatenate_to_the_answer(tmp_path: Path) -> None:
    claude = FakeCli.install(tmp_path, "claude", version_stdout="2.1.259 (Claude Code)", run={"lines": lines("claude-partial.jsonl")})
    adapter = CliModelProvider("claude", "opus", env=claude.env({"PATH": ""}), timeout=10)
    request = chat_request(instructions="Summarise.", context_tokens=1000)

    deltas = list(streaming_provider(adapter, model="opus").stream(request))

    assert [d.text for d in deltas if not d.final] == ["Batching ", "reduces tail latency ", "across the pilot corpus."]
    assert deltas[-1].final and deltas[-1].usage is not None and deltas[-1].usage.output_tokens == 41
    assert deltas[-1].stop_reason == "end_turn" and deltas[-1].model == "opus"
    prompt = json.loads(claude.runs()[0]["stdin"])["message"]["content"][0]["text"]
    assert "Answer in plain prose" in prompt and "Response schema" not in prompt


def test_a_non_chat_schema_is_routed_back_through_the_validated_call(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    deltas = list(streaming_provider(provider(codex)).stream(model_request))
    assert len(deltas) == 1 and deltas[0].final and json.loads(deltas[0].text)["supported"] is True


def test_abandoning_the_stream_cancels_the_process(tmp_path: Path) -> None:
    claude = FakeCli.install(tmp_path, "claude", run={"lines": [*lines("claude-partial.jsonl")[:4], {"sleep": 30}], "hang": True})
    adapter = CliModelProvider("claude", "opus", env=claude.env({"PATH": ""}), timeout=30)
    stream = adapter.stream(chat_request(instructions="x", context_tokens=100))
    first = next(stream)
    stream.close()
    assert first.text == "Batching "
    assert adapter.last_process is not None and not adapter.last_process.running


def test_the_trace_records_runtime_version_protocol_and_model(codex: FakeCli, model_request: ModelRequest[Verdict]) -> None:
    class Sink:
        def __init__(self) -> None:
            self.payloads: list[dict[str, object]] = []

        def record(self, kind: str, *, provider: str, model: str, request_fingerprint: str, payload: object) -> None:
            self.payloads.append(dict(payload))  # type: ignore[call-overload]

    sink = Sink()
    provider(codex).complete(model_request, trace=sink)
    cli = sink.payloads[0]["cli"]
    assert isinstance(cli, dict)
    assert cli["runtime"] == "codex" and cli["protocol"] == "json_events"
    assert cli["transport"] == "stdin_text" and cli["model"] == "gpt-5.5"
    assert cli["version"] is None, "the provider never probes a version itself"
    assert isinstance(cli["executable"], str) and cli["executable"].endswith("bin/codex")
    assert "sk-metered" not in json.dumps(sink.payloads)
```

`tests/unit/providers/cli/test_router_config.py`:

```python
"""`kind: local_cli` in research.yaml (spec §11)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from research_harness.providers.models.router import RouterProviderConfig, entry_base_url, entry_capabilities


def test_runtime_is_required_and_must_be_known() -> None:
    with pytest.raises(ValidationError, match="runtime is required"):
        RouterProviderConfig.model_validate({"name": "x", "kind": "local_cli", "model": "default"})
    with pytest.raises(ValidationError, match="unknown runtime 'nope'"):
        RouterProviderConfig.model_validate({"name": "x", "kind": "local_cli", "runtime": "nope", "model": "default"})


def test_base_url_and_api_key_env_are_forbidden_for_a_cli_entry() -> None:
    for field in ("base_url", "api_key_env"):
        with pytest.raises(ValidationError, match=f"{field} is not allowed"):
            RouterProviderConfig.model_validate({"name": "x", "kind": "local_cli", "runtime": "codex", "model": "default", field: "y"})


def test_runtime_and_reasoning_are_forbidden_for_other_kinds() -> None:
    with pytest.raises(ValidationError, match="runtime is only for"):
        RouterProviderConfig.model_validate({"name": "x", "kind": "openai", "model": "m", "runtime": "codex"})


def test_a_cli_entry_needs_no_credential_and_declares_external_egress_without_spawning() -> None:
    entry = RouterProviderConfig.model_validate({"name": "x", "kind": "local_cli", "runtime": "claude", "model": "opus", "capabilities": {"max_context_tokens": 100_000}})
    caps = entry_capabilities(entry)
    assert caps.max_context_tokens == 100_000 and caps.egress.endpoint_host == "api.anthropic.com"
    assert entry_base_url(entry) == ""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/contract/providers/test_cli_provider.py tests/unit/providers/cli/test_router_config.py -q`
Expected: FAIL — `provider.py` missing; `local_cli` is not a `ProviderKind`.

- [ ] **Step 3: Write `provider.py`**

```python
"""`CliModelProvider`: one `ModelRequest`, one bounded subprocess, one `RawCompletion`.

CLI providers spec §12–§15. The prompt is rendered deterministically and delivered over
stdin or RPC; the process runs in an empty temp cwd with a filtered environment; the
stream parser feeds the engine's small vocabulary; a tool event is a bounded-authority
violation; and the final text goes back through `ModelProvider.complete()` so validation
stays the shared path. `stream()` answers a `ChatReply` turn in prose, delta by delta.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from research_harness.providers.cli.detection import resolve_executable
from research_harness.providers.cli.environment import bounded_environment
from research_harness.providers.cli.errors import (
    CliResponseError,
    CliTransportError,
    classify_failure,
    describe_runtime,
    provider_name,
    redact,
)
from research_harness.providers.cli.parsers import CliEvent, parser_for
from research_harness.providers.cli.process import (
    BoundedProcess,
    OutputLimitExceeded,
    ProcessTimeout,
)
from research_harness.providers.cli.prompt import render_chat_prompt, render_prompt
from research_harness.providers.cli.registry import get_runtime
from research_harness.providers.cli.transport import transport_for
from research_harness.providers.cli.types import DEFAULT_MODEL, CliInvocation, CliRuntimeDef
from research_harness.providers.models.base import (
    EgressDeclaration,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderCapabilities,
    RawCompletion,
    TraceSink,
    Usage,
    canonical_json,
    trace_payload,
)
from research_harness.providers.models.media import media_parts
from research_harness.providers.models.streaming import ChatReply, StreamDelta

__all__ = ["CliModelProvider", "SpawnFactory", "default_cli_capabilities"]

logger = logging.getLogger(__name__)

SpawnFactory = Callable[..., BoundedProcess]
HARNESS_LEVELS = frozenset({"low", "medium", "high"})


def default_cli_capabilities(definition: CliRuntimeDef, model: str | None = None) -> ProviderCapabilities:
    """Declared without spawning anything: text-only, structured, always external egress."""
    window = definition.default_context_tokens
    for option in definition.fallback_models:
        if model and option.id == model and option.context_tokens:
            window = option.context_tokens
    where = definition.egress_host if definition.egress == "external" else "a destination the CLI does not disclose"
    return ProviderCapabilities(
        structured_output=definition.structured_output,
        max_context_tokens=window,
        reasoning_levels=set(HARNESS_LEVELS),
        vision=False,
        input_media=frozenset(),
        egress=EgressDeclaration(
            endpoint_host=definition.egress_host,
            sends_source_text=True,
            sends_identifiers=True,
            description=(
                f"The {definition.name} process starts locally, but research content and object IDs "
                f"go to {where}: the request leaves this workstation."
            ),
        ),
    )


class _Collector:
    """What the stream said so far, and whether it is finished."""

    def __init__(self) -> None:
        self.deltas: list[str] = []
        self.final: str | None = None
        self.usage = Usage()
        self.model: str | None = None
        self.stop_reason: str | None = None
        self.error: CliEvent | None = None
        self.tool: str | None = None
        self.done = False

    def take(self, event: CliEvent) -> str | None:
        """Absorb one event; return the new text a streaming consumer should see."""
        if event.kind == "text_delta":
            self.deltas.append(event.text)
            return event.text
        if event.kind == "final_text":
            self.final = event.text
            streamed = "".join(self.deltas)
            if event.text.startswith(streamed) and len(event.text) > len(streamed):
                rest = event.text[len(streamed) :]
                self.deltas.append(rest)
                return rest
            return None
        if event.kind == "usage" and event.usage is not None:
            self.usage = event.usage
        elif event.kind == "model" and event.model:
            self.model = event.model
        elif event.kind == "stop":
            self.stop_reason = event.stop_reason
        elif event.kind == "error":
            self.error = event
        elif event.kind == "tool":
            self.tool = event.tool or "tool"
        elif event.kind == "done":
            self.done = True
        return None

    @property
    def finished(self) -> bool:
        return self.done or self.error is not None or self.tool is not None

    def text(self) -> str:
        return self.final if self.final is not None else "".join(self.deltas)


class CliModelProvider(ModelProvider):
    """A subscription-backed CLI behind the neutral provider contract (spec §12)."""

    def __init__(
        self,
        runtime: CliRuntimeDef | str,
        model: str = DEFAULT_MODEL,
        *,
        reasoning: str | None = None,
        timeout: float = 300.0,
        capabilities: ProviderCapabilities | None = None,
        env: Mapping[str, str] | None = None,
        executable: Path | None = None,
        version: str | None = None,
        spawn: SpawnFactory = BoundedProcess.spawn,
    ) -> None:
        self.runtime = get_runtime(runtime) if isinstance(runtime, str) else runtime
        self.name = provider_name(self.runtime.id)
        self.model = model
        self.reasoning = reasoning
        self._timeout = timeout
        self._capabilities = capabilities or default_cli_capabilities(self.runtime, model)
        self._env: Mapping[str, str] | None = env
        self._executable = executable
        self._spawn = spawn
        self.version = version
        """The installed version when the caller learned it from a scan; never probed here."""
        self._resolved: Path | None = None
        self.last_process: BoundedProcess | None = None

    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def trace_metadata(self) -> dict[str, Any]:
        """Runtime identity for a trace (spec §19); never a token or a raw path."""
        return {
            "runtime": self.runtime.id,
            "version": self.version,
            "protocol": self.runtime.protocol,
            "transport": self.runtime.transport,
            "model": self.model,
            "executable": self._display_executable(),
        }

    # -- the neutral contract -------------------------------------------------

    def _execute[T: BaseModel](self, request: ModelRequest[T], schema_json: dict[str, Any]) -> RawCompletion:
        """One bounded run; the final text goes back through `ModelProvider.complete()`."""
        collected = _Collector()
        completion: RawCompletion | None = None
        for _text, done in self._run(request, schema_json=schema_json, collected=collected):
            if done is not None:
                completion = done
        if completion is None:  # pragma: no cover - `_run` always ends with the completion
            raise CliTransportError(f"{self._who()}: the run produced no completion", runtime=self.runtime.id, diagnostic="missing_terminal_event")
        return completion

    def stream(self, request: ModelRequest[Any]) -> Iterator[StreamDelta]:
        """Prose deltas for a `ChatReply` turn; the final delta carries model, stop, usage.

        A generator on purpose: a consumer that abandons it triggers `GeneratorExit` inside
        `_drive`, which cancels the process (spec §14).
        """
        collected = _Collector()
        index = 0
        for text, completion in self._run(request, schema_json=None, collected=collected):
            if completion is None:
                yield StreamDelta(text=text, index=index)
                index += 1
            else:
                yield StreamDelta(
                    text=text,
                    index=index,
                    final=True,
                    model=completion.model,
                    stop_reason=completion.stop_reason,
                    usage=completion.usage,
                )

    def _trace[T: BaseModel](self, sink: TraceSink, request: ModelRequest[T], response: ModelResponse[T]) -> None:
        try:
            sink.record(
                "completion",
                provider=self.name,
                model=response.model,
                request_fingerprint=response.request_fingerprint,
                payload={**trace_payload(request, response), "cli": self.trace_metadata()},
            )
        except Exception:
            logger.warning("could not write a %s completion trace", self.name, exc_info=True)

    # -- the run ----------------------------------------------------------------

    def _run(self, request: ModelRequest[Any], *, schema_json: dict[str, Any] | None, collected: _Collector) -> Iterator[tuple[str, RawCompletion | None]]:
        if media_parts(request.inputs):
            raise CliResponseError(
                f"{describe_runtime(self.runtime.id, self.model, self.version)}: CLI providers accept text-only inputs in this release",
                runtime=self.runtime.id,
                diagnostic="invalid_invocation",
            )
        env_base: Mapping[str, str] = self._env if self._env is not None else _os_environ()
        executable = self._executable or resolve_executable(self.runtime, env_base)
        self._resolved = executable
        if executable is None:
            raise classify_failure(runtime=self.runtime.id, model=self.model, version=self.version, os_error="ENOENT: no executable on PATH", login_guidance=self.runtime.login_guidance)
        prompt = render_prompt(request, schema_json) if schema_json is not None else render_chat_prompt(request)
        cwd = Path(tempfile.mkdtemp(prefix="rh-cli-"))
        try:
            schema_path: Path | None = None
            if schema_json is not None:
                schema_path = cwd / "response.schema.json"
                schema_path.write_text(canonical_json(schema_json), encoding="utf-8")
            invocation = CliInvocation(
                model=None if self.model == DEFAULT_MODEL else self.model,
                reasoning=self._effort(request),
                cwd=cwd,
                request_id=uuid4().hex,
                schema_path=schema_path,
            )
            argv = (str(executable), *self.runtime.build_args(invocation))
            env = bounded_environment(self.runtime, env_base, executable=executable)
            yield from self._drive(argv, env, cwd, prompt, invocation, collected)
        finally:
            shutil.rmtree(cwd, ignore_errors=True)

    def _drive(self, argv: tuple[str, ...], env: Mapping[str, str], cwd: Path, prompt: str, invocation: CliInvocation, collected: _Collector) -> Iterator[tuple[str, RawCompletion | None]]:
        parser = parser_for(self.runtime)
        transport = transport_for(self.runtime)
        process = self._spawn(argv, env=env, cwd=cwd, timeout=self._timeout)
        self.last_process = process
        with process:
            transport.start(process, prompt, invocation)
            try:
                for line in process.lines():
                    if transport.intercept(process, line):
                        continue
                    for event in parser.feed(line):
                        transport.observe(process, event)
                        delta = collected.take(event)
                        if delta:
                            yield delta, None
                        if collected.finished:
                            break
                    if collected.finished:
                        break
                else:
                    for event in parser.finish():
                        delta = collected.take(event)
                        if delta:
                            yield delta, None
            except ProcessTimeout:
                transport.cancel(process)
                process.cancel()
                raise self._failure(process, timed_out=True) from None
            except OutputLimitExceeded:
                raise self._failure(process, output_limited=True) from None
            except GeneratorExit:
                transport.cancel(process)
                process.cancel()
                raise
            if collected.tool is not None:
                transport.cancel(process)
                process.cancel()
                raise CliResponseError(
                    f"{self._who()}: the runtime tried to use a tool ({collected.tool}) in bounded mode; the request was cancelled",
                    runtime=self.runtime.id,
                    diagnostic="bounded_authority_violation",
                )
            if collected.error is not None:
                process.cancel()
                raise self._failure(process, stream_error=collected.error.message, stream_code=collected.error.code)
            exit_code = process.wait(self._grace())
            if exit_code is None:
                process.cancel()
                exit_code = process.exit_code
            if not collected.done:
                raise self._failure(process, exit_code=exit_code)
        text = collected.text()
        if not text.strip():
            raise CliResponseError(f"{self._who()}: the runtime completed without an answer", runtime=self.runtime.id, diagnostic="empty_response")
        yield "", RawCompletion(text=text, usage=collected.usage, model=collected.model or self.model, stop_reason=collected.stop_reason or "end_turn")

    # -- helpers ----------------------------------------------------------------

    def _effort(self, request: ModelRequest[Any]) -> str | None:
        if self.reasoning:
            return self.reasoning
        level = request.requirements.reasoning
        return level if level in self.runtime.reasoning_choices else None

    def _grace(self) -> float:
        return min(5.0, self._timeout)

    def _who(self) -> str:
        return describe_runtime(self.runtime.id, self.model, self.version)

    def _display_executable(self) -> str | None:
        path = self._executable or self._resolved
        return None if path is None else redact(str(path))

    def _failure(self, process: BoundedProcess, **fields: Any) -> Exception:
        return classify_failure(
            runtime=self.runtime.id,
            model=self.model,
            version=self.version,
            stderr_tail=process.stderr_tail(),
            login_guidance=self.runtime.login_guidance,
            exit_code=fields.pop("exit_code", process.exit_code),
            **fields,
        )



def _os_environ() -> Mapping[str, str]:
    import os

    return os.environ
```

Implementer notes: (1) `stream()` is a generator so that a consumer's `close()` reaches the `GeneratorExit` branch in `_drive` — that is what `test_abandoning_the_stream_cancels_the_process` measures. (2) The provider never probes `--version` itself; `version` is passed in by a caller that learned it from a scan (Task 10's `provider.cli.test`), and `build_router` leaves it `None`. (3) `default_cli_capabilities` sets `reasoning_levels` to the three harness levels for every runtime: the requested level *routes*, and `_effort` maps it to a flag only when the runtime offers that name.

- [ ] **Step 4: Router, streaming, egress, and export changes**

In `providers/models/router.py`:

```python
ProviderKind = Literal["openai", "anthropic", "local_openai_compatible", "local_cli"]
```

`RouterProviderConfig` gains, after `enabled`:

```python
    runtime: str | None = None
    """`kind: local_cli` only: the runtime id (`codex`, `claude`, ...) from the CLI registry."""
    reasoning: str | None = None
    """`kind: local_cli` only: the runtime's own effort name to send on every request."""

    @model_validator(mode="after")
    def _cli_fields_match_the_kind(self) -> RouterProviderConfig:
        if self.kind == "local_cli":
            if not self.runtime:
                raise ValueError("runtime is required for kind local_cli (one of: " + ", ".join(_runtime_ids()) + ")")
            for field in ("base_url", "api_key_env"):
                if getattr(self, field) is not None:
                    raise ValueError(f"{field} is not allowed for kind local_cli: a CLI provider uses the CLI's own login")
            try:
                _get_runtime(self.runtime)
            except KeyError as exc:
                raise ValueError(str(exc)) from exc
        elif self.runtime is not None or self.reasoning is not None:
            raise ValueError("runtime is only for kind local_cli")
        return self
```

with two module-level helpers that import lazily (so `router.py` does not import the CLI package at import time — `providers/cli/registry.py` imports `privacy.policy`, which is fine, but keeping the seam lazy avoids any future cycle):

```python
def _get_runtime(runtime: str) -> Any:
    from research_harness.providers.cli.registry import get_runtime

    return get_runtime(runtime)


def _runtime_ids() -> tuple[str, ...]:
    from research_harness.providers.cli.registry import RUNTIME_IDS

    return RUNTIME_IDS
```

`_build_entry`: build `kwargs` only for the HTTP kinds; add before the `if provider_config.kind == "openai"` chain:

```python
    if provider_config.kind == "local_cli":
        from research_harness.providers.cli.provider import CliModelProvider

        assert provider_config.runtime is not None
        provider = CliModelProvider(
            provider_config.runtime,
            provider_config.model,
            reasoning=provider_config.reasoning,
            timeout=provider_config.timeout_seconds or 300.0,
            capabilities=capabilities,
            env=env,
        )
        return ProviderEntry(provider=provider, model=provider_config.model, priority=provider_config.priority, roles=set(provider_config.roles) if provider_config.roles is not None else None, tags={provider_config.name, *provider_config.tags})
```

`entry_base_url`: `if provider_config.kind == "local_cli": return ""`. `_default_capabilities(kind, base_url)` becomes `_default_capabilities(provider_config: RouterProviderConfig)`:

```python
def _default_capabilities(provider_config: RouterProviderConfig) -> ProviderCapabilities:
    if provider_config.kind == "local_cli":
        from research_harness.providers.cli.provider import default_cli_capabilities

        return default_cli_capabilities(_get_runtime(provider_config.runtime or ""), provider_config.model)
    base_url = entry_base_url(provider_config)
    if provider_config.kind == "openai":
        return default_openai_capabilities(base_url)
    if provider_config.kind == "anthropic":
        return default_anthropic_capabilities(base_url)
    return default_local_capabilities(base_url)
```

and `entry_capabilities` calls `_merge_capabilities(_default_capabilities(provider_config), provider_config.capabilities)`.

In `privacy/egress.py` `_model_entry`: `key_env = provider_config.api_key_env or MODEL_KEY_ENV_VARS.get(provider_config.kind)`.

In `providers/models/streaming.py` `NativeStream._record`, build the payload as:

```python
        payload = trace_payload(request, response)
        metadata = getattr(self._provider, "trace_metadata", None)
        if callable(metadata):
            payload = {**payload, "cli": metadata()}
```

and pass `payload=payload`.

Do **not** export `CliModelProvider` from `providers/models/__init__.py`: `providers/cli/provider.py` imports `providers.models.base`, so a module-level import back from the `models` package would be a cycle. The public home is `providers/cli/__init__.py`: add `CliModelProvider`, `default_cli_capabilities` (from `.provider`) and `scan`, `detect` (from `.detection`) to its imports and `__all__`.

- [ ] **Step 5: Run the new tests, then the whole provider and privacy suites**

Run: `uv run pytest tests/contract/providers tests/unit/providers tests/integration/privacy tests/contract/capabilities/test_providers.py tests/contract/capabilities/test_server_egress.py -q`
Expected: PASS — including every pre-existing test in those directories (the `_default_capabilities` signature change must not disturb them).

- [ ] **Step 6: Run the full gates**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/research_harness/providers src/research_harness/privacy/egress.py tests/contract/providers/test_cli_provider.py tests/unit/providers/cli/test_router_config.py
git commit -m "feat(cli-providers): CliModelProvider behind the neutral contract, kind local_cli in the router"
```

---
### Task 9: Cursor Agent, Amp, DeepSeek Harness, OpenCode, and Pi definitions

Spec §9, §12, §21. None of these five CLIs is installed on this workstation, so their flags are ported from the pinned Open Design definitions and their bounded posture is declared **only as far as it can be proven by a help probe**; where Open Design's only non-interactive path is a bypass flag, the posture is `none` and the runtime is detected but never routed (spec §12: "there is no prompt-only safety fallback"). Each definition begins with a recorded failing contract test.

**Files:**
- Create: `src/research_harness/providers/cli/defs/cursor_agent.py`, `amp.py`, `deepseek_harness.py`, `opencode.py`, `pi.py`
- Modify: `src/research_harness/providers/cli/defs/__init__.py` (`SHIPPED_DEFS = (CODEX, CLAUDE, CURSOR_AGENT, AMP, DEEPSEEK_HARNESS, OPENCODE, PI)`)
- Create: `tests/fixtures/cli/probes/cursor-status-ok.txt`, `cursor-status-missing.txt`, `cursor-models.txt`, `dsh-probe.jsonl`, `dsh-models.jsonl`, `opencode-models-verbose.txt`, `pi-list-models.txt`
- Test: `tests/unit/providers/cli/test_defs_others.py`, additions to `tests/contract/providers/test_cli_provider.py`

**Interfaces:**
- Produces: `CURSOR_AGENT`, `AMP`, `DEEPSEEK_HARNESS`, `OPENCODE`, `PI` (`CliRuntimeDef`), and per-module builders `cursor_args`, `cursor_auth`, `parse_cursor_models`, `amp_args`, `dsh_args`, `dsh_probe_version`, `parse_dsh_models`, `parse_dsh_semver`, `opencode_args`, `parse_opencode_models`, `pi_args`, `parse_pi_models`.

The matrix (from open-design@9bb4a7d `runtimes/defs/*.ts`, bypass flags removed):

| id | executable (fallbacks) | version | auth probe | model probe | argv (bounded) | protocol / transport | posture | egress |
|---|---|---|---|---|---|---|---|---|
| `cursor-agent` | `cursor-agent` | `--version` | `status` (text: "not logged in" → missing) | `models` (one id per line; "No models available" → None) | `--print --output-format stream-json --stream-partial-output --workspace <cwd> [--model M]` | `json_events`/`cursor_agent`, `stdin_text` | `none` — Open Design needs `--force` to run headless without approval; no deny flag is documented, so `bounded_mode` is `unsupported` until a version documents one | `unknown_external` |
| `amp` | `amp` | `--version` | none | none; fallback `smart`, `deep`, `rush` (modes, sent as `--mode`) | `-x --stream-json [--mode M]` | `claude_stream`, `stdin_text` | `none` — headless Amp blocks on approval unless `--dangerously-allow-all`; unsupported | `unknown_external` |
| `deepseek-harness` | `dsh` | `--version` (strict `v?X.Y.Z[-pre]`) | `--profile open-design --probe` (a `probe` frame → ok; absent profile → unknown) | `--profile open-design --models` (a `models` frame) | `--profile open-design --stdio` | `dsh_profile`, `dsh_profile` | `native_env` proven by the probe frame's `capabilities.structured_events` — but the profile executes tools of its own, so `kind="none"` until upstream documents a tool-less execute; unsupported | `unknown_external` |
| `opencode` | `opencode-cli` (`opencode`) | `--version` | none | `models --verbose` (ids matching `^[A-Za-z0-9][\w.-]*/[\w./:@-]+$`, variants → reasoning) | `run --format json --dir <cwd> [-m M] [--variant R]` with `env_set` `OPENCODE_CONFIG_CONTENT={"permission":{"edit":"deny","bash":"deny","webfetch":"deny"}}`, `OPENCODE_DISABLE_PROJECT_CONFIG=true` | `json_events`/`opencode`, `stdin_text` | `native_env`; help probe `run --help` must show `--format` and `--dir` | `unknown_external` |
| `pi` | `pi` | `--version` (15 s) | none | `--list-models` (TSV: provider, model per line after a header) | `--mode rpc [--model M] [--thinking R]` | `pi_rpc`, `pi_rpc` | `native_flags` requires `--tools` in `--help` and then sends `--tools ""`? — **not documented upstream**; declare `kind="none"`, unsupported | `unknown_external` |

Reasoning choices: cursor `()`, amp `()`, dsh `("low", "medium", "high")` (sent as `reasoning_effort`), opencode `()` (variants are per model, not sent), pi `("minimal", "low", "medium", "high", "xhigh")` (sent as `--thinking`).

- [ ] **Step 1: Write the probe fixtures**

`cursor-status-ok.txt`: `Logged in as researcher (Pro)`. `cursor-status-missing.txt`: `Not logged in. Run cursor-agent login to authenticate.`. `cursor-models.txt`: three lines `auto`, `sonnet-4`, `gpt-5`. `dsh-probe.jsonl`: `{"v":1,"type":"probe","runtime":"open-design","protocol_version":1,"plugin_version":"0.1.1","capabilities":{"session_resume":true,"session_cancel":true,"structured_events":true}}`. `dsh-models.jsonl`: `{"v":1,"type":"models","runtime":"open-design","models":[{"provider":"deepseek","provider_name":"DeepSeek","id":"deepseek-v3","name":"DeepSeek V3","reasoning_options":[{"id":"low","name":"Low"},{"id":"high","name":"High","default":true}]}]}`. `opencode-models-verbose.txt`:

```
anthropic/claude-sonnet-4-5
{
  "variants": {"low": {}, "high": {}}
}
openai/gpt-5
```

`pi-list-models.txt`:

```
PROVIDER   MODEL                      CONTEXT
anthropic  claude-sonnet-4-5          200000
openai     gpt-5                      400000
```

- [ ] **Step 2: Write the failing tests**

`tests/unit/providers/cli/test_defs_others.py`:

```python
"""The five remaining definitions: ported flags, honest postures (spec §9, §12, §21)."""

from __future__ import annotations

import json
from pathlib import Path

from research_harness.providers.cli.defs.amp import AMP, amp_args
from research_harness.providers.cli.defs.cursor_agent import CURSOR_AGENT, cursor_args, cursor_auth, parse_cursor_models
from research_harness.providers.cli.defs.deepseek_harness import DEEPSEEK_HARNESS, dsh_args, dsh_probe_version, parse_dsh_models, parse_dsh_semver
from research_harness.providers.cli.defs.opencode import OPENCODE, opencode_args, parse_opencode_models
from research_harness.providers.cli.defs.pi import PI, parse_pi_models, pi_args
from research_harness.providers.cli.registry import FORBIDDEN_ARGS, RUNTIME_IDS, RUNTIMES, validate_definition
from research_harness.providers.cli.types import UNKNOWN_EXTERNAL_HOST, CliInvocation, ProbeOutcome

PROBES = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "cli" / "probes"


def outcome(name: str, exit_code: int = 0) -> ProbeOutcome:
    return ProbeOutcome(argv=("x",), exit_code=exit_code, stdout=(PROBES / name).read_text(encoding="utf-8"), stderr="")


def invocation(model: str | None = None, reasoning: str | None = None) -> CliInvocation:
    return CliInvocation(model=model, reasoning=reasoning, cwd=Path("/tmp/rh-cli-x"), request_id="req-1")


def test_all_seven_runtimes_are_registered_in_display_order() -> None:
    assert RUNTIME_IDS == ("codex", "claude", "cursor-agent", "amp", "deepseek-harness", "opencode", "pi")
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
    assert args[:3] == ("--print", "--output-format", "stream-json") and "--stream-partial-output" in args
    assert ("--workspace", "/tmp/rh-cli-x") == args[args.index("--workspace") : args.index("--workspace") + 2]
    assert ("--model", "sonnet-4") == args[-2:]
    assert "--force" not in args and "--trust" not in args
    assert cursor_auth(outcome("cursor-status-ok.txt")) == ("ok", "")
    assert cursor_auth(outcome("cursor-status-missing.txt", exit_code=1))[0] == "missing"
    assert [m.id for m in parse_cursor_models(outcome("cursor-models.txt")) or ()] == ["auto", "sonnet-4", "gpt-5"]
    assert parse_cursor_models(ProbeOutcome(argv=("x",), exit_code=0, stdout="No models available for this account.", stderr="")) is None
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
    assert dsh_args(invocation(model="deepseek/deepseek-v3", reasoning="high")) == ("--profile", "open-design", "--stdio")
    assert parse_dsh_semver(ProbeOutcome(argv=("x",), exit_code=0, stdout="v0.1.1-rc.2\n", stderr="")) == "0.1.1-rc.2"
    assert parse_dsh_semver(ProbeOutcome(argv=("x",), exit_code=0, stdout="dsh 0.1.1\n", stderr="")) is None
    assert dsh_probe_version(outcome("dsh-probe.jsonl")) == ("ok", "")
    assert dsh_probe_version(ProbeOutcome(argv=("x",), exit_code=1, stdout="", stderr="profile not installed"))[0] == "unknown"
    models = parse_dsh_models(outcome("dsh-models.jsonl"))
    assert models is not None and models[0].id == "deepseek/deepseek-v3" and models[0].reasoning == ("low", "high")
    assert DEEPSEEK_HARNESS.reasoning_choices == ("low", "medium", "high")
    assert DEEPSEEK_HARNESS.posture.kind == "none" and DEEPSEEK_HARNESS.transport == "dsh_profile"
    assert DEEPSEEK_HARNESS.minimum_version == "0.1.0" and "DSH_HOME" in DEEPSEEK_HARNESS.env_keep


# -- opencode ------------------------------------------------------------------


def test_opencode_argv_env_and_models() -> None:
    args = opencode_args(invocation(model="openai/gpt-5"))
    assert args[:3] == ("run", "--format", "json") and ("--dir", "/tmp/rh-cli-x") == args[3:5]
    assert ("-m", "openai/gpt-5") == args[-2:] and "--variant" not in args
    assert "--dangerously-skip-permissions" not in args
    permission = json.loads(OPENCODE.env_set["OPENCODE_CONFIG_CONTENT"])["permission"]
    assert permission == {"edit": "deny", "bash": "deny", "webfetch": "deny"}
    assert OPENCODE.env_set["OPENCODE_DISABLE_PROJECT_CONFIG"] == "true"
    assert OPENCODE.posture.kind == "native_env" and OPENCODE.posture.required_help_flags == ("--format", "--dir")
    models = parse_opencode_models(outcome("opencode-models-verbose.txt"))
    assert models is not None and [m.id for m in models] == ["anthropic/claude-sonnet-4-5", "openai/gpt-5"]
    assert models[0].reasoning == ("low", "high") and OPENCODE.fallback_executables == ("opencode",)


# -- pi ------------------------------------------------------------------------


def test_pi_argv_and_models() -> None:
    assert pi_args(invocation()) == ("--mode", "rpc")
    assert pi_args(invocation(model="anthropic/claude-sonnet-4-5", reasoning="high")) == ("--mode", "rpc", "--model", "anthropic/claude-sonnet-4-5", "--thinking", "high")
    models = parse_pi_models(outcome("pi-list-models.txt"))
    assert models is not None and [m.id for m in models] == ["anthropic/claude-sonnet-4-5", "openai/gpt-5"]
    assert parse_pi_models(ProbeOutcome(argv=("x",), exit_code=0, stdout="", stderr="")) is None
    assert PI.posture.kind == "none" and PI.version_probe.timeout_seconds == 15.0
    assert PI.reasoning_choices == ("minimal", "low", "medium", "high", "xhigh")
```

Additions to `tests/contract/providers/test_cli_provider.py` — one recorded contract case per new runtime, driven through the fake executable with its stream fixture, **bypassing the posture gate on purpose** (the provider itself never checks posture; the capability layer does, Task 10), so the wire behaviour is pinned even for runtimes that are not routable:

```python
OTHERS = [
    ("cursor-agent", "cursor-success.jsonl", {"before_input": [], "read_stdin": True}),
    ("amp", "amp-success.jsonl", {}),
    ("opencode-cli", "opencode-success.jsonl", {}),
    ("dsh", "dsh-success.jsonl", {"before_input": [lines("dsh-success.jsonl")[0]], "read_one_line": True}),
    ("pi", "pi-success.jsonl", {"read_one_line": True}),
]


@pytest.mark.parametrize(("executable", "fixture", "extra"), OTHERS, ids=[case[0] for case in OTHERS])
def test_every_other_runtime_answers_the_same_contract(tmp_path: Path, model_request: ModelRequest[Verdict], executable: str, fixture: str, extra: dict[str, object]) -> None:
    runtime = {"cursor-agent": "cursor-agent", "amp": "amp", "opencode-cli": "opencode", "dsh": "deepseek-harness", "pi": "pi"}[executable]
    body = lines(fixture)
    if executable == "dsh":
        body = body[1:]  # `ready` is emitted before the execute command is read
    fake = FakeCli.install(tmp_path, executable, run={"lines": body, **extra})
    adapter = CliModelProvider(runtime, env=fake.env({"PATH": ""}), timeout=10)

    response = adapter.complete(model_request)

    assert response.parsed == EXPECTED_VERDICT and response.provider == f"local_cli:{runtime}"
    run = fake.runs()[0]
    assert "Table 3 reports" in (run["stdin"] or "")
    assert not any("Table 3" in arg for arg in run["argv"])
    if executable == "dsh":
        command = json.loads(run["stdin"])
        assert command["type"] == "execute" and command["mcp_servers"] == [] and "Table 3 reports" in command["prompt"]
    if executable == "pi":
        assert json.loads(run["stdin"])["type"] == "prompt"
    if executable == "opencode-cli":
        assert json.loads(run["env"]["OPENCODE_CONFIG_CONTENT"])["permission"]["bash"] == "deny"


@pytest.mark.parametrize(("executable", "fixture"), [("cursor-agent", "cursor-tool.jsonl"), ("amp", "claude-tool.jsonl"), ("opencode-cli", "opencode-tool.jsonl"), ("dsh", "dsh-tool.jsonl"), ("pi", "pi-tool.jsonl")])
def test_every_other_runtime_fails_on_a_tool_event(tmp_path: Path, model_request: ModelRequest[Verdict], executable: str, fixture: str) -> None:
    runtime = {"cursor-agent": "cursor-agent", "amp": "amp", "opencode-cli": "opencode", "dsh": "deepseek-harness", "pi": "pi"}[executable]
    body = lines(fixture)
    extra: dict[str, object] = {}
    if executable == "dsh":
        extra = {"before_input": [body[0]], "read_one_line": True}
        body = body[1:]
    if executable == "pi":
        extra = {"read_one_line": True}
    fake = FakeCli.install(tmp_path, executable, run={"lines": [*body, {"sleep": 30}], "hang": True, **extra})
    with pytest.raises(CliResponseError) as caught:
        CliModelProvider(runtime, env=fake.env({"PATH": ""}), timeout=10).complete(model_request)
    assert caught.value.diagnostic == "bounded_authority_violation"
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/unit/providers/cli/test_defs_others.py tests/contract/providers/test_cli_provider.py -q`
Expected: FAIL — the five modules do not exist.

- [ ] **Step 4: Write the five definitions**

`defs/cursor_agent.py`:

```python
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

_NOT_LOGGED_IN = re.compile(r"not (?:logged in|authenticated)|please (?:log|sign) in|run .*login", re.IGNORECASE)
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
    ids = [line.strip() for line in outcome.stdout.splitlines() if line.strip() and not line.startswith("#")]
    seen: list[str] = []
    for item in ids:
        if item not in seen:
            seen.append(item)
    return tuple(CliModelOption(id=item, label=item) for item in seen) or None


def cursor_args(invocation: CliInvocation) -> tuple[str, ...]:
    args = ["--print", "--output-format", "stream-json", "--stream-partial-output", "--workspace", str(invocation.cwd)]
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
    fallback_models=(CliModelOption(id="auto", label="auto"), CliModelOption(id="sonnet-4", label="sonnet-4"), CliModelOption(id="gpt-5", label="gpt-5")),
    reasoning_choices=(),
    protocol="json_events",
    json_events_variant="cursor_agent",
    transport="stdin_text",
    build_args=cursor_args,
    posture=BoundedPosture(kind="none", note="headless Cursor Agent runs only with --force (approval bypass); no deny-tools flag is documented"),
    egress="unknown_external",
    egress_host=UNKNOWN_EXTERNAL_HOST,
    default_context_tokens=128_000,
    login_guidance="run `cursor-agent login`",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/cursor-agent.ts",
    env_keep=("CURSOR_CONFIG_DIR",),
)
```

`defs/amp.py`:

```python
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
    fallback_models=(CliModelOption(id="smart", label="Smart (mode)"), CliModelOption(id="deep", label="Deep (mode)"), CliModelOption(id="rush", label="Rush (mode)")),
    reasoning_choices=(),
    protocol="claude_stream",
    transport="stdin_text",
    build_args=amp_args,
    posture=BoundedPosture(kind="none", note="headless Amp waits for approval unless --dangerously-allow-all; no deny-tools flag is documented"),
    egress="unknown_external",
    egress_host=UNKNOWN_EXTERNAL_HOST,
    default_context_tokens=128_000,
    login_guidance="run `amp login`",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/amp.ts",
)
```

`defs/deepseek_harness.py`:

```python
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

__all__ = ["DEEPSEEK_HARNESS", "dsh_args", "dsh_probe_version", "parse_dsh_models", "parse_dsh_semver"]

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
    if frame is None or frame.get("type") != "models" or not isinstance(frame.get("models"), list):
        return None
    options: list[CliModelOption] = []
    for item in frame["models"]:  # type: ignore[union-attr]
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) for key in ("provider", "id", "name", "provider_name")):
            return None
        efforts = tuple(e["id"] for e in item.get("reasoning_options", []) if isinstance(e, dict) and isinstance(e.get("id"), str))
        options.append(CliModelOption(id=f"{item['provider']}/{item['id']}", label=f"{item['name']} · {item['provider_name']}", reasoning=efforts))
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
    posture=BoundedPosture(kind="none", note="the open-design profile executes its own tools; generation 1 has no tool-less execute"),
    egress="unknown_external",
    egress_host=UNKNOWN_EXTERNAL_HOST,
    default_context_tokens=128_000,
    login_guidance="configure a provider in `dsh` and install the open-design profile",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/deepseek-harness.ts",
    minimum_version="0.1.0",
    env_keep=("DSH_HOME",),
)
```

`defs/opencode.py`:

```python
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
    fallback_models=(CliModelOption(id="anthropic/claude-sonnet-4-5", label="anthropic/claude-sonnet-4-5"), CliModelOption(id="openai/gpt-5", label="openai/gpt-5")),
    reasoning_choices=(),
    protocol="json_events",
    json_events_variant="opencode",
    transport="stdin_text",
    build_args=opencode_args,
    posture=BoundedPosture(
        kind="native_env",
        help_probe=Probe(args=("run", "--help"), timeout_seconds=5.0),
        required_help_flags=("--format", "--dir"),
        note="permission table injected through OPENCODE_CONFIG_CONTENT denies edit, bash, and webfetch",
    ),
    egress="unknown_external",
    egress_host=UNKNOWN_EXTERNAL_HOST,
    default_context_tokens=128_000,
    login_guidance="run `opencode auth login`",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/opencode.ts",
    env_keep=("OPENCODE_CONFIG",),
    env_set={
        "OPENCODE_CONFIG_CONTENT": json.dumps({"permission": {"edit": "deny", "bash": "deny", "webfetch": "deny"}}),
        "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
    },
)
```

`defs/pi.py`:

```python
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
    rows = [line.strip() for line in outcome.stdout.splitlines() if line.strip() and not line.startswith("#")]
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
    fallback_models=(CliModelOption(id="anthropic/claude-sonnet-4-5", label="Claude Sonnet 4.5 (anthropic)"), CliModelOption(id="openai/gpt-5", label="GPT-5 (openai)")),
    reasoning_choices=("minimal", "low", "medium", "high", "xhigh"),
    protocol="pi_rpc",
    transport="pi_rpc",
    build_args=pi_args,
    posture=BoundedPosture(kind="none", note="pi runs its own tools inside the RPC session; no tool-less mode is documented"),
    egress="unknown_external",
    egress_host=UNKNOWN_EXTERNAL_HOST,
    default_context_tokens=200_000,
    login_guidance="configure a provider key inside `pi`",
    upstream_source="open-design@9bb4a7d apps/daemon/src/runtimes/defs/pi.ts",
)
```

`defs/__init__.py`: import the five and set `SHIPPED_DEFS = (CODEX, CLAUDE, CURSOR_AGENT, AMP, DEEPSEEK_HARNESS, OPENCODE, PI)`.

- [ ] **Step 5: Run the tests and gates**

Run: `uv run pytest tests/unit/providers/cli tests/contract/providers/test_cli_provider.py -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/research_harness/providers/cli/defs tests/fixtures/cli/probes tests/unit/providers/cli/test_defs_others.py tests/contract/providers/test_cli_provider.py
git commit -m "feat(cli-providers): Cursor Agent, Amp, DeepSeek Harness, OpenCode, and Pi definitions with honest bounded postures"
```

---

### Task 10: Workspace write, the four capabilities, and CLI rows in `provider.list`

Spec §11, §16, §19, §20 (capability tests). One server-side truth for scan/configure/remove/test.

**Files:**
- Modify: `src/research_harness/workspace/repository.py` (`WorkspaceConfig.with_providers`, `WorkspaceRepository.update_providers`)
- Create: `src/research_harness/capabilities/cli_providers.py`
- Modify: `src/research_harness/capabilities/providers.py`
- Modify: `tests/e2e/test_cli_capability_parity.py` (`V11_CLI_COUNTERPARTS`), `tests/contract/protocol/test_new_capability_parity.py` (`NEW_CAPABILITIES`, `NEW_MUTATIONS`)
- Test: `tests/contract/capabilities/test_cli_providers.py`, `tests/integration/workspace/test_update_providers.py`

**Interfaces:**
- Produces (workspace): `WorkspaceConfig.with_providers(providers: Sequence[Mapping[str, Any]]) -> WorkspaceConfig`; `WorkspaceRepository.update_providers(providers) -> WorkspaceConfig` (same lock/journal path as `update_config`; no `ResearchEvent`).
- Produces (capabilities): request models `ScanCliRuntimesRequest(rescan: bool = False)`, `ConfigureCliProviderRequest(name, runtime, model="default", priority=100, reasoning=None, timeout_seconds=None, roles=None, enabled=True)`, `RemoveCliProviderRequest(name)`, `TestCliProviderRequest(name)`; response models `CliScanReport(scanned_at, count, runtimes: tuple[CliRuntimeStatus,...], configured: tuple[ConfiguredCliProviderView,...], notice: str)`, `ConfiguredCliProviderView(name, runtime, model, priority, enabled, reasoning, timeout_seconds, roles, available, unavailable_reason)`, `CliProviderConfigured(entry, created, file="research.yaml")`, `CliProviderRemoved(name, file="research.yaml")`, `CliProviderTestReport(name, runtime, model, version, egress_host, egress_kind, ok, latency_ms, message, diagnostic)`; handlers `scan_cli_runtimes`, `configure_cli_provider`, `remove_cli_provider`, `test_cli_provider`; `CLI_PROVIDER_CAPABILITIES`, `CLI_PROVIDER_CAPABILITY_HANDLERS`, `cli_provider_specs()`; `EXTERNAL_EGRESS_NOTICE` (the sentence every surface prints); `cli_availability(entry, statuses, policy_reason) -> tuple[bool, str | None]`.
- `providers.py`: `PROVIDER_CAPABILITIES` becomes `("provider.list", *CLI_PROVIDER_CAPABILITIES)`; `provider_specs()` returns the list spec plus `cli_provider_specs()`; `PROVIDER_CAPABILITY_HANDLERS` merges both; `list_providers` computes `available`/`unavailable_reason` for `local_cli` entries from the (cached) scan.

- [ ] **Step 1: Write the failing workspace test**

`tests/integration/workspace/test_update_providers.py`:

```python
"""`update_providers` is durable, atomic, secret-refusing, and event-free (spec §11, §16)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from research_harness.workspace.repository import WorkspaceRepository
from research_harness.workspace.serialization import WorkspaceSerializationError

ENTRY = {"name": "codex-sub", "kind": "local_cli", "runtime": "codex", "model": "default", "priority": 10}


def test_the_new_list_is_written_atomically_and_read_back(tmp_path: Path) -> None:
    repo = WorkspaceRepository.init(tmp_path / "p", "providers")
    events_before = (repo.layout.events_file.read_text(encoding="utf-8") if repo.layout.events_file.is_file() else "")

    config = repo.update_providers([ENTRY])

    assert config.providers == [ENTRY]
    assert yaml.safe_load(repo.layout.research_file.read_text(encoding="utf-8"))["providers"] == [ENTRY]
    assert WorkspaceRepository.open(repo.root).config.providers == [ENTRY]
    after = repo.layout.events_file.read_text(encoding="utf-8") if repo.layout.events_file.is_file() else ""
    assert after == events_before, "configuration is not scientific state; no ResearchEvent"
    assert not list(repo.root.glob(".tmp-*"))


def test_a_credential_in_the_new_list_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    repo = WorkspaceRepository.init(tmp_path / "p", "providers")
    before = repo.layout.research_file.read_bytes()
    with pytest.raises((ValueError, WorkspaceSerializationError), match="must not contain api_key"):
        repo.update_providers([{**ENTRY, "api_key": "sk-x"}])
    assert repo.layout.research_file.read_bytes() == before


def test_update_providers_may_run_inside_a_held_lock(tmp_path: Path) -> None:
    repo = WorkspaceRepository.init(tmp_path / "p", "providers")
    with repo.lock():
        assert repo.update_providers([ENTRY]).providers == [ENTRY]
```

- [ ] **Step 2: Write the failing capability tests**

`tests/contract/capabilities/test_cli_providers.py`:

```python
"""`provider.cli.*`: one server-side truth for scan, configure, remove, and test (spec §16).

Everything is driven through fake executables; the workstation's real CLIs are never run.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from starlette.testclient import TestClient

from research_harness.capabilities.cli_providers import (
    EXTERNAL_EGRESS_NOTICE,
    ConfigureCliProviderRequest,
    RemoveCliProviderRequest,
    ScanCliRuntimesRequest,
    TestCliProviderRequest,
    configure_cli_provider,
    remove_cli_provider,
    scan_cli_runtimes,
    test_cli_provider,
)
from research_harness.capabilities.context import CapabilityContext, open_context
from research_harness.capabilities.permissions import Permission, PermissionDenied, Principal
from research_harness.capabilities.providers import ListProvidersRequest, list_providers
from research_harness.capabilities.registry import build_default_registry
from research_harness.domain.errors import AuthorityError, CapabilityError
from research_harness.domain.transitions import HUMAN_ACTOR
from research_harness.providers.cli.detection import DEFAULT_CACHE
from research_harness.server.app import create_app, ensure_token
from research_harness.workspace.repository import WorkspaceRepository
from tests.fixtures.cli.fakes import FakeCli

STREAMS = Path(__file__).resolve().parents[2] / "fixtures" / "cli" / "streams"
HELP = "--sandbox --output-schema --json --ephemeral --skip-git-repo-check --ignore-user-config --ignore-rules"


def lines(name: str) -> list[str]:
    return [line for line in (STREAMS / name).read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]


def probe_reply() -> list[str]:
    body = {"ok": True, "echo": "will be replaced"}
    return [json.dumps({"type": "item.completed", "item": {"id": "i", "type": "agent_message", "text": json.dumps(body)}}), json.dumps({"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 2}})]


@pytest.fixture(autouse=True)
def fresh_cache() -> Iterator[None]:
    DEFAULT_CACHE.clear()
    yield
    DEFAULT_CACHE.clear()


@pytest.fixture
def codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCli:
    fake = FakeCli.install(
        tmp_path / "tools",
        "codex",
        version_stdout="codex-cli 0.150.1",
        probes=[{"args": ["login", "status"], "stdout": "Logged in using ChatGPT\n"}, {"args": ["exec", "--help"], "stdout": HELP}, {"args": ["debug", "models"], "stdout": json.dumps({"models": [{"slug": "gpt-5.5", "display_name": "GPT-5.5", "visibility": "list", "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}], "context_window": 272000}]})}],
        run={"lines": lines("codex-success.jsonl")},
    )
    monkeypatch.setenv("PATH", str(fake.bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-leak")
    return fake


@pytest.fixture
def project(tmp_path: Path) -> CapabilityContext:
    repo = WorkspaceRepository.init(tmp_path / "project", "cli-providers")
    return open_context(repo.root, HUMAN_ACTOR)


def configured(ctx: CapabilityContext) -> list[dict[str, Any]]:
    return list(yaml.safe_load(ctx.repo.layout.research_file.read_text(encoding="utf-8")).get("providers", []))


# -- scan ----------------------------------------------------------------------


def test_scan_lists_all_seven_runtimes_in_registry_order_and_edits_nothing(project: CapabilityContext, codex: FakeCli) -> None:
    before = project.repo.layout.research_file.read_bytes()
    report = scan_cli_runtimes(project, ScanCliRuntimesRequest())

    assert [item.runtime for item in report.runtimes] == ["codex", "claude", "cursor-agent", "amp", "deepseek-harness", "opencode", "pi"]
    assert report.count == 7 and report.notice == EXTERNAL_EGRESS_NOTICE
    found = report.runtimes[0]
    assert found.available and found.version == "0.150.1" and found.auth_status == "ok" and found.bounded_mode == "safe"
    assert found.compatibility == "verified" and [m.id for m in found.models] == ["default", "gpt-5.5"] and found.model_source == "live"
    assert not report.runtimes[1].available, "claude is not on the fake PATH"
    assert project.repo.layout.research_file.read_bytes() == before
    assert codex.runs() == []
    assert "sk-must-not-leak" not in report.model_dump_json()


def test_scan_reports_configured_entries_beside_the_runtimes(project: CapabilityContext, codex: FakeCli) -> None:
    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex", model="gpt-5.5"))
    report = scan_cli_runtimes(project, ScanCliRuntimesRequest(rescan=True))
    assert [item.name for item in report.configured] == ["codex-sub"]
    assert report.configured[0].available and report.configured[0].unavailable_reason is None


def test_scan_is_a_read_a_host_may_make(project: CapabilityContext, codex: FakeCli) -> None:
    registry = build_default_registry()
    spec = registry.get("provider.cli.scan")
    assert spec.permission is Permission.READ and not spec.descriptor().human_only
    result = registry.invoke("provider.cli.scan", project, {}, principal=Principal.agent_host("claude"))
    assert result.count == 7


# -- configure -----------------------------------------------------------------


def test_configure_writes_one_validated_entry(project: CapabilityContext, codex: FakeCli) -> None:
    result = configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex", model="gpt-5.5", priority=10, reasoning="high", timeout_seconds=120))

    assert result.created and result.file == "research.yaml"
    assert configured(project) == [{"name": "codex-sub", "kind": "local_cli", "runtime": "codex", "model": "gpt-5.5", "priority": 10, "reasoning": "high", "timeout_seconds": 120.0, "enabled": True}]
    again = configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex", model="default"))
    assert not again.created and configured(project)[0]["model"] == "default"


def test_configure_refuses_an_unavailable_or_unsafe_runtime(project: CapabilityContext, codex: FakeCli) -> None:
    with pytest.raises(CapabilityError, match="claude is not installed"):
        configure_cli_provider(project, ConfigureCliProviderRequest(name="c", runtime="claude"))
    codex.write_script({**codex.script(), "probes": [{"args": ["login", "status"], "stdout": "Logged in using ChatGPT\n"}, {"args": ["exec", "--help"], "stdout": "--json"}]})
    with pytest.raises(CapabilityError, match="no tested bounded"):
        configure_cli_provider(project, ConfigureCliProviderRequest(name="c", runtime="codex"))
    with pytest.raises(CapabilityError, match="unknown runtime 'nope'"):
        configure_cli_provider(project, ConfigureCliProviderRequest(name="c", runtime="nope"))
    assert configured(project) == []


def test_configure_will_not_take_over_an_http_entry_of_the_same_name(project: CapabilityContext, codex: FakeCli) -> None:
    project.repo.update_providers([{"name": "fast", "kind": "openai", "model": "gpt-x"}])
    with pytest.raises(CapabilityError, match="'fast' is an openai entry"):
        configure_cli_provider(project, ConfigureCliProviderRequest(name="fast", runtime="codex"))


def test_configure_and_remove_are_admin_and_human_only(project: CapabilityContext, codex: FakeCli) -> None:
    registry = build_default_registry()
    for name in ("provider.cli.configure", "provider.cli.remove"):
        spec = registry.get(name)
        assert spec.permission is Permission.ADMIN and spec.descriptor().human_only
    with pytest.raises(PermissionDenied):
        registry.invoke("provider.cli.configure", project, {"name": "c", "runtime": "codex"}, principal=Principal.agent_host("claude"))
    as_model = open_context(project.root, "vendor/model")
    with pytest.raises(AuthorityError):
        configure_cli_provider(as_model, ConfigureCliProviderRequest(name="c", runtime="codex"))


def test_remove_takes_only_the_named_cli_entry(project: CapabilityContext, codex: FakeCli) -> None:
    project.repo.update_providers([{"name": "fast", "kind": "openai", "model": "gpt-x"}])
    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex"))
    result = remove_cli_provider(project, RemoveCliProviderRequest(name="codex-sub"))
    assert result.name == "codex-sub" and [e["name"] for e in configured(project)] == ["fast"]
    with pytest.raises(CapabilityError, match="'fast' is an openai entry"):
        remove_cli_provider(project, RemoveCliProviderRequest(name="fast"))
    with pytest.raises(CapabilityError, match="no provider named 'gone'"):
        remove_cli_provider(project, RemoveCliProviderRequest(name="gone"))


# -- provider.list -------------------------------------------------------------


def test_a_configured_cli_entry_appears_in_the_catalog_as_external(project: CapabilityContext, codex: FakeCli) -> None:
    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex", model="gpt-5.5"))
    listed = list_providers(project, ListProvidersRequest())
    row = listed.models[0]
    assert row.id == "codex-sub" and row.label == "codex-sub/gpt-5.5" and row.provider == "local_cli"
    assert row.egress_class.value == "external" and row.available and row.default


def test_a_logged_out_runtime_is_listed_but_unavailable(project: CapabilityContext, codex: FakeCli) -> None:
    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex"))
    codex.write_script({**codex.script(), "probes": [{"args": ["login", "status"], "stdout": "Not logged in\n", "exit": 1}, {"args": ["exec", "--help"], "stdout": HELP}]})
    DEFAULT_CACHE.clear()
    row = list_providers(project, ListProvidersRequest()).models[0]
    assert not row.available and row.unavailable_reason == "codex is not logged in: run `codex login`"


def test_the_policy_is_asked_before_the_runtime(project: CapabilityContext, codex: FakeCli) -> None:
    from research_harness.privacy.policy import EgressPolicy

    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex"))
    project.repo.update_config(EgressPolicy(external_models="disabled"))
    row = list_providers(open_context(project.root, HUMAN_ACTOR), ListProvidersRequest()).models[0]
    assert not row.available and "privacy policy" in (row.unavailable_reason or "")


# -- test ----------------------------------------------------------------------


def test_the_test_call_runs_one_validated_request_and_reports_the_destination(project: CapabilityContext, codex: FakeCli) -> None:
    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex", model="gpt-5.5"))
    codex.set_run(lines=probe_reply())

    report = test_cli_provider(project, TestCliProviderRequest(name="codex-sub"))

    assert report.runtime == "codex" and report.model == "gpt-5.5" and report.version == "0.150.1"
    assert report.egress_host == "chatgpt.com" and report.egress_kind == "external"
    run = codex.runs()[0]
    assert "provider.cli.test" in run["stdin"]
    if report.ok:
        assert report.latency_ms is not None and report.diagnostic is None
    else:
        assert report.diagnostic == "structured_output" and "echo" in report.message
    assert list(project.repo.layout.traces_dir.glob("*/*.json")), "a test call is traced like any call"


def test_the_test_call_is_refused_by_the_policy_before_any_spawn(project: CapabilityContext, codex: FakeCli) -> None:
    from research_harness.privacy.policy import EgressPolicy

    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex"))
    project.repo.update_config(EgressPolicy(external_models="disabled"))
    report = test_cli_provider(open_context(project.root, HUMAN_ACTOR), TestCliProviderRequest(name="codex-sub"))
    assert not report.ok and report.diagnostic == "privacy_refused" and "privacy policy" in report.message
    assert codex.runs() == []


def test_the_test_call_reports_a_failure_without_a_secret(project: CapabilityContext, codex: FakeCli) -> None:
    configure_cli_provider(project, ConfigureCliProviderRequest(name="codex-sub", runtime="codex"))
    codex.set_run(lines=lines("codex-failed.jsonl"), stderr="token sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd")
    report = test_cli_provider(project, TestCliProviderRequest(name="codex-sub"))
    assert not report.ok and report.diagnostic == "unsupported_model"
    assert "sk-proj" not in report.model_dump_json()


def test_the_test_call_is_human_only_even_though_it_is_a_read(project: CapabilityContext, codex: FakeCli) -> None:
    registry = build_default_registry()
    spec = registry.get("provider.cli.test")
    assert spec.permission is Permission.READ and spec.human_only
    with pytest.raises(PermissionDenied):
        registry.invoke("provider.cli.test", project, {"name": "codex-sub"}, principal=Principal.agent_host("claude"))


# -- over HTTP -----------------------------------------------------------------


def test_configure_and_scan_answer_identically_over_the_daemon(project: CapabilityContext, codex: FakeCli) -> None:
    app = create_app(project.root, registry=build_default_registry())
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {ensure_token(project.root)}"
        served = client.post("/capabilities/provider.cli.configure", json={"name": "codex-sub", "runtime": "codex", "model": "gpt-5.5"}).json()
        assert served["ok"] is True and served["result"]["created"] is True
        scanned = client.post("/capabilities/provider.cli.scan", json={}).json()
        assert scanned["ok"] is True
    direct = scan_cli_runtimes(open_context(project.root, HUMAN_ACTOR), ScanCliRuntimesRequest()).model_dump(mode="json")
    assert scanned["result"]["configured"] == direct["configured"]
    assert [r["runtime"] for r in scanned["result"]["runtimes"]] == [r["runtime"] for r in direct["runtimes"]]
```

The fake's `probe_reply` echoes a fixed string rather than the nonce, so the `report.ok` branch pins that a wrong echo surfaces as `diagnostic="structured_output"` and never as a crash; a fake that echoed the nonce would take the `ok` branch.

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/integration/workspace/test_update_providers.py tests/contract/capabilities/test_cli_providers.py -q`
Expected: FAIL — `update_providers` and `capabilities.cli_providers` do not exist.

- [ ] **Step 4: Workspace changes**

In `WorkspaceConfig` add after `with_privacy`:

```python
    def with_providers(self, providers: Sequence[Mapping[str, Any]]) -> WorkspaceConfig:
        return self.model_validate({**self.model_dump(), "providers": [dict(item) for item in providers]})
```

(`model_validate` rather than `model_copy`, so the inline-secret validator runs.) In `WorkspaceRepository`, after `update_config`:

```python
    def update_providers(self, providers: Sequence[Mapping[str, Any]]) -> WorkspaceConfig:
        """Persist a new `providers:` table; same durability as `update_config`, no event.

        Configuration, not scientific state (see `update_config`). Validation runs before
        the write, so a credential in the new list is refused with the file untouched.
        """
        with self.lock():
            config = read_yaml(self._layout.research_file, WorkspaceConfig).with_providers(providers)
            transaction = Transaction(self._layout)
            transaction.write(self._layout.research_file, canonical_bytes(config))
            transaction.commit()
            self._note_commit(transaction.paths)
        self._refresh_config(config)
        return config
```

- [ ] **Step 5: Write `capabilities/cli_providers.py`**

```python
"""`provider.cli.scan|configure|remove|test`: subscription-backed CLIs (CLI providers spec §16).

One server-side source of truth. The Web settings screen, `research providers …`, and an
MCP host call these handlers and render what comes back; none of them probes an executable
or validates a configuration on its own. Scan is a read that edits nothing; configure and
remove are researcher acts on `research.yaml`; test is a read that causes external egress
and is therefore human-only.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from research_harness.capabilities.context import CapabilityContext
from research_harness.capabilities.dto import CapabilityRequest
from research_harness.capabilities.permissions import Permission
from research_harness.capabilities.registry import CapabilitySpec
from research_harness.domain.errors import AuthorityError, CapabilityError
from research_harness.privacy.policy import EgressDeniedError, load_policy
from research_harness.privacy.traces import trace_writer_for
from research_harness.providers.cli.detection import scan
from research_harness.providers.cli.errors import redact
from research_harness.providers.cli.registry import RUNTIMES, UnknownRuntimeError, get_runtime
from research_harness.providers.cli.types import CliRuntimeStatus, EgressKind, unavailable_reason
from research_harness.providers.models.base import (
    InputEnvelope,
    ModelRequest,
    ModelRequirements,
    ProviderError,
    StructuredOutputError,
)
from research_harness.providers.models.router import (
    ModelRouter,
    RouterConfig,
    RouterProviderConfig,
    build_router,
)

__all__ = [
    "CLI_PROVIDER_CAPABILITIES",
    "CLI_PROVIDER_CAPABILITY_HANDLERS",
    "EXTERNAL_EGRESS_NOTICE",
    "CliProbeReply",
    "CliProviderConfigured",
    "CliProviderRemoved",
    "CliProviderTestReport",
    "CliScanReport",
    "ConfiguredCliProviderView",
    "ConfigureCliProviderRequest",
    "RemoveCliProviderRequest",
    "ScanCliRuntimesRequest",
    "TestCliProviderRequest",
    "cli_availability",
    "cli_provider_specs",
    "configure_cli_provider",
    "remove_cli_provider",
    "scan_cli_runtimes",
    "test_cli_provider",
]

CLI_PROVIDER_CAPABILITIES: tuple[str, ...] = (
    "provider.cli.scan",
    "provider.cli.configure",
    "provider.cli.remove",
    "provider.cli.test",
)

EXTERNAL_EGRESS_NOTICE = (
    "A local CLI starts on this workstation, but the model it talks to is the vendor's: "
    "research content and object IDs leave the machine when a CLI provider is used."
)

_NAME = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"


# -- requests and responses ---------------------------------------------------


class ScanCliRuntimesRequest(CapabilityRequest):
    """`provider.cli.scan`: every supported runtime, fresh or from the short cache."""

    rescan: bool = False


class ConfiguredCliProviderView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    runtime: str
    model: str
    priority: int
    enabled: bool
    reasoning: str | None = None
    timeout_seconds: float | None = None
    roles: tuple[str, ...] | None = None
    available: bool
    unavailable_reason: str | None = None


class CliScanReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scanned_at: datetime
    count: int
    runtimes: tuple[CliRuntimeStatus, ...]
    configured: tuple[ConfiguredCliProviderView, ...]
    notice: str = EXTERNAL_EGRESS_NOTICE


class ConfigureCliProviderRequest(CapabilityRequest):
    """`provider.cli.configure`: add or update one `local_cli` entry in `research.yaml`."""

    name: str = Field(pattern=_NAME)
    runtime: str
    model: str = Field(default="default", min_length=1)
    priority: int = 100
    reasoning: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    roles: list[str] | None = None
    enabled: bool = True


class CliProviderConfigured(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entry: ConfiguredCliProviderView
    created: bool
    file: str = "research.yaml"


class RemoveCliProviderRequest(CapabilityRequest):
    name: str


class CliProviderRemoved(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    file: str = "research.yaml"


class TestCliProviderRequest(CapabilityRequest):
    name: str


class CliProviderTestReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    runtime: str
    model: str
    version: str | None
    egress_host: str
    egress_kind: EgressKind
    ok: bool
    latency_ms: int | None = None
    message: str
    diagnostic: str | None = None


class CliProbeReply(BaseModel):
    """What `provider.cli.test` asks for: `ok` and the nonce echoed back."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    echo: str


# -- helpers -------------------------------------------------------------------


def _entries(ctx: CapabilityContext) -> list[dict[str, Any]]:
    return [dict(item) for item in ctx.repo.config.providers]


def _require_human(ctx: CapabilityContext, capability: str) -> None:
    if not ctx.is_human:
        raise AuthorityError(f"{capability}: only a human actor may change or test provider configuration")


def _statuses(*, fresh: bool, only: set[str] | None = None) -> dict[str, CliRuntimeStatus]:
    definitions = [item for item in RUNTIMES.values() if only is None or item.id in only]
    return {status.runtime: status for status in scan(definitions, fresh=fresh)}


def cli_availability(
    entry: RouterProviderConfig, statuses: Mapping[str, CliRuntimeStatus], policy_reason: str | None
) -> tuple[bool, str | None]:
    """Policy first, then the runtime's own gates (spec §11)."""
    if policy_reason is not None:
        return False, f"refused by the privacy policy: {policy_reason}"
    status = statuses.get(entry.runtime or "")
    if status is None:
        return False, f"{entry.runtime} is not a supported runtime"
    reason = unavailable_reason(status)
    return reason is None, reason


def _view(entry: RouterProviderConfig, statuses: Mapping[str, CliRuntimeStatus]) -> ConfiguredCliProviderView:
    available, reason = cli_availability(entry, statuses, None)
    return ConfiguredCliProviderView(
        name=entry.name,
        runtime=entry.runtime or "",
        model=entry.model,
        priority=entry.priority,
        enabled=entry.enabled,
        reasoning=entry.reasoning,
        timeout_seconds=entry.timeout_seconds,
        roles=tuple(entry.roles) if entry.roles is not None else None,
        available=available,
        unavailable_reason=reason,
    )


def _cli_entries(ctx: CapabilityContext) -> list[RouterProviderConfig]:
    config = RouterConfig.model_validate({"providers": _entries(ctx)})
    return [item for item in config.providers if item.kind == "local_cli"]


# -- handlers ------------------------------------------------------------------


def scan_cli_runtimes(ctx: CapabilityContext, request: ScanCliRuntimesRequest) -> CliScanReport:
    """Fresh, bounded, fault-isolated detection of every supported runtime (spec §10)."""
    statuses = _statuses(fresh=request.rescan)
    ordered = tuple(statuses[item.id] for item in RUNTIMES.values())
    configured = tuple(_view(entry, statuses) for entry in _cli_entries(ctx))
    scanned_at = max((item.scanned_at for item in ordered), default=datetime.now(UTC))
    return CliScanReport(scanned_at=scanned_at, count=len(ordered), runtimes=ordered, configured=configured)


def configure_cli_provider(ctx: CapabilityContext, request: ConfigureCliProviderRequest) -> CliProviderConfigured:
    """Add or update one `local_cli` entry; refuses an unavailable or unsafe runtime (spec §11, §17)."""
    _require_human(ctx, "provider.cli.configure")
    try:
        definition = get_runtime(request.runtime)
    except UnknownRuntimeError as exc:
        raise CapabilityError(str(exc)) from exc
    status = _statuses(fresh=True, only={definition.id})[definition.id]
    reason = unavailable_reason(status)
    if reason is not None:
        raise CapabilityError(f"cannot configure {request.runtime}: {reason}")

    entry: dict[str, Any] = {
        "name": request.name,
        "kind": "local_cli",
        "runtime": request.runtime,
        "model": request.model,
        "priority": request.priority,
    }
    if request.reasoning is not None:
        entry["reasoning"] = request.reasoning
    if request.timeout_seconds is not None:
        entry["timeout_seconds"] = float(request.timeout_seconds)
    if request.roles is not None:
        entry["roles"] = list(request.roles)
    entry["enabled"] = request.enabled

    current = _entries(ctx)
    created = True
    replaced: list[dict[str, Any]] = []
    for item in current:
        if item.get("name") != request.name:
            replaced.append(item)
            continue
        if item.get("kind") != "local_cli":
            raise CapabilityError(f"provider {request.name!r} is an {item.get('kind')} entry; choose another name or remove it in research.yaml")
        created = False
        replaced.append(entry)
    if created:
        replaced.append(entry)
    RouterConfig.model_validate({"providers": replaced})  # the validation; a bad list never reaches the file
    ctx.repo.update_providers(replaced)
    stored = next(item for item in _cli_entries(ctx) if item.name == request.name)
    return CliProviderConfigured(entry=_view(stored, {definition.id: status}), created=created)


def remove_cli_provider(ctx: CapabilityContext, request: RemoveCliProviderRequest) -> CliProviderRemoved:
    """Remove exactly one `local_cli` entry and nothing else (spec §16)."""
    _require_human(ctx, "provider.cli.remove")
    current = _entries(ctx)
    match = next((item for item in current if item.get("name") == request.name), None)
    if match is None:
        raise CapabilityError(f"no provider named {request.name!r} in research.yaml")
    if match.get("kind") != "local_cli":
        raise CapabilityError(f"provider {request.name!r} is an {match.get('kind')} entry; `provider.cli.remove` only removes local_cli entries")
    ctx.repo.update_providers([item for item in current if item is not match])
    return CliProviderRemoved(name=request.name)


def test_cli_provider(ctx: CapabilityContext, request: TestCliProviderRequest) -> CliProviderTestReport:
    """One minimal schema-validated request through the configured entry (spec §16, §17)."""
    _require_human(ctx, "provider.cli.test")
    entry = next((item for item in _cli_entries(ctx) if item.name == request.name), None)
    if entry is None:
        raise CapabilityError(f"no local_cli provider named {request.name!r} in research.yaml")
    definition = get_runtime(entry.runtime or "")
    status = _statuses(fresh=True, only={definition.id})[definition.id]
    base = {
        "name": entry.name,
        "runtime": definition.id,
        "model": entry.model,
        "version": status.version,
        "egress_host": definition.egress_host,
        "egress_kind": definition.egress,
    }
    reason = unavailable_reason(status)
    if reason is not None:
        return CliProviderTestReport(**base, ok=False, message=reason, diagnostic="unavailable")

    policy = load_policy(ctx.repo)
    router = build_router(RouterConfig.model_validate({"providers": [entry.model_dump(mode="json", exclude_none=True)]}), policy=policy)
    refusal = router.egress_refusal()
    if refusal is not None:
        return CliProviderTestReport(**base, ok=False, message=refusal.message, diagnostic="privacy_refused")

    nonce = f"provider.cli.test-{os.urandom(4).hex()}"
    probe: ModelRequest[CliProbeReply] = ModelRequest(
        role="provider_test",
        requirements=ModelRequirements(structured_output=True, context_tokens=1_000, reasoning="low", max_output_tokens=200),
        instructions=f"This is a connectivity test. Reply with ok=true and set echo to exactly {nonce!r}.",
        inputs=[InputEnvelope(object_id=None, kind="nonce", content=nonce)],
        response_schema=CliProbeReply,
        temperature=0.0,
        metadata={"capability": "provider.cli.test"},
    )
    provider = router.entries[0].provider
    if hasattr(provider, "version"):
        provider.version = status.version
    started = time.perf_counter()
    try:
        response = provider.complete(probe, trace=trace_writer_for(ctx.repo))
    except StructuredOutputError as exc:
        return CliProviderTestReport(**base, ok=False, message=f"the runtime answered, but not with the requested object: {redact(exc.message)}", diagnostic="structured_output")
    except EgressDeniedError as exc:
        return CliProviderTestReport(**base, ok=False, message=exc.message, diagnostic="privacy_refused")
    except ProviderError as exc:
        return CliProviderTestReport(**base, ok=False, message=redact(exc.message), diagnostic=str(getattr(exc, "diagnostic", "provider_error")))
    latency = int((time.perf_counter() - started) * 1000)
    if response.parsed.echo != nonce or not response.parsed.ok:
        return CliProviderTestReport(**base, ok=False, latency_ms=latency, message="the runtime answered a valid object, but did not echo the nonce", diagnostic="structured_output")
    return CliProviderTestReport(**base, ok=True, latency_ms=latency, message=f"{definition.name} answered through the subscription login in {latency} ms")


# -- registration --------------------------------------------------------------


CLI_PROVIDER_CAPABILITY_HANDLERS: Mapping[str, Callable[[CapabilityContext, Any], Any]] = MappingProxyType(
    {
        "provider.cli.scan": scan_cli_runtimes,
        "provider.cli.configure": configure_cli_provider,
        "provider.cli.remove": remove_cli_provider,
        "provider.cli.test": test_cli_provider,
    }
)


def cli_provider_specs() -> list[CapabilitySpec]:
    return [
        CapabilitySpec(
            name="provider.cli.scan",
            summary="Detect the supported local CLIs: installed, version, login, bounded mode, models.",
            permission=Permission.READ,
            scientific_semantics="runs local version/login/help probes; edits nothing and sends no research content",
            request_model=ScanCliRuntimesRequest,
            response_model=CliScanReport,
            handler=scan_cli_runtimes,
        ),
        CapabilitySpec(
            name="provider.cli.configure",
            summary="Add or update one subscription-backed CLI provider entry in research.yaml.",
            permission=Permission.ADMIN,
            scientific_semantics="changes provider configuration only; writes no research object and no event",
            request_model=ConfigureCliProviderRequest,
            response_model=CliProviderConfigured,
            handler=configure_cli_provider,
            human_only=True,
        ),
        CapabilitySpec(
            name="provider.cli.remove",
            summary="Remove one subscription-backed CLI provider entry from research.yaml.",
            permission=Permission.ADMIN,
            scientific_semantics="changes provider configuration only; writes no research object and no event",
            request_model=RemoveCliProviderRequest,
            response_model=CliProviderRemoved,
            handler=remove_cli_provider,
            human_only=True,
        ),
        CapabilitySpec(
            name="provider.cli.test",
            summary="Run one minimal schema-validated request through a configured CLI provider.",
            permission=Permission.READ,
            scientific_semantics="sends one test prompt off the workstation under the privacy policy; stages nothing",
            request_model=TestCliProviderRequest,
            response_model=CliProviderTestReport,
            handler=test_cli_provider,
            human_only=True,
        ),
    ]
```

- [ ] **Step 6: Wire `providers.py`**

```python
from research_harness.capabilities.cli_providers import (
    CLI_PROVIDER_CAPABILITIES,
    CLI_PROVIDER_CAPABILITY_HANDLERS,
    cli_availability,
    cli_provider_specs,
)

PROVIDER_CAPABILITIES: tuple[str, ...] = ("provider.list", *CLI_PROVIDER_CAPABILITIES)
```

In `list_providers`, before building `models`, collect the CLI runtimes referenced by enabled entries and scan them once (cached):

```python
    cli_runtimes = {entry.runtime for entry in enabled if entry.kind == "local_cli" and entry.runtime}
    statuses = {}
    if cli_runtimes:
        from research_harness.providers.cli.detection import scan
        from research_harness.providers.cli.registry import RUNTIMES

        statuses = {s.runtime: s for s in scan([RUNTIMES[r] for r in cli_runtimes if r in RUNTIMES])}
```

and in `_model_view`, when `entry.kind == "local_cli"`, compute `available, reason = cli_availability(entry, statuses, None if disclosure is None or disclosure.allowed_by_policy else disclosure.reason)` instead of `_availability`. Pass `statuses` through. `PROVIDER_CAPABILITY_HANDLERS` becomes `MappingProxyType({"provider.list": list_providers, **CLI_PROVIDER_CAPABILITY_HANDLERS})`, and `provider_specs()` returns `[<the existing list spec>, *cli_provider_specs()]`.

- [ ] **Step 7: Pin the new capabilities in the parity tests**

`tests/e2e/test_cli_capability_parity.py` `V11_CLI_COUNTERPARTS` gains:

```python
    "provider.cli.scan": ("providers", "scan"),
    "provider.cli.configure": ("providers", "add"),
    "provider.cli.remove": ("providers", "remove"),
    "provider.cli.test": ("providers", "test"),
```

`tests/contract/protocol/test_new_capability_parity.py`: `NEW_CAPABILITIES` gains `"provider.cli.scan": {}` (a host may scan; the answer on a bare workspace is seven runtimes, all unavailable on the test PATH — the test module must `monkeypatch.setenv("PATH", "")` in its workspace fixture so the real workstation CLIs are never probed); `NEW_MUTATIONS` gains `"provider.cli.configure": {"name": "x", "runtime": "codex"}`, `"provider.cli.remove": {"name": "x"}`, `"provider.cli.test": {"name": "x"}` (a host is refused all three, identically over HTTP and MCP).

- [ ] **Step 8: Run the tests and gates**

Run: `uv run pytest tests/integration/workspace/test_update_providers.py tests/contract/capabilities tests/contract/protocol tests/e2e/test_cli_capability_parity.py -q` — the parity test `test_every_v11_capability_has_a_command_in_the_terminal` will still FAIL until Task 11 adds the commands; every other test must PASS. Then `uv run ruff check . && uv run ruff format --check . && uv run mypy src`.

- [ ] **Step 9: Commit**

```bash
git add src/research_harness/workspace/repository.py src/research_harness/capabilities/cli_providers.py src/research_harness/capabilities/providers.py tests/integration/workspace/test_update_providers.py tests/contract/capabilities/test_cli_providers.py tests/e2e/test_cli_capability_parity.py tests/contract/protocol/test_new_capability_parity.py
git commit -m "feat(capabilities): provider.cli.scan/configure/remove/test and CLI rows in provider.list"
```

---

### Task 11: `research providers scan|add|test|remove`, `doctor`, and the generated references

Spec §17, §23.10.

**Files:**
- Modify: `src/research_harness/cli/commands/provider.py`, `src/research_harness/cli/app.py` (`_provider_checks`)
- Regenerate: `docs/guide/cli-reference.md`, `docs/guide/capabilities.md`
- Test: `tests/e2e/test_cli_providers_commands.py`

**Interfaces:**
- Produces: commands `research providers scan [--rescan] [--json]`, `research providers add <runtime> --name NAME [--model M] [--priority N] [--reasoning R] [--timeout S] [--role ROLE]... [--json]`, `research providers test NAME [--json]`, `research providers remove NAME [--json]`; `doctor` lines `  <name>` → `local_cli:<runtime>/<model>, <installed|not installed>, <version>, <login>, <bounded>` (a note when not routable).

- [ ] **Step 1: Write the failing tests**

`tests/e2e/test_cli_providers_commands.py`:

```python
"""`research providers …` is the terminal's view of `provider.cli.*` (spec §17)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from research_harness.cli.app import app
from research_harness.providers.cli.detection import DEFAULT_CACHE
from research_harness.workspace.repository import WorkspaceRepository
from tests.fixtures.cli.fakes import FakeCli

STREAMS = Path(__file__).resolve().parents[1] / "fixtures" / "cli" / "streams"
HELP = "--sandbox --output-schema --json --ephemeral --skip-git-repo-check --ignore-user-config --ignore-rules"
runner = CliRunner()


def lines(name: str) -> list[str]:
    return [line for line in (STREAMS / name).read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]


@pytest.fixture
def codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeCli:
    DEFAULT_CACHE.clear()
    fake = FakeCli.install(tmp_path / "tools", "codex", version_stdout="codex-cli 0.150.1", probes=[{"args": ["login", "status"], "stdout": "Logged in using ChatGPT\n"}, {"args": ["exec", "--help"], "stdout": HELP}], run={"lines": lines("codex-success.jsonl")})
    monkeypatch.setenv("PATH", str(fake.bin_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return fake


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return WorkspaceRepository.init(tmp_path / "project", "cli").root


def run(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def test_scan_prints_every_runtime_with_its_state(workspace: Path, codex: FakeCli) -> None:
    code, out = run("providers", "scan", "--workspace", str(workspace))
    assert code == 0
    assert "codex" in out and "0.150.1" in out and "logged in" in out and "bounded" in out
    assert "claude" in out and "not installed" in out
    assert "leave the machine" in out
    code, out = run("providers", "scan", "--workspace", str(workspace), "--json")
    assert json.loads(out)["count"] == 7


def test_add_refuses_an_unavailable_runtime_and_writes_an_available_one(workspace: Path, codex: FakeCli) -> None:
    code, out = run("providers", "add", "claude", "--name", "claude-sub", "--workspace", str(workspace))
    assert code == 1 and "not installed" in out
    code, out = run("providers", "add", "codex", "--name", "codex-sub", "--model", "gpt-5.5", "--priority", "10", "--workspace", str(workspace))
    assert code == 0 and "codex-sub" in out and "research.yaml" in out
    entries = yaml.safe_load((workspace / "research.yaml").read_text(encoding="utf-8"))["providers"]
    assert entries == [{"name": "codex-sub", "kind": "local_cli", "runtime": "codex", "model": "gpt-5.5", "priority": 10, "enabled": True}]


def test_test_states_the_destination_before_it_calls(workspace: Path, codex: FakeCli) -> None:
    run("providers", "add", "codex", "--name", "codex-sub", "--workspace", str(workspace))
    code, out = run("providers", "test", "codex-sub", "--workspace", str(workspace))
    lines_out = out.splitlines()
    assert lines_out[0].startswith("egress: codex-sub sends research content to chatgpt.com")
    assert code in (0, 1)
    assert "codex" in out and ("ok" in out or "failed" in out)
    assert "supported" not in out, "no raw model response is printed"


def test_remove_takes_the_entry_out(workspace: Path, codex: FakeCli) -> None:
    run("providers", "add", "codex", "--name", "codex-sub", "--workspace", str(workspace))
    code, out = run("providers", "remove", "codex-sub", "--workspace", str(workspace))
    assert code == 0 and yaml.safe_load((workspace / "research.yaml").read_text(encoding="utf-8")).get("providers", []) == []


def test_list_and_doctor_show_the_cli_entry(workspace: Path, codex: FakeCli) -> None:
    run("providers", "add", "codex", "--name", "codex-sub", "--workspace", str(workspace))
    code, out = run("providers", "list", "--workspace", str(workspace))
    assert code == 0 and "codex-sub" in out and "external" in out
    code, out = run("doctor", "--workspace", str(workspace))
    assert "codex-sub" in out and "local_cli:codex" in out and "0.150.1" in out


def test_existing_workflow_commands_select_the_cli_entry_with_provider(workspace: Path, codex: FakeCli) -> None:
    """`--provider <name>` reaches a CLI entry through the same narrowing as an HTTP one."""
    from research_harness.cli.providers import resolve_model_client

    run("providers", "add", "codex", "--name", "codex-sub", "--workspace", str(workspace))
    client = resolve_model_client(WorkspaceRepository.open(workspace), "codex-sub", None)
    assert client.entries[0].provider.name == "local_cli:codex"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/e2e/test_cli_providers_commands.py -q`
Expected: FAIL — `No such command 'scan'`.

- [ ] **Step 3: Extend `cli/commands/provider.py`**

Add the imports and four commands (the module docstring grows a paragraph on the family):

```python
from typing import Annotated

from research_harness.capabilities.cli_providers import (
    CliProviderTestReport,
    CliScanReport,
    ConfigureCliProviderRequest,
    RemoveCliProviderRequest,
    ScanCliRuntimesRequest,
    TestCliProviderRequest,
    configure_cli_provider,
    remove_cli_provider,
    scan_cli_runtimes,
    test_cli_provider,
)
from research_harness.providers.cli.types import CliRuntimeStatus, unavailable_reason


@providers_app.command("scan")
def providers_scan(
    workspace: WorkspaceOption = None,
    rescan: Annotated[bool, typer.Option("--rescan", help="Bypass the short in-memory cache.")] = False,
    as_json: JsonOption = False,
) -> None:
    """Detect the supported local CLIs: installed, version, login, bounded mode, models."""
    with cli_errors():
        report = scan_cli_runtimes(context_for(workspace), ScanCliRuntimesRequest(rescan=rescan))
        emit(report.model_dump(mode="json"), _scan_lines(report), as_json=as_json)


@providers_app.command("add")
def providers_add(
    runtime: Annotated[str, typer.Argument(help="Runtime id: codex, claude, cursor-agent, amp, deepseek-harness, opencode, pi.")],
    name: Annotated[str, typer.Option("--name", help="The entry name `--provider` selects.")],
    workspace: WorkspaceOption = None,
    model: Annotated[str, typer.Option("--model", help="Model id from `providers scan`, or `default`.")] = "default",
    priority: Annotated[int, typer.Option("--priority", help="Lower is preferred.")] = 100,
    reasoning: Annotated[str | None, typer.Option("--reasoning", help="The runtime's own effort name.", show_default=False)] = None,
    timeout: Annotated[float | None, typer.Option("--timeout", help="Request timeout in seconds.", show_default=False)] = None,
    role: Annotated[list[str] | None, typer.Option("--role", help="Restrict to a role; repeatable.", show_default=False)] = None,
    as_json: JsonOption = False,
) -> None:
    """Add (or update) a subscription-backed CLI provider entry in research.yaml."""
    with cli_errors():
        request = ConfigureCliProviderRequest(name=name, runtime=runtime, model=model, priority=priority, reasoning=reasoning, timeout_seconds=timeout, roles=role)
        result = configure_cli_provider(context_for(workspace), request)
        verb = "added" if result.created else "updated"
        lines = [f"{verb} {result.entry.name} ({result.entry.runtime}/{result.entry.model}, priority {result.entry.priority}) in {result.file}", f"select it with --provider {result.entry.name}"]
        emit(result.model_dump(mode="json"), lines, as_json=as_json)


@providers_app.command("test")
def providers_test(
    name: Annotated[str, typer.Argument(help="A local_cli entry name from research.yaml.")],
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Run one minimal schema-validated request through a configured CLI provider."""
    with cli_errors():
        ctx = context_for(workspace)
        entry = next((item for item in ctx.repo.config.providers if item.get("name") == name), None)
        if entry is not None and not as_json:
            from research_harness.providers.cli.registry import RUNTIMES

            definition = RUNTIMES.get(str(entry.get("runtime")))
            if definition is not None:
                typer.echo(f"egress: {name} sends research content to {definition.egress_host} through {definition.name}")
        report = test_cli_provider(ctx, TestCliProviderRequest(name=name))
        emit(report.model_dump(mode="json"), _test_lines(report), as_json=as_json)
        if not report.ok:
            raise typer.Exit(code=1)


@providers_app.command("remove")
def providers_remove(
    name: Annotated[str, typer.Argument(help="A local_cli entry name from research.yaml.")],
    workspace: WorkspaceOption = None,
    as_json: JsonOption = False,
) -> None:
    """Remove a subscription-backed CLI provider entry from research.yaml."""
    with cli_errors():
        result = remove_cli_provider(context_for(workspace), RemoveCliProviderRequest(name=name))
        emit(result.model_dump(mode="json"), [f"removed {result.name} from {result.file}"], as_json=as_json)


def _scan_lines(report: CliScanReport) -> list[str]:
    lines = [report.notice, ""]
    for item in report.runtimes:
        lines.append(f"{item.runtime:<18} {_state(item)}")
        for diagnostic in item.diagnostics:
            lines.append(f"    {diagnostic}")
        if item.available:
            models = ", ".join(model.id for model in item.models[:6]) + (" …" if len(item.models) > 6 else "")
            lines.append(f"    models ({item.model_source}): {models}")
    if report.configured:
        lines.append("")
        lines.append("configured in research.yaml")
        for entry in report.configured:
            state = "available" if entry.available else f"unavailable — {entry.unavailable_reason}"
            lines.append(f"  {entry.name:<16} {entry.runtime}/{entry.model:<20} priority {entry.priority:<4} {state}")
    return lines


def _state(item: CliRuntimeStatus) -> str:
    if not item.available:
        return "not installed"
    version = item.version or "version unknown"
    auth = {"ok": "logged in", "missing": "not logged in", "unknown": "login unverified"}[item.auth_status]
    bounded = {"safe": "bounded mode ok", "unsupported": "no bounded mode", "unknown": "bounded mode unproven"}[item.bounded_mode]
    reason = unavailable_reason(item)
    tail = "" if reason is None else f" — {reason}"
    return f"{version:<14} {auth:<18} {bounded:<22} {item.compatibility}{tail}"


def _test_lines(report: CliProviderTestReport) -> list[str]:
    verdict = "ok" if report.ok else "failed"
    lines = [f"{report.name} ({report.runtime}/{report.model}, {report.version or 'version unknown'}): {verdict}", f"  {report.message}"]
    if report.diagnostic:
        lines.append(f"  diagnostic: {report.diagnostic}")
    return lines
```

`_lines` for `providers list` is unchanged; a `local_cli` row already prints `external`.

- [ ] **Step 4: Extend `doctor`'s `_provider_checks`**

Replace the per-entry loop body: when `entry.kind == "local_cli"`, run `scan([RUNTIMES[entry.runtime]])` (cached) and print `f"local_cli:{entry.runtime}/{entry.model}, {state}"` where `state` is `_state(status)` from the command module (import it lazily); `note=not status.routable`. Otherwise keep the existing key-variable line, using `MODEL_KEY_ENV_VARS.get(entry.kind)`.

- [ ] **Step 5: Regenerate the references**

Run: `uv run python docs/guide/gen_cli_reference.py && uv run python docs/guide/gen_capabilities.py`
Expected: both files change; `capabilities.md` lists the four `provider.cli.*` rows with MCP tool names `provider_cli_scan` etc.

- [ ] **Step 6: Run the tests and gates**

Run: `uv run pytest tests/e2e/test_cli_providers_commands.py tests/e2e/test_cli_capability_parity.py tests/unit/cli -q && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy src`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/research_harness/cli docs/guide/cli-reference.md docs/guide/capabilities.md tests/e2e/test_cli_providers_commands.py
git commit -m "feat(cli): research providers scan/add/test/remove, doctor lines for CLI runtimes, regenerated references"
```

---
### Task 12: Regenerated API snapshots, Web DTOs, and client methods

Spec §16 ("the OpenAPI document, generated capability metadata, Web DTOs, and fixtures are regenerated through the existing repository workflow").

**Files:**
- Regenerate: `web/openapi.json`, `web/capabilities.json`, `web/src/api/types.gen.ts`, `web/src/api/capabilities.gen.ts` (and any changed `web/src/test/fixtures/*.json` the exporter rewrites)
- Modify: `web/src/api/dto.ts`, `web/src/api/client.ts`
- Create: `web/src/test/fixtures/providers/cli-scan.json`, `cli-scan-empty.json`, `cli-configured.json`, `cli-removed.json`, `cli-test-ok.json`, `cli-test-failed.json`, `api-providers.json`
- Modify: `tests/contract/protocol/test_web_routes.py` (`WEB_RESPONSE_TYPES`)
- Test: `web/src/api/client.test.ts` (four new cases)

**Interfaces:**
- Produces (dto.ts): `CliModelView`, `CliRuntimeStatus`, `ConfiguredCliProviderView`, `CliScanReport`, `CliProviderConfigureRequest`, `CliProviderConfigured`, `CliProviderRemoved`, `CliProviderTestReport`.
- Produces (client.ts): `providerCliScan(rescan = false): Promise<CliScanReport>`, `providerCliConfigure(request: CliProviderConfigureRequest): Promise<CliProviderConfigured>`, `providerCliRemove(name: string): Promise<CliProviderRemoved>`, `providerCliTest(name: string): Promise<CliProviderTestReport>`.

- [ ] **Step 1: Regenerate the snapshots and the types**

Run: `uv run python web/scripts/export_backend_json.py && pnpm --filter research-harness-web gen:types`
Expected: `web/capabilities.json` gains the four `provider.cli.*` entries; `capabilities.gen.ts` lists them in `CapabilityName`; `pnpm --filter research-harness-web typecheck` still passes (the `conversationCall` seam keeps compiling because `ConversationReadCapability` is now a subset of `CapabilityName`).

- [ ] **Step 2: Write the failing client tests**

Append to `web/src/api/client.test.ts` (follow the file's existing `fakeDaemon`/`HarnessClient` setup):

```ts
describe('subscription-backed CLI providers', () => {
  it('scans through provider.cli.scan and forwards rescan', async () => {
    const daemon = fakeDaemon({ capabilities: { 'provider.cli.scan': { scanned_at: 't', count: 0, runtimes: [], configured: [], notice: 'n' } } });
    const client = new HarnessClient({ baseUrl: 'http://daemon.test', token: 't', fetchImpl: daemon.fetch });
    const report = await client.providerCliScan(true);
    expect(report.count).toBe(0);
    expect(daemon.capabilityCalls()).toEqual([{ name: 'provider.cli.scan', request: { rescan: true } }]);
  });

  it('configures, tests, and removes by name', async () => {
    const daemon = fakeDaemon({
      capabilities: {
        'provider.cli.configure': { entry: { name: 'codex-sub' }, created: true, file: 'research.yaml' },
        'provider.cli.test': { name: 'codex-sub', ok: true, message: 'ok' },
        'provider.cli.remove': { name: 'codex-sub', file: 'research.yaml' },
      },
    });
    const client = new HarnessClient({ baseUrl: 'http://daemon.test', token: 't', fetchImpl: daemon.fetch });
    await client.providerCliConfigure({ name: 'codex-sub', runtime: 'codex', model: 'gpt-5.5', priority: 10 });
    await client.providerCliTest('codex-sub');
    await client.providerCliRemove('codex-sub');
    expect(daemon.capabilityCalls().map((call) => call.name)).toEqual(['provider.cli.configure', 'provider.cli.test', 'provider.cli.remove']);
    expect(daemon.capabilityCalls()[0].request).toEqual({ name: 'codex-sub', runtime: 'codex', model: 'gpt-5.5', priority: 10 });
    expect(daemon.capabilityCalls()[2].request).toEqual({ name: 'codex-sub' });
  });

  it('surfaces a refusal as a CapabilityError', async () => {
    const daemon = fakeDaemon({ capabilities: { 'provider.cli.configure': { capability: 'provider.cli.configure', ok: false, error: { code: 'permission_denied', message: 'human only' } } } });
    const client = new HarnessClient({ baseUrl: 'http://daemon.test', token: null, fetchImpl: daemon.fetch });
    await expect(client.providerCliConfigure({ name: 'x', runtime: 'codex' })).rejects.toThrow('human only');
  });
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `pnpm --filter research-harness-web test -- src/api/client.test.ts`
Expected: FAIL — `providerCliScan is not a function`.

- [ ] **Step 4: Declare the DTOs**

Append to `web/src/api/dto.ts` (one field per line — `tests/contract/protocol/test_web_routes.py` parses these interfaces):

```ts
// ---------------------------------------------------------------------------
// subscription-backed CLI providers (provider.cli.*)
// ---------------------------------------------------------------------------
//
// Hand-declared like the sections above: `provider.cli.*` answers through
// `POST /capabilities/<name>`. They mirror `capabilities/cli_providers.py` and
// `providers/cli/types.py` field for field; the contract test pins every field name to
// the schema the daemon publishes.

export type CliAuthStatus = 'ok' | 'missing' | 'unknown';
export type CliBoundedMode = 'safe' | 'unsupported' | 'unknown';
export type CliCompatibility = 'verified' | 'warning' | 'blocked' | 'unknown';
export type CliEgressKind = 'external' | 'unknown_external';

export interface CliModelView {
  id: string;
  label: string;
  reasoning?: string[];
  context_tokens?: number | null;
}

/** One runtime as `provider.cli.scan` found it. Never carries a secret. */
export interface CliRuntimeStatus {
  runtime: string;
  name: string;
  available: boolean;
  executable: string | null;
  version: string | null;
  auth_status: CliAuthStatus;
  auth_guidance: string;
  bounded_mode: CliBoundedMode;
  compatibility: CliCompatibility;
  models: CliModelView[];
  model_source: 'live' | 'fallback';
  reasoning_choices: string[];
  egress_kind: CliEgressKind;
  egress_host: string;
  diagnostics: string[];
  scanned_at: string;
}

export interface ConfiguredCliProviderView {
  name: string;
  runtime: string;
  model: string;
  priority: number;
  enabled: boolean;
  reasoning?: string | null;
  timeout_seconds?: number | null;
  roles?: string[] | null;
  available: boolean;
  unavailable_reason?: string | null;
}

export interface CliScanReport {
  scanned_at: string;
  count: number;
  runtimes: CliRuntimeStatus[];
  configured: ConfiguredCliProviderView[];
  notice: string;
}

/** `provider.cli.configure`'s request, exactly as the settings screen posts it. */
export interface CliProviderConfigureRequest {
  name: string;
  runtime: string;
  model?: string;
  priority?: number;
  reasoning?: string | null;
  timeout_seconds?: number | null;
  roles?: string[] | null;
  enabled?: boolean;
}

export interface CliProviderConfigured {
  entry: ConfiguredCliProviderView;
  created: boolean;
  file: string;
}

export interface CliProviderRemoved {
  name: string;
  file: string;
}

export interface CliProviderTestReport {
  name: string;
  runtime: string;
  model: string;
  version: string | null;
  egress_host: string;
  egress_kind: CliEgressKind;
  ok: boolean;
  latency_ms?: number | null;
  message: string;
  diagnostic?: string | null;
}
```

- [ ] **Step 5: Add the client methods**

In `web/src/api/client.ts`, import the four response types and the request type, and add after `providers()`:

```ts
  // -- subscription-backed CLI providers (provider.cli.*) ----------------------

  /** Detect the supported local CLIs. A read; `rescan` bypasses the daemon's short cache. */
  providerCliScan(rescan = false): Promise<CliScanReport> {
    return this.call<CliScanReport>('provider.cli.scan', { rescan });
  }

  /** Add or update one `local_cli` entry in research.yaml. Researcher-only. */
  providerCliConfigure(request: CliProviderConfigureRequest): Promise<CliProviderConfigured> {
    return this.call<CliProviderConfigured>('provider.cli.configure', request as unknown as Json);
  }

  /** Remove one `local_cli` entry. Researcher-only. */
  providerCliRemove(name: string): Promise<CliProviderRemoved> {
    return this.call<CliProviderRemoved>('provider.cli.remove', { name });
  }

  /** One minimal validated request through a configured entry; external egress, researcher-only. */
  providerCliTest(name: string): Promise<CliProviderTestReport> {
    return this.call<CliProviderTestReport>('provider.cli.test', { name });
  }
```

- [ ] **Step 6: Pin the DTOs in the contract test and write the fixtures**

`tests/contract/protocol/test_web_routes.py` `WEB_RESPONSE_TYPES` gains:

```python
    # subscription-backed CLI providers
    "CliModelView": "provider.cli.scan",
    "CliRuntimeStatus": "provider.cli.scan",
    "ConfiguredCliProviderView": "provider.cli.scan",
    "CliScanReport": "provider.cli.scan",
    "CliProviderConfigured": "provider.cli.configure",
    "CliProviderRemoved": "provider.cli.remove",
    "CliProviderTestReport": "provider.cli.test",
```

Fixtures (hand-authored to the Pydantic schemas, like `fixtures/conversation/providers.json`):

`providers/cli-scan.json` — `scanned_at: "2026-09-04T00:00:00Z"`, `count: 7`, `notice` = the `EXTERNAL_EGRESS_NOTICE` sentence, `runtimes`: `codex` (available, `0.150.1`, `ok`, `safe`, `verified`, models `default`/`gpt-5.5` (reasoning `low,medium,high,xhigh`, 272000)/`gpt-5.4-mini`, `live`, reasoning_choices `low,medium,high,xhigh`, `external`, `chatgpt.com`, no diagnostics), `claude` (available, `2.1.259`, `missing` with guidance ``run `claude auth login` ``, `safe`, `verified`, fallback models `default`/`sonnet`/`opus`/`haiku`, `api.anthropic.com`), `cursor-agent` (available, `1.4.0`, `ok`, `unsupported`, `warning`, diagnostics `["cursor-agent: headless Cursor Agent runs only with --force (approval bypass); no deny-tools flag is documented"]`, `unknown_external`, `unknown.external`), `amp`/`deepseek-harness`/`opencode`/`pi` not available (`executable: null`, `version: null`, `unknown`/`unknown`/`unknown`, models `[default]`, `fallback`, diagnostics `["<id> is not installed: no '<exe>' on PATH"]`); `configured`: one entry `codex-sub` (`codex`, `gpt-5.5`, priority 10, enabled, available). `cli-scan-empty.json` — all seven unavailable, `configured: []`. `cli-configured.json` — `{entry: <codex-sub view>, created: true, file: "research.yaml"}`. `cli-removed.json` — `{name: "codex-sub", file: "research.yaml"}`. `cli-test-ok.json` — `{name, runtime: "codex", model: "gpt-5.5", version: "0.150.1", egress_host: "chatgpt.com", egress_kind: "external", ok: true, latency_ms: 2140, message: "Codex CLI answered through the subscription login in 2140 ms", diagnostic: null}`. `cli-test-failed.json` — same identity, `ok: false`, `latency_ms: null`, `message: "codex/gpt-5.5 (0.150.1): not logged in; run `codex login`"`, `diagnostic: "login_missing"`. `api-providers.json` — a `ProviderCatalog` with two rows: `fast` (`openai`, external, available) and `codex-sub` (`local_cli`, external, available, default).

- [ ] **Step 7: Run the tests and gates**

Run: `pnpm --filter research-harness-web test && pnpm --filter research-harness-web typecheck && pnpm --filter research-harness-web lint && uv run pytest tests/contract/protocol/test_web_routes.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add web/openapi.json web/capabilities.json web/src/api web/src/test/fixtures tests/contract/protocol/test_web_routes.py
git commit -m "feat(web): regenerated daemon snapshots and the provider.cli.* client with pinned DTOs"
```

---

### Task 13: The Web *Models & providers* settings section

Spec §18. The UI renders server decisions; it never runs a binary and never decides availability.

**Files:**
- Modify: `web/src/app/SettingsDialog.tsx`
- Create: `web/src/app/settings/ProvidersSettings.tsx`, `LocalCliTab.tsx`, `ApiProvidersTab.tsx`, `RuntimeCard.tsx`, `useCliRuntimes.ts`, `mappers.ts`, `settings.css`
- Test: `web/src/app/settings/settings.test.tsx`, `web/src/app/settings/mappers.test.ts`

**Interfaces:**
- Consumes: `HarnessClient` methods from Task 12; `useSession()` from `web/src/app/session.tsx` (`client`, `canMutate` — if `client` is not on the `Session` interface, add it there, one line, rather than threading it through props); design primitives `Tabs, TabList, Tab, TabPanel, Button, Badge, Select, Input, Card, ErrorNotice, useToast`; `Loading, ErrorBox, Empty` from `web/src/components/Feedback.tsx`.
- Produces: `useCliRuntimes(client, { enabled }) -> { report, loading, error, rescan(), configure(request), remove(name), test(name), busy: string | null, lastTest: Record<string, CliProviderTestReport> }`; `mappers.ts`: `runtimeBadges(status) -> { login: Badge, bounded: Badge, compatibility: Badge }` where `Badge = { tone: BadgeTone; label: string }`, `groupRuntimes(report) -> { installed: CliRuntimeStatus[]; unavailable: CliRuntimeStatus[] }`, `defaultEntryName(runtime) -> string` (`<runtime>-subscription`), `configuredFor(report, runtime) -> ConfiguredCliProviderView | null`.

- [ ] **Step 1: Write the failing mapper tests**

`web/src/app/settings/mappers.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import scan from '../../test/fixtures/providers/cli-scan.json';
import type { CliScanReport } from '../../api/dto';
import { configuredFor, defaultEntryName, groupRuntimes, runtimeBadges } from './mappers';

const report = scan as CliScanReport;

describe('runtime badges', () => {
  it('names login, bounded mode, and compatibility with a tone and a word', () => {
    const codex = runtimeBadges(report.runtimes[0]);
    expect(codex).toEqual({
      login: { tone: 'success', label: 'Logged in' },
      bounded: { tone: 'success', label: 'Bounded mode' },
      compatibility: { tone: 'success', label: 'Verified 0.150.1' },
    });
    const claude = runtimeBadges(report.runtimes[1]);
    expect(claude.login).toEqual({ tone: 'error', label: 'Not logged in' });
    const cursor = runtimeBadges(report.runtimes[2]);
    expect(cursor.bounded).toEqual({ tone: 'error', label: 'No bounded mode' });
    expect(cursor.compatibility).toEqual({ tone: 'warning', label: 'Untested 1.4.0' });
    expect(runtimeBadges(report.runtimes[3]).login).toEqual({ tone: 'neutral', label: 'Login unverified' });
  });
});

describe('grouping', () => {
  it('splits installed from unavailable and keeps registry order', () => {
    const groups = groupRuntimes(report);
    expect(groups.installed.map((item) => item.runtime)).toEqual(['codex', 'claude', 'cursor-agent']);
    expect(groups.unavailable.map((item) => item.runtime)).toEqual(['amp', 'deepseek-harness', 'opencode', 'pi']);
  });

  it('finds the configured entry for a runtime', () => {
    expect(configuredFor(report, 'codex')?.name).toBe('codex-sub');
    expect(configuredFor(report, 'claude')).toBeNull();
    expect(defaultEntryName('deepseek-harness')).toBe('deepseek-harness-subscription');
  });
});
```

- [ ] **Step 2: Write the failing view tests**

`web/src/app/settings/settings.test.tsx`:

```tsx
/**
 * The Models & providers settings: what the daemon says, rendered, and nothing decided here.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations, fakeDaemon, renderView } from '../../test/harness';
import scan from '../../test/fixtures/providers/cli-scan.json';
import scanEmpty from '../../test/fixtures/providers/cli-scan-empty.json';
import configured from '../../test/fixtures/providers/cli-configured.json';
import removed from '../../test/fixtures/providers/cli-removed.json';
import testOk from '../../test/fixtures/providers/cli-test-ok.json';
import testFailed from '../../test/fixtures/providers/cli-test-failed.json';
import apiProviders from '../../test/fixtures/providers/api-providers.json';
import { SettingsDialog } from '../SettingsDialog';

function answers(extra: Record<string, unknown> = {}) {
  return {
    'provider.cli.scan': scan,
    'provider.list': apiProviders,
    'provider.cli.configure': configured,
    'provider.cli.remove': removed,
    'provider.cli.test': testOk,
    ...extra,
  };
}

function open(daemon: ReturnType<typeof fakeDaemon>, token: string | null = 'local-token') {
  return renderView(<SettingsDialog open onOpenChange={() => undefined} />, { daemon, token });
}

async function providersTab() {
  await userEvent.click(screen.getByRole('tab', { name: 'Models & providers' }));
  return screen.getByRole('tabpanel', { name: 'Models & providers' });
}

describe('the two tabs', () => {
  it('renders Local CLIs and API providers as separate tabs', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    const panel = await providersTab();
    expect(within(panel).getByRole('tab', { name: 'Local CLIs' })).toHaveAttribute('aria-selected', 'true');
    expect(within(panel).getByRole('tab', { name: 'API providers' })).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole('tab', { name: 'API providers' }));
    expect(await screen.findByText('fast/gpt-4o-mini')).toBeInTheDocument();
    expect(screen.getByText(/API keys are read from environment variables/)).toBeInTheDocument();
  });

  it('moves between tabs with the arrow keys', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    const panel = await providersTab();
    within(panel).getByRole('tab', { name: 'Local CLIs' }).focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(within(panel).getByRole('tab', { name: 'API providers' })).toHaveFocus();
  });
});

describe('the Local CLIs tab', () => {
  it('shows a loading state, then the installed and unavailable groups', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    await providersTab();
    expect(screen.getByText(/Scanning local CLIs/)).toBeInTheDocument();
    const installed = await screen.findByRole('region', { name: 'Installed' });
    expect(within(installed).getAllByRole('heading', { level: 4 }).map((h) => h.textContent)).toEqual(['Codex CLI', 'Claude Code', 'Cursor Agent']);
    const unavailable = screen.getByRole('region', { name: 'Not installed' });
    expect(within(unavailable).getAllByRole('heading', { level: 4 })).toHaveLength(4);
    expect(screen.getByText(scan.notice)).toBeInTheDocument();
    await expectNoAxeViolations();
  });

  it('renders the daemon states: logged out, unsafe, version warning, with its own words', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    await providersTab();
    const claude = await screen.findByRole('article', { name: 'Claude Code' });
    expect(within(claude).getByText('Not logged in')).toBeInTheDocument();
    expect(within(claude).getByText('run `claude auth login`')).toBeInTheDocument();
    const cursor = screen.getByRole('article', { name: 'Cursor Agent' });
    expect(within(cursor).getByText('No bounded mode')).toBeInTheDocument();
    expect(within(cursor).getByText('Untested 1.4.0')).toBeInTheDocument();
    expect(within(cursor).getByText(/no deny-tools flag is documented/)).toBeInTheDocument();
    expect(within(cursor).getByRole('button', { name: 'Add provider' })).toBeDisabled();
  });

  it('says so when nothing is installed and offers a rescan', async () => {
    const daemon = fakeDaemon({ capabilities: answers({ 'provider.cli.scan': scanEmpty }) });
    open(daemon);
    await providersTab();
    expect(await screen.findByText(/No supported CLI is installed/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Rescan' }));
    await waitFor(() => expect(daemon.capabilityCalls().filter((c) => c.name === 'provider.cli.scan')).toHaveLength(2));
    expect(daemon.capabilityCalls().at(-1)?.request).toEqual({ rescan: true });
  });

  it('reports a failed scan and keeps the rescan control', async () => {
    const daemon = fakeDaemon({ capabilities: answers({ 'provider.cli.scan': { capability: 'provider.cli.scan', ok: false, error: { code: 'internal_error', message: 'scan blew up' } } }) });
    open(daemon);
    await providersTab();
    expect(await screen.findByText(/scan blew up/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Rescan' })).toBeEnabled();
  });

  it('adds a provider with the chosen model and reasoning, after the egress warning', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    await providersTab();
    const claude = await screen.findByRole('article', { name: 'Claude Code' });
    expect(within(claude).getByRole('button', { name: 'Add provider' })).toBeDisabled();
    const codex = screen.getByRole('article', { name: 'Codex CLI' });
    expect(within(codex).getByText(/leave the machine/)).toBeInTheDocument();
    await userEvent.selectOptions(within(codex).getByLabelText('Model'), 'gpt-5.5');
    await userEvent.selectOptions(within(codex).getByLabelText('Reasoning'), 'high');
    await userEvent.clear(within(codex).getByLabelText('Entry name'));
    await userEvent.type(within(codex).getByLabelText('Entry name'), 'codex-work');
    await userEvent.click(within(codex).getByRole('button', { name: 'Update provider' }));
    await waitFor(() => expect(daemon.capabilityCalls().some((c) => c.name === 'provider.cli.configure')).toBe(true));
    expect(daemon.capabilityCalls().find((c) => c.name === 'provider.cli.configure')?.request).toEqual({ name: 'codex-work', runtime: 'codex', model: 'gpt-5.5', priority: 10, reasoning: 'high' });
  });

  it('tests a configured entry and renders the daemon report, success and failure', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    await providersTab();
    const codex = await screen.findByRole('article', { name: 'Codex CLI' });
    await userEvent.click(within(codex).getByRole('button', { name: 'Test' }));
    expect(await within(codex).findByRole('status')).toHaveTextContent('answered through the subscription login in 2140 ms');

    const failing = fakeDaemon({ capabilities: answers({ 'provider.cli.test': testFailed }) });
    open(failing);
    await providersTab();
    const again = (await screen.findAllByRole('article', { name: 'Codex CLI' })).at(-1)!;
    await userEvent.click(within(again).getByRole('button', { name: 'Test' }));
    expect(await within(again).findByText(/not logged in; run `codex login`/)).toBeInTheDocument();
    expect(within(again).getByText('login_missing')).toBeInTheDocument();
  });

  it('removes a configured entry', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon);
    await providersTab();
    const codex = await screen.findByRole('article', { name: 'Codex CLI' });
    expect(within(codex).getByText(/configured as codex-sub/)).toBeInTheDocument();
    await userEvent.click(within(codex).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(daemon.capabilityCalls().some((c) => c.name === 'provider.cli.remove')).toBe(true));
    expect(daemon.capabilityCalls().find((c) => c.name === 'provider.cli.remove')?.request).toEqual({ name: 'codex-sub' });
  });

  it('offers no mutation to a window that may only read', async () => {
    const daemon = fakeDaemon({ capabilities: answers() });
    open(daemon, null);
    await providersTab();
    const codex = await screen.findByRole('article', { name: 'Codex CLI' });
    for (const name of ['Update provider', 'Test', 'Remove']) {
      expect(within(codex).getByRole('button', { name })).toBeDisabled();
    }
    expect(within(codex).getByText(/agent host/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `pnpm --filter research-harness-web test -- src/app/settings`
Expected: FAIL — modules missing.

- [ ] **Step 4: Write `mappers.ts`**

```ts
/**
 * Pure view mapping for the Models & providers settings. Words and tones only; the
 * daemon decided every state (PRODUCT §5 P10).
 */
import type { BadgeTone } from '@research-harness/design';
import type { CliRuntimeStatus, CliScanReport, ConfiguredCliProviderView } from '../../api/dto';

export interface BadgeView {
  tone: BadgeTone;
  label: string;
}

export interface RuntimeBadges {
  login: BadgeView;
  bounded: BadgeView;
  compatibility: BadgeView;
}

export function runtimeBadges(status: CliRuntimeStatus): RuntimeBadges {
  const version = status.version ?? 'unknown version';
  const login: BadgeView =
    status.auth_status === 'ok'
      ? { tone: 'success', label: 'Logged in' }
      : status.auth_status === 'missing'
        ? { tone: 'error', label: 'Not logged in' }
        : { tone: 'neutral', label: 'Login unverified' };
  const bounded: BadgeView =
    status.bounded_mode === 'safe'
      ? { tone: 'success', label: 'Bounded mode' }
      : status.bounded_mode === 'unsupported'
        ? { tone: 'error', label: 'No bounded mode' }
        : { tone: 'warning', label: 'Bounded mode unproven' };
  const compatibility: BadgeView =
    status.compatibility === 'verified'
      ? { tone: 'success', label: `Verified ${version}` }
      : status.compatibility === 'blocked'
        ? { tone: 'error', label: `Incompatible ${version}` }
        : status.compatibility === 'warning'
          ? { tone: 'warning', label: `Untested ${version}` }
          : { tone: 'neutral', label: 'Version unknown' };
  return { login, bounded, compatibility };
}

export function groupRuntimes(report: CliScanReport): { installed: CliRuntimeStatus[]; unavailable: CliRuntimeStatus[] } {
  return {
    installed: report.runtimes.filter((item) => item.available),
    unavailable: report.runtimes.filter((item) => !item.available),
  };
}

export function configuredFor(report: CliScanReport, runtime: string): ConfiguredCliProviderView | null {
  return report.configured.find((item) => item.runtime === runtime) ?? null;
}

export function defaultEntryName(runtime: string): string {
  return `${runtime}-subscription`;
}

/** Whether the daemon would accept an Add: every gate it reports must be green. */
export function routable(status: CliRuntimeStatus): boolean {
  return status.available && status.auth_status !== 'missing' && status.bounded_mode === 'safe' && status.compatibility !== 'blocked';
}
```

- [ ] **Step 5: Write `useCliRuntimes.ts`**

```ts
/**
 * The scan, and the three researcher acts on it. Every answer is the daemon's; the hook
 * only sequences calls and remembers the last test report per entry.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { HarnessClient } from '../../api/client';
import type { CliProviderConfigureRequest, CliProviderTestReport, CliScanReport } from '../../api/dto';

export interface CliRuntimesApi {
  report: CliScanReport | null;
  loading: boolean;
  error: string | null;
  /** The entry name an action is running for, or the word `scan`; disables the controls. */
  busy: string | null;
  lastTest: Record<string, CliProviderTestReport>;
  rescan: () => Promise<void>;
  configure: (request: CliProviderConfigureRequest) => Promise<void>;
  remove: (name: string) => Promise<void>;
  test: (name: string) => Promise<void>;
}

function message(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

export function useCliRuntimes(client: HarnessClient, options: { enabled?: boolean } = {}): CliRuntimesApi {
  const enabled = options.enabled ?? true;
  const [report, setReport] = useState<CliScanReport | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [lastTest, setLastTest] = useState<Record<string, CliProviderTestReport>>({});

  const load = useCallback(
    async (rescan: boolean) => {
      setLoading(true);
      try {
        setReport(await client.providerCliScan(rescan));
        setError(null);
      } catch (cause) {
        setError(message(cause));
      } finally {
        setLoading(false);
      }
    },
    [client],
  );

  useEffect(() => {
    if (enabled) void load(false);
  }, [enabled, load]);

  const run = useCallback(
    async (key: string, action: () => Promise<unknown>) => {
      setBusy(key);
      try {
        await action();
        await load(true);
      } finally {
        setBusy(null);
      }
    },
    [load],
  );

  return useMemo(
    () => ({
      report,
      loading,
      error,
      busy,
      lastTest,
      rescan: () => run('scan', async () => undefined),
      configure: (request) => run(request.name, () => client.providerCliConfigure(request)),
      remove: (name) => run(name, () => client.providerCliRemove(name)),
      test: async (name) => {
        setBusy(name);
        try {
          const result = await client.providerCliTest(name);
          setLastTest((current) => ({ ...current, [name]: result }));
        } finally {
          setBusy(null);
        }
      },
    }),
    [busy, client, error, lastTest, loading, report, run],
  );
}
```

- [ ] **Step 6: Write the components**

`RuntimeCard.tsx`:

```tsx
/**
 * One runtime: what the daemon found, and the researcher's controls over it.
 *
 * Every word of state comes from the report — the badges, the unavailable reason, the
 * diagnostics, the egress sentence. The card decides nothing; it disables the Add control
 * when the daemon's gates are not all green and repeats the daemon's reason beside it.
 */
import { useState } from 'react';
import { Badge, Button, Input, Select, useToast } from '@research-harness/design';
import type { CliProviderTestReport, CliRuntimeStatus, ConfiguredCliProviderView } from '../../api/dto';
import { configuredFor, defaultEntryName, routable, runtimeBadges } from './mappers';
import type { CliScanReport } from '../../api/dto';

export interface RuntimeCardProps {
  status: CliRuntimeStatus;
  report: CliScanReport;
  canMutate: boolean;
  busy: string | null;
  lastTest: CliProviderTestReport | undefined;
  onConfigure: (request: { name: string; runtime: string; model: string; priority: number; reasoning?: string | null }) => Promise<void>;
  onRemove: (name: string) => Promise<void>;
  onTest: (name: string) => Promise<void>;
}

function unavailableReason(status: CliRuntimeStatus): string | null {
  const label = status.version ? `${status.runtime} ${status.version}` : status.runtime;
  if (!status.available) return `${status.runtime} is not installed on this workstation`;
  if (status.auth_status === 'missing') return `${status.runtime} is not logged in: ${status.auth_guidance}`;
  if (status.bounded_mode === 'unsupported') return `${label} has no tested bounded (no-tools, read-only) mode`;
  if (status.bounded_mode === 'unknown') return `${label} could not prove a bounded (no-tools, read-only) mode`;
  if (status.compatibility === 'blocked') return `${label} is a known-incompatible version`;
  return null;
}

export function RuntimeCard({ status, report, canMutate, busy, lastTest, onConfigure, onRemove, onTest }: RuntimeCardProps) {
  const toast = useToast();
  const configured: ConfiguredCliProviderView | null = configuredFor(report, status.runtime);
  const badges = runtimeBadges(status);
  const [name, setName] = useState(configured?.name ?? defaultEntryName(status.runtime));
  const [model, setModel] = useState(configured?.model ?? 'default');
  const [reasoning, setReasoning] = useState<string>(configured?.reasoning ?? '');
  const [priority, setPriority] = useState(configured?.priority ?? 10);
  const reason = unavailableReason(status);
  const reasoningChoices = status.models.find((item) => item.id === model)?.reasoning?.length ? status.models.find((item) => item.id === model)!.reasoning! : status.reasoning_choices;
  const working = busy !== null;
  const headingId = `rh-runtime-${status.runtime}`;

  async function submit() {
    try {
      await onConfigure({ name, runtime: status.runtime, model, priority, ...(reasoning ? { reasoning } : {}) });
      toast.show({ tone: 'success', title: `${name} written to research.yaml` });
    } catch (cause) {
      toast.show({ tone: 'error', title: cause instanceof Error ? cause.message : String(cause) });
    }
  }

  return (
    <article className="rh-runtime-card" aria-labelledby={headingId}>
      <header className="rh-runtime-card__header">
        <h4 id={headingId}>{status.name}</h4>
        <span className="rh-runtime-card__version">{status.version ?? (status.available ? 'version unknown' : 'not installed')}</span>
      </header>
      {status.available ? (
        <div className="rh-runtime-card__badges">
          <Badge tone={badges.login.tone}>{badges.login.label}</Badge>
          <Badge tone={badges.bounded.tone}>{badges.bounded.label}</Badge>
          <Badge tone={badges.compatibility.tone}>{badges.compatibility.label}</Badge>
        </div>
      ) : null}
      {status.auth_status === 'missing' ? <p className="rh-runtime-card__guidance">{status.auth_guidance}</p> : null}
      {status.diagnostics.length > 0 ? (
        <ul className="rh-runtime-card__diagnostics">
          {status.diagnostics.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      <p className="rh-runtime-card__egress">
        The process runs here, but research content and IDs leave the machine for {status.egress_kind === 'external' ? status.egress_host : 'a destination the CLI does not disclose'}.
      </p>
      {configured ? (
        <p className="rh-runtime-card__configured">
          configured as <strong>{configured.name}</strong> ({configured.model}, priority {configured.priority}){' '}
          {configured.available ? '— available' : `— unavailable: ${configured.unavailable_reason}`}
        </p>
      ) : null}
      {status.available ? (
        <div className="rh-runtime-card__form">
          <Select label="Model" value={model} onChange={(event) => setModel(event.target.value)} disabled={working}>
            {status.models.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </Select>
          <Select label="Reasoning" value={reasoning} onChange={(event) => setReasoning(event.target.value)} disabled={working || reasoningChoices.length === 0}>
            <option value="">Runtime default</option>
            {reasoningChoices.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </Select>
          <Input label="Entry name" value={name} onChange={(event) => setName(event.target.value)} disabled={working} />
          <Input label="Priority" type="number" value={priority} onChange={(event) => setPriority(Number(event.target.value))} disabled={working} />
        </div>
      ) : null}
      <div className="rh-runtime-card__actions">
        <Button variant="primary" size="sm" disabled={!canMutate || working || reason !== null} onClick={() => void submit()}>
          {configured ? 'Update provider' : 'Add provider'}
        </Button>
        {configured ? (
          <>
            <Button variant="secondary" size="sm" disabled={!canMutate || working} onClick={() => void onTest(configured.name)}>
              Test
            </Button>
            <Button variant="danger" size="sm" disabled={!canMutate || working} onClick={() => void onRemove(configured.name)}>
              Remove
            </Button>
          </>
        ) : null}
        {reason !== null && status.available ? <span className="rh-runtime-card__reason">{reason}</span> : null}
        {!canMutate ? <span className="rh-runtime-card__reason">An agent host may read this screen; adding, testing, and removing are the researcher's.</span> : null}
      </div>
      {lastTest ? (
        <p role="status" className={lastTest.ok ? 'rh-runtime-card__test rh-runtime-card__test--ok' : 'rh-runtime-card__test rh-runtime-card__test--failed'}>
          {lastTest.message}
          {lastTest.diagnostic ? <code className="rh-runtime-card__diagnostic">{lastTest.diagnostic}</code> : null}
        </p>
      ) : null}
    </article>
  );
}
```

(Check `useToast`'s API in `design/src/primitives/Toast` — if `show` takes `{ tone, title }` under a different name, use that name; the toast is a courtesy, the `role="status"` line is what the tests read.)

`LocalCliTab.tsx`:

```tsx
import { Button } from '@research-harness/design';
import { Empty, ErrorBox, Loading } from '../../components/Feedback';
import type { HarnessClient } from '../../api/client';
import { groupRuntimes } from './mappers';
import { RuntimeCard } from './RuntimeCard';
import { useCliRuntimes } from './useCliRuntimes';

export function LocalCliTab({ client, canMutate }: { client: HarnessClient; canMutate: boolean }) {
  const cli = useCliRuntimes(client);
  const groups = cli.report ? groupRuntimes(cli.report) : null;
  return (
    <div className="rh-settings-providers">
      <div className="rh-settings-providers__toolbar">
        <p className="rh-settings-providers__notice">{cli.report?.notice ?? 'A local CLI starts on this workstation, but the model it talks to is the vendor’s: research content leaves the machine when a CLI provider is used.'}</p>
        <Button variant="secondary" size="sm" onClick={() => void cli.rescan()} disabled={cli.busy !== null}>
          Rescan
        </Button>
      </div>
      {cli.loading && !cli.report ? <Loading what="Scanning local CLIs" /> : null}
      {cli.error ? <ErrorBox error={cli.error} retry={() => void cli.rescan()} /> : null}
      {groups && groups.installed.length === 0 && !cli.error ? (
        <Empty>No supported CLI is installed on this workstation. Install Codex CLI, Claude Code, Cursor Agent, Amp, DeepSeek Harness, OpenCode, or Pi and rescan.</Empty>
      ) : null}
      {groups && groups.installed.length > 0 ? (
        <section aria-label="Installed" className="rh-settings-providers__group">
          <h3>Installed</h3>
          {groups.installed.map((status) => (
            <RuntimeCard key={status.runtime} status={status} report={cli.report!} canMutate={canMutate} busy={cli.busy} lastTest={cli.lastTest[cli.report!.configured.find((c) => c.runtime === status.runtime)?.name ?? '']} onConfigure={cli.configure} onRemove={cli.remove} onTest={cli.test} />
          ))}
        </section>
      ) : null}
      {groups && groups.unavailable.length > 0 ? (
        <section aria-label="Not installed" className="rh-settings-providers__group">
          <h3>Not installed</h3>
          {groups.unavailable.map((status) => (
            <RuntimeCard key={status.runtime} status={status} report={cli.report!} canMutate={canMutate} busy={cli.busy} lastTest={undefined} onConfigure={cli.configure} onRemove={cli.remove} onTest={cli.test} />
          ))}
        </section>
      ) : null}
    </div>
  );
}
```

`ApiProvidersTab.tsx`:

```tsx
import { Empty, ErrorBox, Loading } from '../../components/Feedback';
import type { HarnessClient } from '../../api/client';
import { useAsync } from '../useAsync';

export function ApiProvidersTab({ client }: { client: HarnessClient }) {
  const catalog = useAsync(() => client.providers(), [client]);
  const rows = (catalog.data?.models ?? []).filter((item) => item.provider !== 'local_cli');
  return (
    <div className="rh-settings-providers">
      <p className="rh-settings-providers__notice">
        API providers are configured in <code>research.yaml</code> with <code>api_key_env</code>. API keys are read from environment variables on the workstation and never enter the browser.
      </p>
      {catalog.loading ? <Loading what="API providers" /> : null}
      {catalog.error ? <ErrorBox error={catalog.error} retry={catalog.reload} /> : null}
      {catalog.data && rows.length === 0 ? <Empty>No API provider is configured.</Empty> : null}
      {rows.length > 0 ? (
        <ul className="rh-settings-providers__list">
          {rows.map((item) => (
            <li key={item.id}>
              <strong>{item.label}</strong> · {item.provider} · {item.egress_class} ·{' '}
              {item.available ? 'available' : `unavailable — ${item.unavailable_reason}`}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
```

`ProvidersSettings.tsx`:

```tsx
import { Tab, TabList, TabPanel, Tabs } from '@research-harness/design';
import { useSession } from '../session';
import { ApiProvidersTab } from './ApiProvidersTab';
import { LocalCliTab } from './LocalCliTab';
import './settings.css';

export function ProvidersSettings() {
  const { client, canMutate } = useSession();
  return (
    <Tabs defaultValue="local">
      <TabList aria-label="Provider kinds">
        <Tab value="local">Local CLIs</Tab>
        <Tab value="api">API providers</Tab>
      </TabList>
      <TabPanel value="local">
        <LocalCliTab client={client} canMutate={canMutate} />
      </TabPanel>
      <TabPanel value="api">
        <ApiProvidersTab client={client} />
      </TabPanel>
    </Tabs>
  );
}
```

`SettingsDialog.tsx` becomes a `size="lg"` dialog with an outer `Tabs defaultValue="appearance"`: `Tab value="appearance"` → the existing two selects; `Tab value="providers"` labelled **Models & providers** → `<ProvidersSettings />`. Give the outer `TabList` `aria-label="Settings sections"`. The `TabPanel`s are labelled by their tabs through the primitive (`aria-labelledby`), which is what `getByRole('tabpanel', { name: 'Models & providers' })` reads.

`settings.css`: the card grid (`.rh-runtime-card` bordered with `var(--rh-color-border)`, padding `var(--rh-space-3)`, `.rh-runtime-card__badges` flex gap, `.rh-runtime-card__form` a two-column grid collapsing at 640 px, `.rh-runtime-card__test--failed` uses `var(--rh-color-status-error-text)` and `--ok` the success token). Use only tokens `design/scripts/check-tokens.mjs` accepts; run `pnpm --filter @research-harness/design lint` if unsure which names exist.

- [ ] **Step 7: Run the tests and gates**

Run: `pnpm --filter research-harness-web test && pnpm --filter research-harness-web typecheck && pnpm --filter research-harness-web lint && pnpm --filter research-harness-web build`
Expected: PASS, including the axe check.

- [ ] **Step 8: Commit**

```bash
git add web/src/app/SettingsDialog.tsx web/src/app/settings web/src/app/session.tsx
git commit -m "feat(web): Models & providers settings with Local CLIs and API providers tabs"
```

---

### Task 14: Documentation, ADR-030, and status

Spec §22–§24; conventions.md ("documentation and first-run experience").

**Files:**
- Create: `docs/decisions/ADR-030-cli-backed-providers-are-bounded-external-workers.md`
- Modify: `docs/guide/providers.md`, `docs/index.md`, `docs/decisions/README.md`, `docs/architecture/web.md`, `docs/architecture/domain-changelog.md`, `docs/plans/acceptance-matrix.md`, `README.md`, `ROADMAP.md`

- [ ] **Step 1: Write ADR-030**

```markdown
# ADR-030: CLI-backed providers are bounded external workers behind the neutral provider boundary

**Status:** Accepted
**Date:** 2026-09-04
**Source:** `docs/superpowers/specs/2026-09-03-subscription-local-cli-providers-design.md`; `providers/cli/`, `capabilities/cli_providers.py`, `cli/commands/provider.py`, `web/src/app/settings/`

## Context

A researcher who already pays for Codex CLI, Claude Code, Cursor Agent, Amp, DeepSeek
Harness, OpenCode, or Pi has a model login on the workstation and no API key. Open
Design shows the CLIs can be driven headlessly, but it drives them as *full agents*:
tools on, approvals bypassed, the project as the working directory. That authority model
is the opposite of ADR-005 and ADR-007.

## Decision

1. A CLI is a **model backend**, not an agent. `CliModelProvider` turns one
   `ModelRequest` into one subprocess run and returns `RawCompletion`; validation,
   traces, staging, and review are the shared path (ADR-005). Every runtime is a
   declarative `CliRuntimeDef`; the registry refuses a definition carrying a bypass flag.
2. **Bounded execution is native or nothing.** A runtime is routable only when its
   installed version proves a no-tools/read-only posture through a help probe
   (`bounded_mode: safe`). Prompt text alone never counts. A tool or file-write event in
   a bounded run cancels the process and fails the request.
3. **A CLI provider is external egress.** "Local" names where the process starts, not
   where inference happens. Every definition declares a vendor host or
   `unknown.external`; `privacy.external_models: disabled` refuses it before it spawns;
   the catalog, `research egress`, traces, and receipts all say `external`.
4. **Research content travels on stdin or the RPC channel, never argv**, in an empty
   temp cwd, under an environment with every API-key variable removed, so a subscription
   login cannot become metered access by accident.
5. **One capability surface.** `provider.cli.scan|configure|remove|test` are the only
   way any client learns availability or changes `research.yaml`; Web and CLI render the
   same strings.

## Consequences

- Cursor Agent, Amp, DeepSeek Harness, and Pi are detected and catalogued but not
  routable in this release: none documents a deny-tools posture. Adding one is a change
  to a definition's `BoundedPosture` plus fixtures, not to the engine.
- Detection is process-spawning work; `provider.list` consults a 30-second cache so a
  selector stays responsive, and an explicit rescan bypasses it. No availability is
  canonical state.
- Conversation streaming through a CLI answers in prose; structured workflow requests
  are buffered and validated. Image and document inputs are refused in this release.

## Invariants protected

- CLI providers spec §24 (1)–(15); tests under `tests/unit/providers/cli/`,
  `tests/contract/providers/test_cli_provider.py`,
  `tests/contract/capabilities/test_cli_providers.py`,
  `tests/e2e/test_cli_providers_commands.py`, `web/src/app/settings/settings.test.tsx`.
- PRODUCT §34 (egress decided at selection, ADR-018) and §20 (provider neutrality).

## Alternatives rejected

- Running Open Design's daemon as a service: a second authority model and a Node runtime
  in the critical path.
- Treating a local process as local inference: it would let a vendor-hosted model bypass
  the sensitive-corpus switch.
- A prompt-only "do not use tools" instruction as the safety mechanism.
```

- [ ] **Step 2: Extend `docs/guide/providers.md`**

Add a section after *Selecting one*:

```markdown
## Subscription-backed local CLIs

If you are already logged in to Codex CLI, Claude Code, Cursor Agent, Amp, DeepSeek
Harness, OpenCode, or Pi, the harness can route research work through that CLI. No API
key enters Research Harness; the CLI's own login is used.

A CLI provider is **not local**. The process starts here; the model is the vendor's.
Research content and object IDs leave the workstation exactly as they do for an HTTP
provider, and `privacy.external_models: disabled` refuses a CLI provider before it is
started (ADR-030).

```console
$ research providers scan
A local CLI starts on this workstation, but the model it talks to is the vendor's: research content and object IDs leave the machine when a CLI provider is used.

codex              0.150.1        logged in          bounded mode ok        verified
    models (live): default, gpt-5.5, gpt-5.4, gpt-5.4-mini
claude             2.1.259        logged in          bounded mode ok        verified
    models (fallback): default, sonnet, opus, haiku, claude-opus-5, claude-sonnet-5 …
cursor-agent       not installed
…
$ research providers add codex --name codex-sub --model gpt-5.5 --priority 10
added codex-sub (codex/gpt-5.5, priority 10) in research.yaml
select it with --provider codex-sub
$ research providers test codex-sub
egress: codex-sub sends research content to chatgpt.com through Codex CLI
codex-sub (codex/gpt-5.5, 0.150.1): ok
  Codex CLI answered through the subscription login in 2140 ms
$ research interrogate W0001 --provider codex-sub
```

The entry `add` writes:

```yaml
providers:
  - name: codex-sub
    kind: local_cli
    runtime: codex          # codex | claude | cursor-agent | amp | deepseek-harness | opencode | pi
    model: gpt-5.5          # or `default` for the CLI's own configured model
    priority: 10
    reasoning: high         # optional; the runtime's own effort name
    timeout_seconds: 300    # optional
    enabled: true
```

`runtime` is required and `base_url`/`api_key_env` are refused for `kind: local_cli`.

**Bounded mode.** A runtime is routable only when the installed version proves a
no-tools, read-only posture: Codex runs `codex exec --sandbox read-only` with approvals
set to `never` and the user's config and rules ignored; Claude Code runs `claude -p
--tools "" --permission-mode dontAsk --permission-prompts none --strict-mcp-config`.
Both run in an empty temporary directory with every API-key variable removed from the
environment. Cursor Agent, Amp, DeepSeek Harness, and Pi are detected and listed but
report `no bounded mode`: their headless modes need an approval bypass, so `add` refuses
them. A tool call during a bounded run fails the request
(`bounded_authority_violation`); there is no prompt-only fallback.

**What a scan reports.** Installed, version, login (`logged in`, `not logged in`,
`login unverified`), bounded mode, compatibility (`verified` with recorded fixtures for
that version, `warning` for an untested version, `blocked`), and the models the CLI
lists (`live`) or the shipped hints (`fallback`). A scan edits nothing and sends no
research content; it runs the CLI's own `--version`, login-status, help, and model-list
commands with short timeouts. The Web cockpit's *Settings → Models & providers → Local
CLIs* tab renders the same report and calls the same capabilities.

**Traces and errors.** A CLI call is traced like any other under `.research/traces/`,
with the runtime id, version, protocol, and model added. Errors name the runtime, model,
and version and a next action (`run \`codex login\``); they never contain a token, a
credential path, or the raw process output.
```

Also add `local_cli` to the *Configuring `providers:`* field table (`runtime` row: "`kind: local_cli` only: the runtime id"; `reasoning` row) and to the adapter-defaults table (`local_cli` | — | — | "source text + identifiers to the CLI vendor (declared per runtime; `unknown.external` when undisclosed)").

- [ ] **Step 3: Index, ADR table, web.md, changelog, acceptance matrix, README, ROADMAP**

- `docs/index.md`: add the spec row `[Subscription-backed local CLI providers](superpowers/specs/2026-09-03-subscription-local-cli-providers-design.md) | declarative runtime registry, bounded subprocess engine, egress invariant, the four capabilities` under the design specifications table; add ADR-030 to the decisions table; note the plan `[Subscription-backed CLI providers plan](superpowers/plans/2026-09-04-subscription-local-cli-providers.md)` in *Plans and reports*.
- `docs/decisions/README.md`: append the ADR-030 row (`Accepted`).
- `docs/architecture/web.md`: after *The shell and the Design System*, a subsection **Settings → Models & providers**: what it calls (`provider.cli.scan` on open and Rescan, `provider.cli.configure`/`remove`/`test` on the three buttons, `provider.list` for the API tab), that the Add control is disabled by the daemon's gates and repeats its reason, that the egress sentence is the daemon's `notice`, and that an agent host sees the screen read-only. Add the four names to *What the cockpit calls*.
- `docs/architecture/domain-changelog.md`: append a bullet: no domain object changed; `provider.cli.scan|configure|remove|test` join `capabilities/` in `capabilities/cli_providers.py`; `RouterProviderConfig` (a provider-layer model, not domain) gains `runtime` and `reasoning`; `WorkspaceConfig.providers` is unchanged in shape and gains `update_providers`.
- `docs/plans/acceptance-matrix.md`: a table **Subscription-backed local CLI providers (spec §24)** with fifteen rows — criterion → what demonstrates it → where it lives → holds today — e.g. (1) `git submodule status` shows `9bb4a7d`, `tests/unit/providers/cli/test_registry.py::test_the_shipped_registry_is_importable_and_ordered` (no import of the submodule); (2) `test_defs_others.py::test_all_seven_runtimes_are_registered_in_display_order`, `test_detection.py`; (3) `test_cli_providers.py::test_configure_writes_one_validated_entry` and `settings.test.tsx` "adds a provider"; (4) `test_live_cli_smoke.py` (opt-in; ran on 2026-09-04 for codex 0.150.1 and claude 2.1.259 — Task 15 fills in the result); (5) `test_cli_providers_commands.py::test_existing_workflow_commands_select_the_cli_entry_with_provider`; (6) `test_cli_provider.py::test_research_content_travels_on_stdin_never_argv` and `test_registry.py::test_research_content_may_not_reach_argv`; (7) `test_cli_provider.py::test_capabilities_are_external_text_only_and_structured`, `test_types.py::test_the_unknown_external_host_is_never_local`; (8) `test_cli_provider.py::test_the_privacy_policy_refuses_before_any_process_is_spawned`, `test_cli_providers.py::test_the_test_call_is_refused_by_the_policy_before_any_spawn`; (9) `test_cli_provider.py::test_a_tool_event_cancels_the_process_and_is_a_bounded_authority_violation` and the five-runtime tool cases; (10) `test_invalid_json_fails_through_the_shared_structured_output_path`, `test_a_schema_violation_never_returns_a_partial_object`; (11) `test_process.py::test_cancel_terminates_grandchildren`, `test_cli_provider.py::test_abandoning_the_stream_cancels_the_process`; (12) `test_cli_providers.py::test_configure_and_scan_answer_identically_over_the_daemon`, `settings.test.tsx` "renders the daemon states … with its own words"; (13) the pre-existing `tests/contract/providers` and `tests/e2e/invariants/test_a_provider_independence.py` unchanged and green; (14) every default test uses `tests/fixtures/cli/fakes.py`; `test_new_capability_parity.py` empties `PATH`; (15) `test_errors.py::test_messages_carry_identity_and_a_next_action_but_no_secret`, `test_detection.py::test_a_diagnostic_never_carries_a_home_path_or_a_token`, `test_cli_providers.py::test_the_test_call_reports_a_failure_without_a_secret`, the Task 15 secret scan.
- `README.md`: in *Status*, add a paragraph: "**Subscription-backed local CLI providers** (2026-09-04): a researcher logged in to Codex CLI or Claude Code can route research work through that CLI with no API key, under the same privacy policy, traces, and review gates; Cursor Agent, Amp, DeepSeek Harness, OpenCode, and Pi are detected but not routable until they document a bounded mode. See [providers](docs/guide/providers.md#subscription-backed-local-clis) and ADR-030." Add the providers guide anchor to the *Documentation* list if it is not already linked.
- `ROADMAP.md`: after the v1.1 track sections and before *Later Post-v1.0 Extensions*, add `## v1.1 follow-on — Subscription-backed local CLI providers` with **Outcome**, **Relative effort: Medium**, *Product scope* (seven bullets from spec §2), *Boundary requirements* (spec §3–§4, §12 in five bullets), and a **Gate status (2026-09-04)** table listing spec §24 (1)–(15) with `holds` / `holds (opt-in live run)` / `n/a on this workstation` and the test that demonstrates each (the same mapping as the acceptance matrix).

- [ ] **Step 4: Check the docs build nothing but text**

Run: `uv run python docs/guide/gen_capabilities.py && git diff --stat docs README.md ROADMAP.md`
Expected: only the intended files change; `capabilities.md` is unchanged (already regenerated in Task 11).

- [ ] **Step 5: Commit**

```bash
git add docs README.md ROADMAP.md
git commit -m "docs: subscription-backed CLI providers — guide, ADR-030, acceptance matrix, and status"
```

---

### Task 15: Full gates, secret scan, and the opt-in live smoke on the installed CLIs (PM)

Spec §20 (optional live tests), §23.12, §24 (4), (14), (15). Run by the PM after Task 14.

**Files:**
- Create: `tests/contract/providers/test_live_cli_smoke.py`
- Possibly create: `tests/fixtures/cli/streams/codex-live-0.150.1.jsonl`, `claude-live-2.1.259.jsonl` (sanitized captures); update `verified_versions` if a different version answered.

- [ ] **Step 1: Write the opt-in live test**

```python
"""Opt-in live smoke through the CLIs installed and logged in on this workstation.

Never part of CI: skipped unless `RESEARCH_HARNESS_LIVE_CLI_TESTS=1`, and per runtime
unless the CLI is installed, logged in, and bounded. One minimal schema-validated
request per runtime; no project file is read; on failure nothing raw is printed.

    RESEARCH_HARNESS_LIVE_CLI_TESTS=1 uv run pytest tests/contract/providers/test_live_cli_smoke.py -q

Set `RESEARCH_HARNESS_LIVE_CLI_CAPTURE=<dir>` to also write a sanitized JSONL capture of
the event stream per runtime, for the parser fixtures.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from research_harness.providers.cli.detection import detect
from research_harness.providers.cli.process import BoundedProcess
from research_harness.providers.cli.provider import CliModelProvider
from research_harness.providers.cli.registry import RUNTIMES
from research_harness.providers.models.base import InputEnvelope, ModelRequest, ModelRequirements
from tests.contract.providers.conftest import SOURCE_TEXT, Verdict

LIVE_FLAG = "RESEARCH_HARNESS_LIVE_CLI_TESTS"
CAPTURE = "RESEARCH_HARNESS_LIVE_CLI_CAPTURE"
live_only = pytest.mark.skipif(os.environ.get(LIVE_FLAG) != "1", reason=f"set {LIVE_FLAG}=1 to run live CLI smoke tests")

_ID = re.compile(r"\b(?:sess|thread|msg|toolu|req|call|ses)[_-][A-Za-z0-9_-]+\b")


def _request() -> ModelRequest[Verdict]:
    return ModelRequest(
        role="evidence_verifier",
        requirements=ModelRequirements(structured_output=True, context_tokens=20_000, reasoning="low", max_output_tokens=512),
        instructions="Decide whether the source text states the throughput figure. Answer only with the required structured object.",
        inputs=[InputEnvelope(object_id="work:live", kind="source_text", content=SOURCE_TEXT)],
        response_schema=Verdict,
        temperature=0.0,
    )


class _Capturing(BoundedProcess):
    captured: list[str] = []

    def lines(self):  # type: ignore[override]
        for line in super().lines():
            type(self).captured.append(line)
            yield line


def _sanitize(line: str) -> str:
    return _ID.sub("sess-x", re.sub(r"/home/[^/\s\"]+", "~", line))


@live_only
@pytest.mark.parametrize("runtime", ["codex", "claude"])
def test_live_cli_smoke(runtime: str, tmp_path: Path) -> None:
    status = detect(RUNTIMES[runtime])
    if not status.routable:
        pytest.skip(f"{runtime}: {status.diagnostics or status.auth_status}")
    _Capturing.captured = []
    spawn = _Capturing.spawn if os.environ.get(CAPTURE) else BoundedProcess.spawn
    provider = CliModelProvider(runtime, "default", timeout=180, spawn=spawn, version=status.version)

    response = provider.complete(_request())

    assert isinstance(response.parsed, Verdict)
    assert response.provider == f"local_cli:{runtime}" and response.request_fingerprint
    if os.environ.get(CAPTURE):
        out = Path(os.environ[CAPTURE]) / f"{runtime}-live-{status.version}.jsonl"
        out.write_text(f"# source: live {runtime} {status.version} on 2026-09-04; sanitized\n" + "\n".join(_sanitize(line) for line in _Capturing.captured) + "\n", encoding="utf-8")
```

Add to `tests/unit/providers/cli/test_parsers.py` a test that every `*-live-*.jsonl` present parses to a `done` event with non-empty text (skipped when there is none).

- [ ] **Step 2: Run every gate**

Run, from the repository root with `PATH` set as in Global Constraints:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy src
pnpm --filter research-harness-web typecheck && pnpm --filter research-harness-web lint && pnpm --filter research-harness-web test && pnpm --filter research-harness-web build
pnpm --filter @research-harness/design test
git grep -nE 'sk-(proj-)?[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9._-]{20,}|xox[abpr]-' -- ':!open-design' ':!deepseek-harness' ':!tests' ':!docs/superpowers/plans' ':!pnpm-lock.yaml'
```

Expected: every suite green; the secret scan prints nothing.

- [ ] **Step 3: Run the live smoke and capture fixtures (this workstation only)**

```bash
mkdir -p tests/fixtures/cli/streams
RESEARCH_HARNESS_LIVE_CLI_TESTS=1 RESEARCH_HARNESS_LIVE_CLI_CAPTURE=tests/fixtures/cli/streams uv run pytest tests/contract/providers/test_live_cli_smoke.py -q -s
```

Expected: two passes (codex 0.150.1, claude 2.1.259). Inspect the two captures for anything that is not event structure (an account id, an e-mail, a home path) and sanitize by hand; then run the parser tests again. If a runtime answered on a version other than the one in `verified_versions`, add it there.

- [ ] **Step 4: Record the outcome**

Fill in the live-run row of `docs/plans/acceptance-matrix.md` and the ROADMAP gate table with the date and versions; commit:

```bash
git add tests/contract/providers/test_live_cli_smoke.py tests/fixtures/cli/streams tests/unit/providers/cli/test_parsers.py docs/plans/acceptance-matrix.md ROADMAP.md src/research_harness/providers/cli/defs
git commit -m "test: opt-in live CLI smoke with sanitized captures; gate status recorded"
```

---

## Self-review

**Spec coverage.** §2 goals → Tasks 6 (detect without mutation), 8 (RawCompletion path, bounded cancel), 10–13 (CLI + Web), 9 (adding a CLI is a definition + fixtures). §3 non-goals → registry forbids bypass flags (T1), media refused (T8), no failover (router unchanged, T8 test), no session resume (no def field). §4 egress → T1 host rule, T8 capabilities, T10 policy-before-spawn, T14 docs. §5 submodule → already pinned; T1 test notes it is never imported. §6–§7 architecture/package → file map; `transport.py` and `environment.py` are two additions to the spec's proposed tree, both pure engine concerns. §8 registry → T1. §9 matrix → T7, T9. §10 detection → T6. §11 configuration → T8 router, T10 capabilities. §12 execution → T2, T3, T5, T7, T8. §13 parsing → T4, T8 collector. §14 cancellation → T3, T8. §15 errors → T1, T8. §16 capabilities → T10. §17 CLI → T11. §18 Web → T13. §19 privacy/logging → T1 redact, T8 trace metadata, T10 test report redaction. §20 tests → each task; live → T15. §21 compatibility → T6 `compatibility_of`, T7/T9 `verified_versions`. §22 backward compatibility → T8 keeps every HTTP test green; T10 keeps `provider.list` semantics for HTTP entries. §23 sequence → the task order. §24 acceptance → T14 matrix, T15 gates.

**Placeholder scan.** No "TBD"/"TODO"; the only deferred item is the `useToast` call signature (T13), which the implementer reads from the primitive, and the two captured help texts (T7), which are captured by command.

**Type consistency.** `CliRuntimeStatus` fields are identical across T1 (Python), T12 (TS DTO), T13 (mappers). `provider_name()` yields `local_cli:<runtime>` in T1 and is asserted in T8/T10/T11. `ConfigureCliProviderRequest` fields match `CliProviderConfigureRequest` in T12 and the request the T13 test asserts. `unavailable_reason()` strings in T1 are the strings T10's tests and T13's `RuntimeCard.unavailableReason` repeat. `EXTERNAL_EGRESS_NOTICE` is the `notice` T12's fixture and T13's tests read. Transport protocol `start/observe/intercept/cancel` (T5) is what `_drive` calls (T8). `ProbeOutcome`-taking parsers (T1 types) are what T7/T9 helpers accept and T6 calls.
