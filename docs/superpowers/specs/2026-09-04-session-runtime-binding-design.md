# Session Runtime Binding — Design Specification

**Status:** Architecture approved in conversation on 2026-09-04; ready to be used as the basis of an implementation plan.

**Scope:** Design only. This document does not authorize implementation. It builds on the shipped subscription-backed local CLI providers (`docs/superpowers/specs/2026-09-03-subscription-local-cli-providers-design.md`, ADR-030) and supersedes exactly one sentence of that specification (§5 below).

## 1. Decision summary

A conversation session may be **bound** to a local CLI runtime, a model, and a reasoning level from the conversation composer, without editing `research.yaml`. The binding is stored on the session record by the daemon, is resolved on every send by the same validator and gates a `research.yaml` entry passes, and is shown identically by the Web cockpit and the `research` CLI.

The approved architecture is **a daemon-owned session binding resolved into an in-memory provider entry**. Nothing in the browser decides availability, routability, or wording; nothing new touches the runtime engine, the registry, or the bounded posture rules. A per-message model override keeps precedence over the binding, and clearing the binding returns the session to the project default.

Two alternatives were considered and rejected:

- **Auto-created `research.yaml` entries.** Every composer pick would write project configuration, the entry list would grow with every experiment, and a window without admin rights could not pick at all.
- **Browser-side stickiness.** The daemon would stop being the source of truth for what a session sends to; the choice would be lost across devices and reloads, and a runtime/model/reasoning string syntax would leak into the CLI.

## 2. Goals

1. From the composer, pick a routable runtime (Codex CLI or Claude Code in this release), one of the models the daemon's scan lists for it, and a reasoning level the runtime offers.
2. The pick is sticky for the session: later messages use it until it is changed or cleared; a new session starts from the project default.
3. The pick survives reload and is visible from every window and from the terminal, because the daemon stores it.
4. Every refusal a configured entry would receive applies to a binding, in the same order and with the same sentence: privacy policy, bounded posture, login, version, executable.
5. The terminal can bind, show, and clear a session with the same words the Web shows.
6. Egress is disclosed before a session's first binding to an external destination.
7. Default CI needs no installed CLI, no login, no key, and no network.

## 3. Non-goals

- Binding API-key (HTTP) providers to a session beyond the entry name they already have. An HTTP entry has one model; the picker lists it as it does today.
- A model list for HTTP providers; a per-provider model catalogue for HTTP kinds is a separate decision.
- Persisting a binding into `research.yaml`, or letting a binding change the project default. `research providers add` remains the way to configure the project.
- A per-message reasoning override. Reasoning is part of the binding or of a configured entry; a per-message `model` override uses that entry's reasoning.
- Any change to the runtime registry, the bounded posture rules, the environment allow-list, the parsers, or the process engine.
- Any client-side interpretation of runtime, model, or reasoning identifiers.

## 4. Terminology

- **Entry**: one item of the `providers:` table in `research.yaml`, named, persisted, project-wide.
- **Binding**: a session's stored choice of what answers its messages: either an entry name, or a runtime with a model and a reasoning level. Never persisted in `research.yaml`.
- **Session provider**: the in-memory provider entry the daemon builds from a runtime binding for one call, named `session:<runtime>`; its words on every surface are `session:<runtime>/<model>`, followed by ` (reasoning <level>)` when one is set.
- **Project default**: the entry the router selects for an unconstrained call, in priority order; `provider.list` marks it `default`.
- **Routable runtime**: a runtime whose cached scan reports it installed, logged in with a subscription, provably bounded, and not version-blocked, as defined by the CLI providers specification §10 and §11.

## 5. Relationship to the CLI providers specification

Everything in the 2026-09-03 specification and ADR-030 stays in force: the registry, detection, the bounded posture and its gates, the environment rules, the capability permissions, the CLI commands, the Settings section, and the privacy rules.

One sentence of its §18 is superseded:

> The existing conversation model selector automatically receives configured CLI entries through `provider.list`; no separate conversation-only integration is permitted.

It is replaced by:

