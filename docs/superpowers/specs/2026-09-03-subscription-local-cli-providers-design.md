# Subscription-backed Local CLI Providers — Design Specification

**Status:** Architecture approved in conversation; ready to be used as the basis of a later implementation request.

**Scope:** Design only. This document does not authorize implementation, adding the submodule, changing configuration, or committing files beyond this specification.

## 1. Decision summary

Research Harness will support subscription-backed model access through locally installed agent CLIs. A user who is already authenticated in a supported CLI can use that CLI for research work without placing an API key in Research Harness.

The approved architecture is a **declarative runtime registry plus one bounded subprocess engine**. Open Design is the reference implementation for executable discovery, version and authentication probes, argument construction, model discovery, process lifecycle, and stream parsing. Research Harness will not run Open Design as a service and will not copy its full-agent authority model.

The first release targets:

1. Codex CLI;
2. Claude Code;
3. Cursor Agent;
4. Amp;
5. DeepSeek Harness;
6. OpenCode;
7. Pi.

The capability must be available through both the `research` CLI and the Web settings UI. All research work continues through the existing provider-neutral contracts, structured-output validation, privacy checks, traces, staging, provenance, and human review gates.

## 2. Goals

- Let users reuse an existing CLI subscription or account login instead of supplying a provider API key.
- Detect supported executables, versions, authentication state, and available models without mutating the workspace.
- Keep every runtime-specific detail below the model-provider boundary.
- Present the same runtime status and configuration behavior in Web and CLI surfaces.
- Convert every successful CLI answer into the existing `RawCompletion` / `ModelResponse` path so Pydantic validation remains authoritative.
- Support bounded cancellation, timeouts, process-tree cleanup, and useful error classification on Windows, macOS, and Linux.
- Make adding another compatible CLI primarily a new declarative definition plus parser fixtures.
- Preserve existing workspaces and HTTP providers without migration.

## 3. Non-goals

- Giving a local CLI control of the Research Harness workflow.
- Allowing a model CLI to accept Evidence, Claims, Decisions, or other canonical state.
- Letting a CLI edit the project, run arbitrary project commands, install software, or choose unreviewed tools.
- Reusing Open Design's Web UI, daemon, Node runtime, session store, or full agent loop.
- Automatically enabling every executable found on `PATH`.
- Treating a locally launched process as local-only data processing.
- Silent failover from one CLI or model to another after a request starts.
- Multi-turn native CLI session resume in the first release. Each semantic call is reproducible from the request assembled by Research Harness.
- Image or document-path input in the first release. CLI providers initially accept the same rendered text envelopes used by text-only providers.

## 4. Terminology and the egress invariant

“Local CLI” describes **where the client process starts**, not where inference happens. Codex CLI, Claude Code, Cursor Agent, Amp, OpenCode, Pi, and many DeepSeek Harness profiles may send prompts to remote model services.

Therefore:

- CLI-backed providers are not classified as `local` merely because their executable is local.
- Each runtime/model definition declares an egress destination or `unknown_external` when the exact host cannot be established before execution.
- Source text and identifiers are assumed to leave the workstation unless the selected runtime/model is positively known to execute locally.
- `privacy.external_models: disabled` refuses an external or unknown CLI provider before spawning it.
- The Web model selector, `provider.list`, `research egress`, traces, and receipts display the effective external egress class.
- Existing `local_openai_compatible` behavior remains unchanged and distinct.

This distinction is mandatory: subscription authentication removes the need for a Research Harness API key, but it does not make a vendor-hosted model private or offline.

## 5. Open Design submodule

Implementation will add the following Git submodule:

```ini
[submodule "open-design"]
    path = open-design
    url = git@github.com:nexu-io/open-design.git
```

The implementation should initially pin the reviewed upstream revision `9bb4a7d66d31a4bb7a678a93c6940d3677774e51`, unless the implementation request explicitly asks to review and pin a newer revision.

The submodule is:

