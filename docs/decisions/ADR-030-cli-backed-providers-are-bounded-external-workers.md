# ADR-030: CLI-backed providers are bounded external workers behind the neutral provider boundary

**Status:** Accepted
**Date:** 2026-09-04
**Source:** PRODUCT.md §20, §21, §34, §42 (A); `docs/superpowers/specs/2026-09-03-subscription-local-cli-providers-design.md` §4, §8–§12, §17–§19, §21, §24; implemented in `providers/cli/` (`types.py`, `registry.py`, `defs/`, `detection.py`, `environment.py`, `process.py`, `transport.py`, `parsers/`, `prompt.py`, `provider.py`, `errors.py`), `capabilities/cli_providers.py`, `cli/commands/provider.py`, `web/src/app/settings/`

## Context

A researcher who already pays for Codex CLI, Claude Code, Cursor Agent, Amp, DeepSeek
Harness, OpenCode, or Pi has a model login on the workstation and no API key. Open Design
(the pinned reference implementation, `open-design@9bb4a7d`) shows the CLIs can be driven
headlessly, but it drives them as *full agents*: tools on, approvals bypassed, the project
as the working directory — `--sandbox workspace-write`, `--permission-mode
bypassPermissions`, `--force`, `--dangerously-allow-all`. That authority model is the
opposite of ADR-005, where the provider layer answers one request and proposes nothing, and
of ADR-007, where nothing reaches accepted state without review. It also collapses PRODUCT
§21's two layers: an agent host is where the researcher works, a model provider is a worker
the harness calls. Claude Code is both, and the two must not be coupled.

The second trap is the word "local". The process starts here; the model does not run here.
Classifying a CLI provider as local inference would let a vendor-hosted model past the
sensitive-corpus switch that ADR-018 puts at provider selection.

## Decision

1. **A CLI is a model backend, not an agent.** `CliModelProvider` turns one `ModelRequest`
   into one subprocess run and returns one `RawCompletion`; validation, traces, staging, and
   review stay on the shared path (ADR-005). Every runtime is a declarative `CliRuntimeDef`
   — data plus pure builders — and `registry.py` refuses, at import, a definition carrying a
   bypass flag, a shell operator, a local egress host, or research content in argv.
2. **Bounded execution is native or nothing.** A runtime is routable only when the
   *installed* version proves a no-tools, read-only posture (`bounded_mode: safe`) — a flag
   posture through a help probe, an environment-injected posture through recorded fixtures,
   because no help output can attest to a deny table. Prompt text alone never counts. Codex
   runs `codex exec --json --skip-git-repo-check --ephemeral --ignore-user-config
   --ignore-rules --sandbox read-only -c approval_policy="never" -C <temp cwd>`; Claude Code
   runs `claude -p --tools "" --permission-mode dontAsk --permission-prompts none
   --strict-mcp-config --disable-slash-commands --no-session-persistence --restricted`. A
   tool or file-write event in a bounded run cancels the process and fails the request
   (`bounded_authority_violation`).
3. **A CLI provider is external egress.** Every definition declares a vendor host or
   `unknown.external`; `privacy.external_models: disabled` refuses it before a process is
   spawned; the catalog, `research egress`, traces, and receipts all say `external`.
4. **The subscription login is the only credential, and it stays the subscription login.**
   Research content travels on stdin or the runtime's RPC channel — never argv — in an empty
   temporary working directory, under an environment allow-list from which every API-key,
   token, and cloud-credential variable is removed. Dropping variables is not sufficient on
   its own, because a persisted API-key login lives in the CLI's own config directory, which
   the allow-list keeps; so the auth probe decides too. Codex counts as logged in only for a
   ChatGPT login, Claude Code only for `authMethod: claude.ai`. Any other login is reported
   as not logged in, with guidance, because it is metered and reaches a different host.
5. **One capability surface.** `provider.cli.scan|configure|remove|test` are the only way any
   client learns availability or changes `research.yaml`. The server computes `routable` and
   `unavailable_reason`; Web and CLI render those strings and re-derive no rule (ADR-004).

## Consequences

- Five of the seven runtimes are detected and catalogued but not routable in this release,
  and the scan says why for each. Cursor Agent, Amp, DeepSeek Harness, and Pi report
  `bounded_mode: unsupported` — the first two run headless only behind an approval bypass, and
  the other two execute tools of their own. OpenCode declares a deny table injected through
  `OPENCODE_CONFIG_CONTENT`, which counts only on a version with recorded fixtures, and there
  is none yet, so it reports `bounded_mode: unknown`. `research providers add` refuses all
  five. Admitting a runtime is a change to one definition's `BoundedPosture` plus fixtures,
  not to the engine.
- A version the harness has no fixtures for is `warning`, and one whose version string cannot
  be parsed is `unknown` — both still routable when a help probe proved the posture on the
  installed build. Only a version that is known-incompatible or below the definition's minimum
  version is `blocked`. Refusing every unrecognised version would break the provider on the
  CLI's next release.
- Detection spawns processes, so `provider.list` consults a 30-second in-memory cache and an
  explicit rescan bypasses it. No availability is canonical state.
- Conversation streaming through a CLI answers in prose; structured workflow requests are
  buffered and validated through the shared structured-output path. Image and document inputs
  are refused in this release.
- The harness now depends on the flags of a third-party CLI. Drift surfaces at the help probe
  rather than mid-run: a build missing a required flag is reported unsupported instead of
  being sent a flag it does not understand.

## Invariants this ADR protects

- Research content never appears in argv, in a process listing, or in a file outside the
  request's temporary working directory (spec §12, §24 (6)).
- A definition that carries a bypass flag, a shell operator, or a local egress host cannot be
  loaded, let alone spawned (spec §8, §12; §24 (7)).