> The conversation model selector receives configured entries through `provider.list` and the runtime groups through `provider.cli.scan`. A session may bind to a routable runtime, model, and reasoning level without an entry; the binding is stored by the daemon, resolved through the same validator and gates as an entry, and rendered from daemon words only.

ADR-030's invariants are unchanged. Implementation records a short addendum to ADR-030 naming the session binding as a second, non-persisted way to name a CLI provider, subject to every existing invariant.

## 6. Architecture

```
composer picker ──session.configure──▶ daemon ──validate (RouterProviderConfig)──▶ session record
                                                                                    (defaults.model,
                                                                                     defaults.reasoning)
composer send ───session.send─────────▶ WorkspaceProviders.select
                                            1. per-message `model`?  ─▶ narrow to it
                                            2. session binding?      ─▶ entry: narrow to it
                                                                        runtime: build session provider,
                                                                                 validate, append
                                            3. project default       ─▶ priority order
                                        ──▶ privacy policy ──▶ run-time runtime gate ──▶ spawn
```

Layering rules hold as before: `providers/` never imports `cli/`, `server/`, `capabilities/`, or `workspace/`; `capabilities/` is the only mutation surface; the domain treats model identity as opaque labels. The interpretation of the `local_cli:<runtime>` provider name lives in `conversation/send.py`'s selector and nowhere else.

## 7. Data model

`SessionDefaults` (in `domain/conversation.py`) already carries `model: ModelIdentity | None`, set at session creation and unused on the send path. It gains one field and a documented convention:

```python
class SessionDefaults(DomainModel):
    model: ModelIdentity | None = None
    mode: str | None = None
    token_budget: int | None = Field(default=None, ge=0)
    reasoning: str | None = None
    """The runtime's own effort name for a runtime binding; None otherwise."""
```

`ModelIdentity` is unchanged. Its two shapes on a session are:

| binding | `provider` | `model` | `reasoning` |
|---|---|---|---|
| runtime | `local_cli:<runtime id>` | model id from the scan, or `default` | a value from the runtime's `reasoning_choices`, or `None` for the runtime's default |
| entry | `entry` | the entry's name in `research.yaml` | `None` |
| none | `None` | | `None` |

The domain validates only shape: `provider` and `model` are non-empty strings; `reasoning` is `None` unless `provider` starts with `local_cli:`. Which runtimes, models, and reasoning levels exist is decided by the capability layer at binding time and by the routing layer at send time.

A session created with a `model` argument today stores it as an entry binding (`provider = "entry"`); this is the one migration in §15.

## 8. Capability contract

### `session.configure`

Permission `MUTATE`, which the registry treats as human-only, like `session.rename` (`capabilities/registry.py` derives `human_only` from `MUTATE`/`ADMIN`). Request:

```python
class ConfigureSessionRequest(CapabilityRequest):
    session: ConversationSessionId
    runtime: str | None = None      # a registry runtime id
    model: str | None = None        # required with runtime; a scan model id or "default"
    reasoning: str | None = None    # only with runtime
    entry: str | None = None        # an entry name in research.yaml
    clear: bool = False
```

Exactly one of `runtime`, `entry`, `clear` is given; `model` is required with `runtime`; `reasoning` is allowed only with `runtime`. The handler:

1. Loads the session or refuses with the existing not-found error.
2. For `entry`: refuses unless an enabled entry of that name exists in `research.yaml`, with the same sentence a stale per-message `model` gets today.
3. For `runtime`: builds `RouterProviderConfig(kind="local_cli", name="session:<runtime>", runtime=…, model=…, reasoning=…)` and lets its validator refuse an unknown runtime, a runtime with no proven bounded posture, or a reasoning level the runtime does not offer, with the sentences `research providers add` prints. It then reads the cached scan for that runtime and refuses a model that is neither `default` nor in the scan's `models` list, with `"<runtime> does not list model '<model>'; run research providers scan"`. A runtime that is installed but not routable right now is **accepted** at binding time, so a researcher can bind a session before logging in; the send refuses with the scan's sentence until the runtime is routable.
4. Refuses a **private** session a runtime binding, with the send path's own private-egress sentence (`conversation/send.py::private_egress_sentence`). Every CLI runtime is external egress, so a runtime binding on a private session would leave a session that looks configured and can never answer. The check comes *after* the entry is validated, in the order the send path refuses, so an invalid binding is still refused in the entry's own words first. An **entry** binding is unaffected: an entry may name a local provider.
5. Stores the binding on the session record under the session lock and answers with the updated `SessionView`.