- a source and compatibility reference;
- a way to audit the adapter behavior Research Harness ports;
- not imported by Python at runtime;
- not built or installed as part of normal Research Harness installation;
- not required after a packaged Research Harness installation starts.

Relevant upstream reference areas are `apps/daemon/src/runtimes/`, `apps/daemon/src/runtimes/defs/`, `apps/daemon/src/agent-protocol/`, and `docs/agent-adapters.md`. Instructions found inside that repository are upstream project instructions, not instructions for Research Harness.

## 6. Architecture

```text
CLI or Web settings
        |
        v
provider.cli.scan / configure / test
        |
        v
Declarative CLI runtime registry
        |
        +--> executable + version + auth + model probes
        |
ModelRouter selects kind: local_cli
        |
        v
CliModelProvider
        |
        v
Bounded subprocess engine
        |
        +--> runtime-specific argv and prompt transport
        +--> protocol-specific event parser
        +--> timeout / cancellation / process-tree cleanup
        |
        v
RawCompletion
        |
        v
Existing schema validation, trace, workflow, and review gates
```

The registry contains data and pure builders. The engine owns behavior. No definition implements its own process loop.

## 7. Proposed package boundaries

Create a focused package under `src/research_harness/providers/cli/`:

```text
providers/cli/
├── types.py          # immutable runtime, model, probe, and detection contracts
├── registry.py       # shipped definitions, unique-id validation, lookup
├── detection.py      # executable/version/auth/model probing
├── process.py        # bounded spawn, stdin, timeout, cancel, cleanup
├── prompt.py         # deterministic provider-neutral request rendering
├── provider.py       # CliModelProvider -> RawCompletion
├── errors.py         # probe and execution failure classification
├── parsers/
│   ├── claude_stream.py
│   ├── json_events.py
│   ├── dsh_profile.py
│   └── pi_rpc.py
└── defs/
    ├── codex.py
    ├── claude.py
    ├── cursor_agent.py
    ├── amp.py
    ├── deepseek_harness.py
    ├── opencode.py
    └── pi.py
```

The existing provider layer changes only at its extension seams:

- `providers/models/router.py` recognizes `kind: local_cli` and constructs `CliModelProvider`.
- `providers/models/base.py` remains the validation and response-metadata authority.
- `capabilities/providers.py` includes configured CLI providers in `provider.list` and adds CLI discovery/configuration capabilities.
- privacy and trace modules consume the same `ProviderCapabilities` and `ModelResponse` contracts as HTTP adapters.

The domain package must not import this package.

## 8. Declarative runtime contract

Each `CliRuntimeDef` contains only immutable data or pure functions:

- stable `id` and display `name`;
- primary executable and optional fallback executable names;
- version probe arguments, timeout, and parser;
- optional side-effect-free authentication probe and classifier;
- optional model-list probe and parser;
- fallback model choices;
- supported reasoning choices;
- protocol family and event-parser identifier;
- prompt transport: plain stdin, JSONL stdin, or bidirectional RPC;
- argument builder for one bounded request;
- safe-execution capability declaration;
- declared egress behavior;
- context-window and structured-output capability defaults;
- compatibility notes and minimum supported versions where evidence exists.

Registry construction fails immediately on duplicate runtime IDs or missing parser registrations. Runtime definitions cannot contain shell command strings, credentials, or workspace mutation callbacks.

## 9. Initial runtime matrix