- A runtime with no proven bounded posture is never spawned for research, and there is no
  prompt-only fallback (spec §12; §24 (9)).
- The privacy policy decides before a process exists, on every transport (ADR-018, PRODUCT
  §34; spec §24 (8)).
- A subscription login never becomes metered API-key access (spec §12, §19; §24 (4)).
- No credential, home path, or raw process output reaches an error, a diagnostic, a trace,
  `research.yaml`, a fixture, or browser storage (PRODUCT §34; spec §19, §24 (15)).
- Invalid, partial, or schema-incompatible output never reaches staging, and a cancellation or
  timeout terminates the whole process tree (spec §13, §14; §24 (10), (11)).
- Provider neutrality holds: no workflow, capability, or domain module knows a runtime exists
  (PRODUCT §20, §42 (A); ADR-005; spec §24 (5), (13)).

## Addendum, 2026-09-04: a session binding is a second way to name a CLI provider

**Source:** `docs/superpowers/specs/2026-09-04-session-runtime-binding-design.md` §5, §8, §9;
implemented in `conversation/binding.py`, `conversation/service.py::ConversationService.configure`,
`conversation/send.py::WorkspaceProviders.select`, `capabilities/conversation.py`
(`session.configure`), `cli/commands/session.py` (`research chat configure`), and the
conversation composer under `web/src/views/conversation/`.

A conversation session may name a runtime, a model, and an effort level without an entry in
`research.yaml`. The binding is stored on the session record — `defaults.model` as
`local_cli:<runtime>` plus `defaults.reasoning` — never in project configuration, and it is
resolved on every send into one in-memory `RouterProviderConfig` named `session:<runtime>`,
appended to a copy of the routing table for that call alone.

This changes nothing in the decision above. The binding goes through the *same* validator a
hand-written entry goes through (`RouterProviderConfig`), so an unknown runtime, a runtime
with no proven bounded posture, and an effort name the runtime does not offer are refused
with the entry's own sentences; and the resolved call passes the same gates in the same
order — the privacy policy first, then the run-time runtime gate in `CliModelProvider._run`
with `bounded_mode_unsupported`, `version_blocked`, `login_missing`, or
`executable_missing`. No gate is added, none is bypassed, and the `availability` injection
point is never passed. Every invariant listed above therefore applies to a binding exactly
as it applies to an entry.

Two consequences worth stating:

- **It is still external egress.** A private session may not be bound to a runtime at all:
  `session.configure` refuses with the send path's own private-egress sentence, because a
  binding that could never answer is not a binding worth storing. Visibility is decided at
  creation and no capability changes it, so a session that will use a bound runtime is
  opened with `research chat new --visibility project`.
- **The label says which path answered.** `ProviderProfile.provider` — and so the
  transcript, the receipt, and the run record — carries `session:<runtime>` with the bound
  model; the trace keeps the adapter's own `local_cli:<runtime>`, because the trace writer
  records the adapter rather than the entry. A reader can tell a session-bound answer from
  one routed through a configured entry.

Enforced by `tests/contract/conversation/test_session_configure.py`,
`tests/integration/conversation/test_send_session_binding.py`,
`tests/unit/conversation/test_binding.py`, `tests/e2e/test_chat_configure_command.py`, and
`web/src/views/conversation/{ConversationRoute.test.tsx,mappers.test.ts}`.

## Rejected alternatives

- **Run Open Design's daemon as a service.** A second authority model, a Node runtime in the
  critical path, and a bypass posture to unwind on every upgrade.
- **Treat a local process as local inference.** It reads well in a selector and would let a
  vendor-hosted model past the sensitive-corpus switch — the one thing ADR-018 exists to stop.
- **Use a prompt-only "do not use tools" instruction as the safety mechanism.** Model
  instructions are not an authority boundary; a single non-compliant turn is a file write.
- **Read the CLI's credential store and call the vendor's HTTP API directly.** Faster and
  fully typed, and it turns a subscription login into an exfiltrated token; spec §19 forbids
  the harness reading, copying, exporting, or displaying a credential store at all.
- **Refuse any version without recorded fixtures.** Safe-looking, but it makes every upstream
  release an outage; the help probe proves the posture on the build that is installed.

## Where it is enforced

- `providers/cli/registry.py` — `FORBIDDEN_ARGS`, the shell-operator and prompt-marker checks,
  and `is_local_endpoint` on every declared host, run over `SAMPLE_INVOCATIONS` at import.
- `providers/cli/types.py` — `BoundedPosture`, `UNKNOWN_EXTERNAL_HOST`, and the server-computed
  `CliRuntimeStatus.routable` / `unavailable_reason`.
- `providers/cli/environment.py` — `BASE_KEEP`, `ALWAYS_DROP` (deny-list wins), `FIXED_ENV`.
- `providers/cli/defs/*.py` — each runtime's bounded argv, help-probe flags, and
  `classify_auth`; `detection.py` (fault-isolated probes, `ScanCache`), `process.py`
  (process-group cancellation), `transport.py`, `parsers/`, `prompt.py`, `provider.py`,
  `errors.py` (`DiagnosticCode`, redaction).
- `capabilities/cli_providers.py` (the four capabilities, `EXTERNAL_EGRESS_NOTICE`,
  `cli_availability`) and `capabilities/providers.py`; `cli/commands/provider.py`;
  `web/src/app/settings/`.
- `tests/unit/providers/cli/`, `tests/contract/providers/test_cli_provider.py`,
  `tests/contract/capabilities/test_cli_providers.py`,
  `tests/e2e/test_cli_providers_commands.py`, `web/src/app/settings/settings.test.tsx`.
- `docs/guide/providers.md` — *Subscription-backed local CLIs*.