For `clear`, it stores `model = None`, `reasoning = None`.

Visibility is decided at creation and **no capability changes it afterwards**: `session.create` (and `research chat new`) defaults to `private`, and there is no `session.set_visibility`. A session that is to use a bound runtime is therefore created as a project session — `research chat new --visibility project` — and the same is true of the Web, whose New session flow sends a title and nothing else today.

The response is the existing `SessionView`, whose `defaults` now carry the binding. `session.get`, `session.list`, and `session.search` return the same record and need no change beyond the new field.

### `provider.cli.scan`

Unchanged. The composer reads runtime groups, models, `model_source`, `reasoning_choices`, and every reason from it, through the daemon, with the cache the Settings section already uses.

### `session.send` and `session.retry`

Unchanged in shape. Their `model` field keeps its meaning as a per-message override. A retry without `model` resolves the binding as the session has it at retry time, not at the time of the original message.

## 9. Routing resolution and gates

Resolution lives in `WorkspaceProviders.select` (`conversation/send.py`), the one place a send picks a provider. Precedence:

1. an explicit per-message `model` (entry name or tag), unchanged;
2. the session binding;
3. the project default: the router's priority order.

For an **entry binding**, step 2 narrows the router to that entry, exactly as a per-message `model` does. A binding to an entry that has since been removed or disabled fails with the existing "no provider named … in research.yaml" sentence.

For a **runtime binding**, the selector builds one `RouterProviderConfig` of kind `local_cli` with name `session:<runtime>`, the bound model and reasoning, priority `0` and `enabled: true`, validates it through the same validator `research.yaml` goes through, appends it to a copy of the routing table for this call only, and narrows to it. The call then passes the gates every entry passes, in the same order:

1. the privacy policy, so `external_models: disabled` refuses before any process exists;
2. the run-time runtime gate in `CliModelProvider._run`, which reads the cached scan and refuses with `bounded_mode_unsupported`, `version_blocked`, `login_missing`, or `executable_missing` and the scan's own sentence, before the prompt is rendered.

No gate is added and none is bypassed. The `availability` injection point on `CliModelProvider` is never passed here.

The transcript, the receipt, and the run record carry the provider label `session:<runtime>` with the bound model, so a reader can tell a session-bound answer from one routed through a configured entry; the trace keeps the adapter's own name, `local_cli:<runtime>`, with the same model, because the trace writer records the adapter, not the entry. Reasoning travels the way the adapter already takes it: `--effort` for Claude Code, `-c model_reasoning_effort="…"` for Codex, screened by the run-time argv check.

## 10. Web experience

The composer's `ModelSelector` becomes a grouped selector. Groups, in order:

1. **Configured entries**: the `provider.list` catalogue as today, each row `<entry>/<model>` with the daemon's availability and reason.
2. **One group per CLI runtime the scan lists as installed**, titled with the daemon's runtime name and version, listing the scan's models with the daemon's `model_source` word (live or fallback). A runtime the scan reports as not routable is one disabled row carrying the scan's `unavailable_reason`, so the picker never hides why a runtime is absent. Runtimes the scan reports as not installed are omitted.

Picking a runtime model shows a reasoning control beside the selector, populated from that runtime's `reasoning_choices`, defaulting to the runtime's own default (no reasoning sent). Picking anything calls `session.configure`; the selector value is then read back from the session record returned by the daemon, never from local state, so a second window or a reload shows the same choice. Clearing calls `session.configure` with `clear`.