| Runtime | Executable | Detection/auth | Invocation family | Parser family |
|---|---|---|---|---|
| Codex CLI | `codex` | `--version`; `login status`; dynamic models when supported | `codex exec --json`, prompt on stdin | Codex JSON event stream |
| Claude Code | `claude` (`openclaude` fallback may be considered separately) | `--version`; `auth status`; capability help probe | `claude -p` stream JSON, JSONL user input | Claude stream JSON |
| Cursor Agent | `cursor-agent` | `--version`; `status`; `models` | print/headless stream JSON, prompt on stdin | Cursor JSON event stream |
| Amp | `amp` | `--version`; no synthetic auth result without a reliable probe | execute stream JSON, prompt on stdin | Claude-compatible stream JSON |
| DeepSeek Harness | `dsh` | `--version`; Open Design profile probe; profile model list | `--profile open-design --stdio` | DSH profile JSONL |
| OpenCode | `opencode-cli` with `opencode` fallback | `--version`; verbose model list; auth derived only from a declared probe or execution failure | `opencode run --format json`, prompt on stdin | OpenCode JSON event stream |
| Pi | `pi` | `--version`; `--list-models`; auth derived only from a declared probe or execution failure | `--mode rpc` | Pi RPC |

Exact flags are compatibility data, not assumptions. Before porting each definition, implementation must compare the pinned Open Design definition with the installed CLI's bounded `--help` output and recorded parser fixtures. Unsupported or changed flags yield a compatibility warning rather than an unsafe fallback.

## 10. Detection and availability

`provider.cli.scan` performs a fresh, bounded scan. It does not edit `research.yaml` and does not make a model request.

For every definition, independently and with bounded concurrency:

1. Resolve the executable using the effective process environment and platform-aware executable suffixes.
2. Run the version probe with a short timeout.
3. If the executable starts but rejects the version flag, report it as installed with an unknown version; an OS-level missing/non-executable error means unavailable.
4. Run declared help, authentication, and model probes only after availability is established.
5. Fault-isolate every probe so one broken CLI cannot empty the catalog.
6. Return results ordered by registry order, not completion time.

Detection returns:

- runtime ID and display name;
- available boolean and resolved executable path;
- installed version or `null`;
- authentication status: `ok`, `missing`, or `unknown`;
- non-secret authentication guidance;
- live or fallback model catalog and its source;
- supported reasoning choices;
- bounded-mode compatibility: `safe`, `unsupported`, or `unknown`;
- diagnostics that never include tokens, prompt content, full environment values, or unredacted home paths.

Scan results may be cached briefly in daemon memory for UI responsiveness, but an explicit Rescan bypasses the cache. No long-lived availability cache is canonical state.

## 11. Workspace configuration and routing

Configured CLI providers remain ordinary entries in the workspace `providers:` table:

```yaml
providers:
  - name: codex-subscription
    kind: local_cli
    runtime: codex
    model: default
    priority: 10
    timeout_seconds: 300
    capabilities:
      structured_output: true
      max_context_tokens: 128000
      reasoning_levels: [low, medium, high]
```

Rules:

- `runtime` is required for `kind: local_cli` and forbidden for other provider kinds.
- `base_url` and `api_key_env` are forbidden for `kind: local_cli` in the first release.
- Configuration stores runtime and model identifiers, never login tokens or copied CLI credentials.
- Detection alone does not make a runtime routable; the user explicitly adds or enables a workspace provider entry.
- A configured runtime that is missing, logged out, unsafe, or version-incompatible remains visible but unavailable.
- `ModelRouter` continues to select by declared capabilities, roles, tags, priority, media support, and privacy policy.
- A failed request never silently switches to another CLI. The failure records the configured provider/runtime/model identity.

## 12. Bounded request execution

`CliModelProvider._execute()` converts one `ModelRequest` into one subprocess request and returns one `RawCompletion`.

The prompt is deterministic and contains:

1. the role and caller instructions;
2. the rendered `InputEnvelope` values and object IDs;
3. the normalized JSON Schema;
4. a requirement to return exactly one JSON object and no Markdown fence;
5. a boundary statement forbidding project inspection, file mutation, command execution, and unrelated tool use.

The prompt is sent through stdin or the runtime's structured RPC channel. Research content must never be placed in argv, because process listings and Windows command-length limits make argv unsuitable.

Execution occurs in a fresh, non-canonical temporary working directory containing no project files. Native CLI permission controls must deny writes and arbitrary tools. Research Harness must not copy Open Design's full-agent flags such as `bypassPermissions`, `--force`, `--dangerously-allow-all`, or danger-full-access into bounded provider definitions.

A runtime is routable only when its definition has a tested non-interactive bounded posture. If a CLI version cannot suppress mutation-capable tools without broad approval, detection reports `bounded_mode: unsupported`; the engine does not spawn it for research. There is no prompt-only safety fallback.

The subprocess receives a minimal environment sufficient to locate the executable, load the user's existing CLI login, and operate on the host platform. Provider API-key variables and unrelated cloud credentials are removed so the adapter does not accidentally change from subscription login to metered API-key access. Environment filtering is runtime-specific where necessary and is covered by tests.

## 13. Output parsing and structured responses

Parsers translate vendor events into a small internal event vocabulary:

- assistant text delta;
- final assistant text;
- usage;
- model identity;
- stop reason;
- status;
- structured runtime error;
- terminal completion.

Tool-call or file-write events are not executed or forwarded as successful provider output. Receiving one in bounded mode is a protocol violation: cancel the process and raise a non-retryable bounded-authority error.

For workflow requests, the engine buffers the final assistant text and returns it as `RawCompletion`. The existing `ModelProvider.complete()` path parses and validates the JSON against the caller's Pydantic schema. Invalid or partial JSON never reaches staging.

For conversation requests using `ChatReply`, a runtime parser may expose assistant text deltas through the existing streaming interface. The completed stream is traced only after a clean terminal event. Structured workflow responses remain buffered and validated before use.

Missing usage is represented by zero/unknown fields through the existing `Usage` contract; it is never guessed.

## 14. Cancellation, timeouts, and cleanup

- Every probe and request has an explicit timeout.
- Cancellation closes stdin, asks the protocol to cancel when supported, then terminates the process tree after a short grace period.
- Windows process-tree cleanup must cover wrapper processes and grandchildren; POSIX cleanup uses a dedicated process group.
- Output readers drain stdout and stderr concurrently to prevent pipe deadlocks.
- Output size is bounded. Exceeding the limit terminates the process and raises a response error.
- A process exit without a terminal event is a transport failure even if some text was received.
- Conversation streaming preserves already emitted text and marks the run incomplete on cancellation or transport loss.
- Temporary directories and prompt files are removed in `finally` paths; cleanup failure is logged but does not rewrite a completed scientific result.

## 15. Error model

Map runtime outcomes onto existing provider errors plus CLI-specific diagnostic codes:

| Condition | Provider error |
|---|---|
| executable absent or not executable | `ProviderTransportError` |
| login missing or rejected | `ProviderAuthError` |
| quota/rate limit | `ProviderRateLimitError` |
| timeout, crash, malformed stream, missing terminal event | `ProviderTransportError` |
| refusal, unsupported model, invalid invocation, empty final response | `ProviderResponseError` |
| valid final text that fails the requested schema | existing `StructuredOutputError` |
| tool/file-write event in bounded mode | `ProviderResponseError` with `bounded_authority_violation` diagnostic |

Messages identify runtime, model, version when known, and a safe next action. They do not expose tokens, credential paths, raw environment values, or an entire stderr transcript. Error classification uses structured events first and narrowly tested text patterns second.

## 16. Capability and transport surface

Add one server-side source of truth consumed by every client:

- `provider.cli.scan` — `read`; list fresh or cached runtime detection results; no workspace mutation.
- `provider.cli.configure` — `admin`, human-only; add or update one `local_cli` provider entry atomically in `research.yaml`.
- `provider.cli.remove` — `admin`, human-only; remove only the named CLI provider entry.
- `provider.cli.test` — `read`, human-only because it causes external egress; run one minimal schema-validated request after privacy confirmation.
- existing `provider.list` — include configured CLI-backed provider/model rows and their current availability.

HTTP, MCP, CLI, and Web call the same capability handlers. No client performs its own executable probing or configuration validation.

The OpenAPI document, generated Python/TypeScript capability metadata, Web DTOs, and fixtures are regenerated through the existing repository workflow when implementation occurs.