The selector shows the current binding as its value: the entry row for an entry binding, the runtime model row for a runtime binding, and the project default row otherwise, marked as the daemon's `default`.

**Disclosure.** Before a session's first binding to an external destination, the composer shows the daemon's egress sentence for that runtime, the `notice` `provider.cli.scan` returns, and proceeds only after the researcher confirms. The confirmation is remembered per session in the browser only as a convenience; the daemon's receipt panel keeps showing each message's egress class as today, so the disclosure is not the only place the destination is visible.

**Read-only windows.** A window without `canMutate` keeps today's selector behaviour exactly: a pick sets the per-message `model` and changes nothing durable. Its runtime groups are shown disabled with the session's mutation-blocked reason. A mutating window's pick binds the session; there is no separate per-message control in the composer.

**Session list.** Each session row shows its binding in the fixed format every surface uses, composed from the record's fields: `session:codex/gpt-5.5 (reasoning high)`, `entry codex-sub`, or nothing for the project default. The CLI composes the same strings from the same fields; a test on each side pins them.

The badge and state mappers of the Settings section are reused; no new client rule decides availability, routability, or wording. Components come from `@research-harness/design`; token and contrast checks apply as for the Settings section.

## 11. CLI experience

The parity rule requires a terminal command for every capability. The `session.*` capabilities live under `research chat` (the `research session` name belongs to the working-session summary), so the command is:

```console
research chat configure CS0001 --runtime codex --model gpt-5.5 --reasoning high
research chat configure CS0001 --entry codex-sub
research chat configure CS0001 --clear
```

Output: the egress sentence for the runtime before the change, then the resulting binding, as `bound to: session:codex/gpt-5.5 (reasoning high)`, `bound to: entry codex-sub`, or `bound to: project default`. Exit non-zero on refusal with the daemon's sentence. `--json` prints the `SessionView`.

`research chat list` and `research chat show` print the binding with the same words. `research doctor` is unchanged: a session binding is not project configuration.

## 12. Privacy, credentials, and logging

- A binding names a runtime, a model, and an effort level; none of them is a secret. The session record gains no credential material.
- The egress invariant of the CLI providers specification §4 holds: a session provider is external egress with the runtime's declared host; it is never `local`.
- The privacy policy is asked before the runtime on every send, including bound ones; a refusal raises before a run exists and the session gains nothing.
- A private session may not be bound to a runtime at all. `session.configure` refuses it at bind time with the send path's private-egress sentence, so the refusal arrives where the choice was made rather than on the first send. An entry binding is unaffected.
- Visibility is a creation-time decision and no capability changes it, so the way to use a bound runtime is `research chat new --visibility project` on a new conversation — which is exactly what the private-egress sentence already tells the researcher to do.
- The transcript, the receipt, and the run record carry `session:<runtime>` with the bound model; the trace keeps the adapter's own `local_cli:<runtime>`, because the trace writer records the adapter rather than the entry (§9, §14). All four already exclude prompts, tokens, and paths.
- No new log line, diagnostic, or fixture may contain a token, a credential path, a home path, or an e-mail.

## 13. Error model

All errors are the existing `CapabilityError` or the existing CLI provider diagnostics; none is new.

| situation | when | sentence |
|---|---|---|
| unknown runtime id | `session.configure` | the router validator's unknown-runtime sentence |
| runtime with no proven posture | `session.configure` | the router validator's "runtime '…' has no proven bounded (no-tools, read-only) mode and cannot be configured" |
| reasoning the runtime does not offer | `session.configure` | the router validator's reasoning-choices sentence, which lists the runtime's choices |
| model not in the scan's list | `session.configure` | `"<runtime> does not list model '<model>'; run research providers scan"` |
| entry missing or disabled | `session.configure` and send | "no provider named '…' in research.yaml (have: …)" |
| window without MUTATE | `session.configure` | the registry's permission refusal |
| policy refuses external models | send | the existing policy refusal, before any process |
| runtime not routable right now | send | `bounded_mode_unsupported` / `version_blocked` / `login_missing` / `executable_missing` with the scan's sentence |

## 14. Testing strategy