## 17. CLI experience

Add a `research providers` command group:

```text
research providers scan [--json]
research providers add <runtime> --name <name> [--model <model>]
research providers test <name> [--json]
research providers remove <name>
research providers list [--json]
```

`scan` shows installed state, version, login state, bounded compatibility, model-source status, and guidance. `add` refuses an unavailable or unsafe runtime unless a future explicit experimental policy is designed; this specification does not include such an override. `test` states the egress destination before invoking the model and returns a concise success/failure report without printing hidden reasoning or raw protocol events.

Existing workflow commands continue to use `--provider <configured-name>` without new runtime-specific flags:

```text
research interrogate W0001 --provider codex-subscription
research verify W0001 --provider claude-subscription
```

## 18. Web experience

Expand Settings with a **Models & providers** section containing two tabs:

- **Local CLIs**;
- **API providers**.

The Local CLIs tab includes:

- a Rescan action;
- installed and unavailable groups;
- runtime name, version, login status, and bounded-mode status;
- model and reasoning selectors populated from the server response;
- Add/Enable, Disable/Remove, and Test actions;
- the configured workspace provider name and priority;
- explicit text that the process is local but model data may leave the workstation;
- the exact server-provided unavailable or privacy reason.

The UI never executes a local binary directly. It invokes capabilities through the daemon. Web and CLI render server decisions and do not duplicate runtime support, safety, or routing rules.

The existing conversation model selector automatically receives configured CLI entries through `provider.list`; no separate conversation-only integration is permitted.

## 19. Privacy, credentials, and logging

- Research Harness never reads, copies, exports, or displays the contents of a CLI credential store.
- Authentication probes report only normalized status and safe guidance.
- No credential is written to `research.yaml`, canonical research files, traces, test fixtures, command arguments, or browser storage.
- CLI providers declare source-text and identifier egress just like HTTP providers.
- Provider test calls obey project privacy policy before process creation.
- Traces record the normalized prompt/response through the existing redaction and retention policy, along with runtime ID, executable version, selected model, protocol family, and latency.
- Raw stdout/stderr may be held in bounded memory for parsing but is not persisted by default.
- Diagnostic logging redacts home paths, tokens, emails, signed URLs, and high-entropy credential-like strings.

## 20. Testing strategy

Implementation follows test-first development. Tests use fake executables or recorded, sanitized transcripts by default; live subscription accounts are opt-in and never required in CI.

### Unit tests

- Registry uniqueness and complete definitions for all seven runtimes.
- Pure argument builders for default/model/reasoning selections.
- Prompt rendering and the absence of research content from argv.
- Environment allow/deny behavior, including removal of API-key variables.
- Executable resolution on POSIX and Windows wrapper paths.
- Version, auth, model-list, and error parsers.
- Event parser fixtures for every supported protocol family.
- Tool/file-write events fail bounded mode.
- Timeout, output-limit, cancellation, and process cleanup behavior.
- Router configuration validation for `kind: local_cli`.
- Egress classification never equates local process location with local inference.

### Contract tests

- Each CLI provider runs the same `ModelRequest` fixture and produces the same validated response schema as HTTP providers.
- Invalid JSON and schema violations fail through the shared structured-output path.
- Provider/model/fingerprint metadata survives unchanged.
- Streaming conversation deltas concatenate to the final answer.

### Capability and integration tests

- Scan is read-only and fault-isolates one broken executable.
- Configure/remove mutate only the intended provider entry through a human-authorized capability.
- Web and CLI receive identical scan, availability, and test results.
- Privacy refusal happens before the fake executable is spawned.
- A configured but logged-out runtime appears unavailable in `provider.list`.
- No silent failover occurs after a subprocess failure.

### Web tests

- Local CLI and API tabs render separately.
- Rescan loading, success, partial failure, and empty states.
- Installed/logged-out/unsafe/version-warning states.
- Model selection, configure, remove, and Test flows.
- External-egress warning is visible before testing or enabling.
- Keyboard and screen-reader behavior for tabs, cards, actions, and status messages.