All offline, with the fake CLI under `tests/fixtures/cli/fakes.py`; the real `codex`/`claude` are never run in default CI.

**Domain and capability**
- `SessionDefaults` accepts the three shapes of §7 and refuses `reasoning` without a runtime provider.
- `session.configure` stores a runtime binding, an entry binding, and a clear; refuses an unknown runtime, a posture-`none` runtime, an unlisted model, an unoffered reasoning level, and a missing entry, each with the sentence of §13; accepts an installed but logged-out runtime.
- The permission table marks it `MUTATE`, which the registry treats as human-only, so an agent host is refused it on every transport; the parity test maps it to `research chat configure`.

**Routing**
- A bound session with no per-message `model` spawns the fake with the bound model and reasoning in argv; the transcript records `session:codex` with the bound model, and the trace records `local_cli:codex`, because the trace writer records the adapter rather than the entry (§9).
- A per-message `model` wins over the binding.
- A binding whose runtime the fake now reports logged out fails before any run process with `login_missing` and the scan's sentence; `fake.runs() == []`.
- `external_models: disabled` refuses a bound send before any spawn.
- An entry binding to a removed entry fails like a stale per-message name.
- A retry without `model` follows the binding at retry time.

**HTTP and MCP parity**
- `session.configure` answers identically in process and over the daemon, in the existing parity harness.

**Web**
- The grouped selector renders configured entries and one group per installed runtime from the fixtures, with the disabled row and reason for a non-routable runtime and no row for an uninstalled one.
- Picking a runtime model calls `session.configure` with the expected body and the selector value follows the returned session record.
- The reasoning control lists the runtime's `reasoning_choices`.
- The egress confirmation appears before the first external binding of a session and not again for the same session.
- A read-only window sees a disabled picker with the daemon's reason and can still send with a per-message override.
- The session list shows the binding words.
- Axe, token, and contrast checks pass.

**Live**
- The optional live smoke is unchanged: the same provider code answers a bound request.

## 15. Compatibility and migration

- Sessions written before this change have `defaults.model` either `None` or a `ModelIdentity` naming an entry with the adapter's own provider name. On first read, a `ModelIdentity` whose `provider` is neither `entry` nor `local_cli:*` is treated as an entry binding on its `model` value; nothing is rewritten until the session is next configured.
- The `SessionDefaults` schema gains an optional field with a default. The repository has no object schema-version convention beyond the constant every canonical object carries, and an additive optional field loads every existing session file, so no version bump ships with this change.
- Generated artifacts are regenerated, never hand-edited: `docs/guide/capabilities.md`, `docs/guide/cli-reference.md`, `web/capabilities.json`, `web/openapi.json`, `web/src/api/capabilities.gen.ts`, and the Web DTO for `SessionDefaults`.
- The acceptance matrix and ROADMAP gain rows for the criteria in §16; ADR-030 gains the addendum of §5.

## 16. Acceptance criteria

1. A session can be bound to a routable runtime and model from the composer without editing `research.yaml`, and the binding survives reload and a second window.
2. A bound session's messages route through that runtime and model with the chosen reasoning, and the transcript names `session:<runtime>/<model>`.
3. Every refusal a configured entry would get applies to a binding, in the same order and with the same sentence: policy, posture, login, version, executable.
4. A per-message override wins over the binding, and clearing the binding returns the session to the project default.
5. Web and CLI can both bind, show, and clear a binding, and show identical words in the fixed format of §4.
6. The picker's runtime groups, model lists, reasoning lists, and reasons are the daemon's; no client code decides availability.
7. Egress is disclosed before the first external binding of a session.
8. Default CI needs no installed CLI, login, key, or network, and no credential material appears in any new fixture, message, or log line.

## 17. Implementation request

This document authorizes no implementation. Implementation begins only with an explicit request; when it comes, the plan follows the sequence: domain field and migration; `session.configure` with its tests and parity; routing resolution and gates; CLI command and generated docs; Web selector, disclosure, and session list; acceptance matrix, ROADMAP, and the ADR addendum.