### Optional live tests

One opt-in test per installed CLI may run a harmless, minimal schema request. It must be explicitly enabled, skip when unavailable, consume no project files, and print no raw model response or credential data on failure.

## 21. Compatibility policy

- A runtime version with recorded fixtures is `verified`.
- A newer unrecorded version is `warning` unless a bounded capability probe proves it compatible.
- A known incompatible version is blocked with upgrade or pin guidance.
- Unknown auth state is distinct from missing auth.
- Fallback model lists are labeled as hints; they do not prove account access.
- Live model results are cached only in memory and include a timestamp and source.
- Parser fixtures retain event structure while replacing arbitrary text, paths, account identifiers, and secrets.

The implementation should record the Open Design source revision used for each ported definition in code comments or fixture metadata so upstream drift can be audited.

## 22. Backward compatibility

- Existing provider kinds and configuration remain valid.
- A workspace without `local_cli` entries behaves exactly as before.
- No runtime is automatically added to `research.yaml` after detection.
- Existing `--provider`, model routing, workflow, Web conversation, privacy, trace, and egress contracts remain the public path.
- Removing the `open-design` checkout from an installed package does not affect runtime behavior because no production import points into the submodule.

## 23. Implementation sequence for the later request

1. Add and pin the Open Design submodule; record the reviewed revision.
2. Add failing registry, configuration, egress, and process-engine tests.
3. Implement the immutable runtime types and unique registry.
4. Implement safe executable resolution, probes, environment filtering, and error classification.
5. Implement bounded spawn/cancel/cleanup and parser interfaces.
6. Port Codex and Claude definitions plus fixtures as the first vertical slice.
7. Connect `CliModelProvider` to the existing router and provider contract.
8. Add capabilities and CLI commands, then verify end-to-end with fake executables.
9. Add Cursor Agent, Amp, DeepSeek Harness, OpenCode, and Pi one at a time, each beginning with recorded failing contract tests.
10. Extend `provider.list`, egress reports, doctor output, traces, and generated API contracts.
11. Build the Web Models & providers settings surface against the shared capabilities.
12. Run focused tests, the full Python suite, Web tests, type checks, lint, build, secret scans, and optional local smoke tests.

No later step may weaken bounded execution merely to make an adapter pass.

## 24. Acceptance criteria

1. `open-design` is a pinned Git submodule at the repository root and is not a runtime dependency.
2. A fresh scan detects all seven supported runtime definitions independently and reports normalized version/auth/model status.
3. A user can configure a detected CLI provider from either Web or `research providers add`, and both paths create the same validated workspace entry.
4. A logged-in user with no Research Harness API key can complete a schema-validated research request through each safely compatible CLI.
5. Existing commands select the configured CLI through `--provider` without domain or workflow branches.
6. Research content is delivered through stdin/RPC, never argv.
7. A CLI provider is represented as external egress unless local inference is positively established.
8. Project privacy policy can prevent the process from spawning.
9. The runtime cannot edit project files or execute arbitrary project tools; a tool/file-write event fails the request.
10. Invalid, partial, or schema-incompatible output never reaches staging or accepted state.
11. Cancellation and timeout terminate the entire process tree and preserve incomplete conversation output according to existing semantics.
12. Web and CLI display identical availability and failure reasons from shared capabilities.
13. Existing HTTP, local-server, and scripted providers continue to pass their contract and integration tests unchanged.
14. Default CI requires no installed third-party CLI, subscription login, API key, or network call.
15. Logs, traces, fixtures, configuration, and UI contain no credential material.

## 25. Implementation request

When implementation is desired, the user can request:

> Implement `docs/superpowers/specs/2026-09-03-subscription-local-cli-providers-design.md` using test-driven development. Do not weaken the bounded-execution or egress requirements.

That later request authorizes implementation; this design document by itself does not.
