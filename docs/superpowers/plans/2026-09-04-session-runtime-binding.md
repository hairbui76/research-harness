# Session Runtime Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a conversation session be bound, from the composer or the terminal, to a routable CLI runtime, model, and reasoning level without editing `research.yaml`, with the daemon storing and resolving the binding through the same validator and gates a configured entry passes.

**Architecture:** A `SessionDefaults.reasoning` field plus a fixed convention for `defaults.model` (`local_cli:<runtime>` or `entry`) carries the binding on the session record. A new `session.configure` capability validates and stores it. `WorkspaceProviders.select` resolves the binding on send by appending an in-memory `local_cli` entry named `session:<runtime>` to the routing table for that call, so every existing gate applies unchanged. The Web composer gets a grouped `ModelSelector` fed by `provider.list` and `provider.cli.scan`; `research chat configure` keeps CLI parity.

**Tech Stack:** Python 3.12, Pydantic v2, Typer, pytest with the fake CLI under `tests/fixtures/cli/fakes.py`; React 18, TypeScript, vitest, `@research-harness/design`.

**Spec:** `docs/superpowers/specs/2026-09-04-session-runtime-binding-design.md` (read it first; §5 lists what it supersedes; the rulings below refine §9, §10, §11, §15 after code exploration and are mirrored in the spec).

## Global Constraints

- Default tests never spawn the real `codex`/`claude`: only `tests/fixtures/cli/fakes.py`; never set `RESEARCH_HARNESS_LIVE_CLI_TESTS`.
- No token, credential path, home path, or e-mail in any message, fixture, log line, or test name.
- Layering: `providers/` never imports `cli/`, `server/`, `capabilities/`, or `workspace/`; `workspace/` never imports `providers/`; `capabilities/` is the only mutation surface; `domain/` never branches on the values of `ModelIdentity` beyond the shape rule in spec §7.
- Every gate a `research.yaml` entry passes applies to a binding, in the same order and with the same sentence: privacy policy, then the run-time runtime gate (`bounded_mode_unsupported`, `version_blocked`, `login_missing`, `executable_missing`). No new gate, no bypass; the `availability` injection point of `CliModelProvider` is never passed.
- Python gates: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` (strict), line length 100. Web gates: `pnpm --filter research-harness-web typecheck|lint|test|build`, `pnpm --filter @research-harness/design test`, token and contrast checks clean.
- Generated files are regenerated, never edited by hand: `docs/guide/capabilities.md` (`uv run python docs/guide/gen_capabilities.py`), `docs/guide/cli-reference.md` (`uv run python docs/guide/gen_cli_reference.py`), `web/capabilities.json` and `web/openapi.json` (`uv run python web/scripts/export_backend_json.py`, then revert the fixture files under `web/src/test/fixtures/` whose only changes are temp paths, timestamps, or run ids), `web/src/api/capabilities.gen.ts` and `types.gen.ts` (`cd web && pnpm gen:types`).
- The daemon decides every state, reason, list, and sentence. Client code composes labels only from record fields in the fixed formats below and never decides availability or routability.
- TDD per task: failing test, red run recorded, implementation, green run, commit. Commit trailers:
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_018NVxnVP19ZXR3cUTi9fvuK`.

## Rulings that refine the spec (mirrored in the spec text)

1. **CLI command name.** The `session.*` capabilities live under `research chat …` (the `research session` name is taken by the working-session summary). The command is `research chat configure`; the parity row is `("chat", "configure")`.
2. **Where `session:<runtime>` appears.** `ProviderProfile.provider` (transcript `Message.model`, the receipt, the run record's `provider` input) carries `session:<runtime>`; the trace keeps the adapter's own name `local_cli:<runtime>`, because the trace writer records `provider.name` of the adapter. Both carry the bound model.
3. **No schema-version bump.** `domain.base.SCHEMA_VERSION` has never been bumped and there is no multi-version reader; an additive optional field with a default loads every existing session file, so `SessionDefaults.reasoning` ships without a bump. The migration of pre-binding records is the `binding_of` rule: a provider that is neither `entry` nor `local_cli:*` is **no binding** — such a record was never read on the send path, so it bound nothing then and binds nothing now, and the session sends through the project default rather than failing on a name that never named a `research.yaml` entry.
4. **Binding words are a fixed format composed from record fields.** `session:<runtime>/<model>` plus ` (reasoning <level>)` when set, `entry <name>`, or `project default`. The CLI composes it in Python (`RuntimeBinding.words` / `EntryBinding.words`), the Web composes the same strings in `mappers.ts`; a test on each side pins the strings.
5. **Read-only windows.** A window without `canMutate` keeps today's selector behaviour exactly (a pick sets the per-message `model`); its runtime groups are shown disabled with the session's mutation-blocked reason. A mutating window's pick binds the session and there is no separate per-message control.
6. **Composer option ids.** A runtime model row has the view key `runtime:<runtime id>:<model id>`; the Web builds and parses that key itself. It is a view key, not a daemon semantic; the daemon receives `runtime` and `model` separately.
7. **Model-list check env.** `ConversationService.configure` reads the cached scan with `detect_cached(get_runtime(runtime), env=os.environ)`, the same environment `build_router` uses on send.

## File structure

| File | Responsibility |
|---|---|
| `src/research_harness/domain/conversation.py` | `SessionDefaults.reasoning` and its shape rule |
| `src/research_harness/conversation/binding.py` (new) | `EntryBinding`, `RuntimeBinding`, `binding_of`, identities, words, `SESSION_LABEL_PREFIX` |
| `src/research_harness/conversation/service.py` | `configure(...)`; `create` stores `provider="entry"` |
| `src/research_harness/capabilities/conversation.py` | `ConfigureSessionRequest`, `configure_session`, spec entry |
| `src/research_harness/conversation/send.py` | `ProviderSelector.select(..., defaults=)`, resolution in `WorkspaceProviders.select`, `_prepare` passes the record's defaults |
| `src/research_harness/cli/commands/session.py` | `chat configure`; binding words in `list`/`show` |
| `design/src/conversation/models.ts`, `ModelSelector/`, `SessionList/` | grouped selector, nullable `contextTokens`, `SessionSummary.binding` |
| `web/src/api/{dto,client}.ts` | `SessionDefaults.reasoning`, `ConfigureSessionRequest`, `configureSession` |
| `web/src/views/conversation/{useModels,useSessions,mappers,ComposerPane,SessionListPane}` | grouped options, binding, reasoning control, disclosure, session words |
| `web/src/test/fixtures/conversation/sessions.json` | a bound session |
| `docs/…` | guide, web.md, acceptance matrix, ROADMAP, ADR-030 addendum |

## Waves

- **Wave 1 (parallel):** Task 1 (domain, binding, service), Task 5 (design system).
- **Wave 2 (parallel, after Task 1):** Task 2 (capability + parity + regen), Task 3 (routing).
- **Wave 3 (parallel, after Task 2; Task 6 also after Task 5):** Task 4 (CLI), Task 6 (Web app).
- **Wave 4 (after all):** Task 7 (docs and status).
- **Task 8:** PM gates, final review, push to `main`.

---

### Task 1: Domain field, binding module, service `configure`

**Files:**
- Modify: `src/research_harness/domain/conversation.py:291-297` (`SessionDefaults`)
- Create: `src/research_harness/conversation/binding.py`
- Modify: `src/research_harness/conversation/service.py:123-149` (`create`), add `configure`
- Test: `tests/unit/domain/test_session_defaults.py` (new), `tests/unit/conversation/test_binding.py` (new), `tests/contract/conversation/test_session_configure.py` (new)

**Interfaces:**
- Consumes: `ConversationStore.update_session(session, *, defaults=SessionDefaults)` (`workspace/conversations.py:210-233`); `RouterProviderConfig` (`providers/models/router.py:359-431`); `detect_cached` (`providers/cli/detection.py:339`); `get_runtime` (`providers/cli/registry.py`); `DEFAULT_CACHE` (`providers/cli/detection.py`); `CapabilityError` (`domain/errors.py:67`); `DomainModel.touch(**updates)`.
- Produces: `SessionDefaults.reasoning: str | None`; module `research_harness.conversation.binding` with `ENTRY_PROVIDER = "entry"`, `RUNTIME_PROVIDER_PREFIX = "local_cli:"`, `SESSION_LABEL_PREFIX = "session:"`, `EntryBinding(name)`, `RuntimeBinding(runtime, model, reasoning)` with `.label` and `.words`, `Binding = EntryBinding | RuntimeBinding`, `binding_of(defaults) -> Binding | None`, `binding_words(defaults) -> str`, `runtime_identity(runtime, model) -> ModelIdentity`, `entry_identity(name) -> ModelIdentity`; `ConversationService.configure(session, *, runtime=None, model=None, reasoning=None, entry=None, clear=False) -> ConversationSession`.

- [ ] **Step 1: Write the failing domain test**

`tests/unit/domain/test_session_defaults.py`:

```python
"""`SessionDefaults` carries a binding in one of three shapes (binding spec §7)."""

import pytest
from pydantic import ValidationError

from research_harness.domain.conversation import ModelIdentity, SessionDefaults


def test_a_runtime_binding_carries_a_reasoning_level() -> None:
    defaults = SessionDefaults(
        model=ModelIdentity(provider="local_cli:codex", model="gpt-5.5"), reasoning="high"
    )
    assert defaults.reasoning == "high"


def test_an_entry_binding_carries_no_reasoning() -> None:
    defaults = SessionDefaults(model=ModelIdentity(provider="entry", model="codex-sub"))
    assert defaults.reasoning is None


def test_reasoning_without_a_runtime_binding_is_refused() -> None:
    with pytest.raises(ValidationError, match="runtime binding"):
        SessionDefaults(model=ModelIdentity(provider="entry", model="codex-sub"), reasoning="high")
    with pytest.raises(ValidationError, match="runtime binding"):
        SessionDefaults(reasoning="high")


def test_an_old_record_without_the_field_still_loads() -> None:
    defaults = SessionDefaults.model_validate(
        {"model": {"provider": "local", "model": "local-small"}, "mode": None, "token_budget": 8000}
    )
    assert defaults.reasoning is None and defaults.token_budget == 8000
```

- [ ] **Step 2: Run it red**

Run: `uv run pytest tests/unit/domain/test_session_defaults.py -q`
Expected: FAIL — `reasoning` is an unexpected field (`extra="forbid"`).

- [ ] **Step 3: Add the field and the shape rule**

In `src/research_harness/domain/conversation.py`, replace `SessionDefaults`:

```python
RUNTIME_PROVIDER_PREFIX = "local_cli:"
"""A `defaults.model` whose provider starts with this names a runtime binding (spec §7)."""


class SessionDefaults(DomainModel):
    """What a new message in this session uses unless the composer overrides it."""

    model: ModelIdentity | None = None
    mode: str | None = None
    """Opaque composer mode label (a role or task preset), never interpreted here."""
    token_budget: int | None = Field(default=None, ge=0)
    reasoning: str | None = None
    """The runtime's own effort name for a runtime binding; `None` otherwise."""

    @model_validator(mode="after")
    def _reasoning_needs_a_runtime_binding(self) -> SessionDefaults:
        # The one shape rule the domain enforces (binding spec §7): what runtimes, models
        # and effort names exist is decided by the capability and routing layers.
        if self.reasoning is not None and not (
            self.model is not None and self.model.provider.startswith(RUNTIME_PROVIDER_PREFIX)
        ):
            raise ValueError("reasoning is only for a runtime binding (provider local_cli:<id>)")
        return self
```

`model_validator` is already imported in that module (used by `ConversationSession`).

- [ ] **Step 4: Run it green**

Run: `uv run pytest tests/unit/domain/test_session_defaults.py -q` — Expected: 4 passed.

- [ ] **Step 5: Write the failing binding test**

`tests/unit/conversation/test_binding.py`:

```python
"""What a session's `defaults.model` means (binding spec §7, §9, §15)."""

from research_harness.conversation.binding import (
    EntryBinding,
    RuntimeBinding,
    binding_of,
    binding_words,
    entry_identity,
    runtime_identity,
)
from research_harness.domain.conversation import ModelIdentity, SessionDefaults


def test_a_runtime_binding_names_the_runtime_model_and_reasoning() -> None:
    defaults = SessionDefaults(model=runtime_identity("codex", "gpt-5.5"), reasoning="high")
    binding = binding_of(defaults)
    assert binding == RuntimeBinding(runtime="codex", model="gpt-5.5", reasoning="high")
    assert binding.label == "session:codex"
    assert binding.words == "session:codex/gpt-5.5 (reasoning high)"
    assert binding_words(SessionDefaults(model=runtime_identity("claude", "default"))) == (
        "session:claude/default"
    )


def test_an_entry_binding_names_the_entry() -> None:
    binding = binding_of(SessionDefaults(model=entry_identity("codex-sub")))
    assert binding == EntryBinding(name="codex-sub")
    assert binding.words == "entry codex-sub"


def test_no_binding_means_the_project_default() -> None:
    assert binding_of(SessionDefaults()) is None
    assert binding_words(SessionDefaults()) == "project default"


def test_a_record_written_before_bindings_is_an_entry_binding_on_its_model_value() -> None:
    # `ConversationService.create` used to store provider == model == the entry name.
    old = SessionDefaults(model=ModelIdentity(provider="fast", model="fast"))
    assert binding_of(old) == EntryBinding(name="fast")
```

- [ ] **Step 6: Run it red**

Run: `uv run pytest tests/unit/conversation/test_binding.py -q` — Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 7: Create the binding module**

`src/research_harness/conversation/binding.py`:

```python
"""What a session's `defaults.model` means for routing (binding spec §7, §9, §15).

The domain stores two opaque labels; this module is the one place that reads them. A
provider of `local_cli:<runtime>` is a runtime binding, `entry` is an entry binding, and any
other provider is a record written before bindings existed, when `create` stored the
adapter's own name in both fields: it is an entry binding on its `model` value.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_harness.domain.conversation import (
    RUNTIME_PROVIDER_PREFIX,
    ModelIdentity,
    SessionDefaults,
)

ENTRY_PROVIDER = "entry"
SESSION_LABEL_PREFIX = "session:"
PROJECT_DEFAULT_WORDS = "project default"


@dataclass(frozen=True, slots=True)
class EntryBinding:
    """The session sends through one named `research.yaml` entry."""

    name: str

    @property
    def words(self) -> str:
        return f"entry {self.name}"


@dataclass(frozen=True, slots=True)
class RuntimeBinding:
    """The session sends through a runtime and model with no `research.yaml` entry."""

    runtime: str
    model: str
    reasoning: str | None

    @property
    def label(self) -> str:
        """The in-memory entry's name, and the transcript's provider label."""
        return f"{SESSION_LABEL_PREFIX}{self.runtime}"

    @property
    def words(self) -> str:
        base = f"{self.label}/{self.model}"
        return base if self.reasoning is None else f"{base} (reasoning {self.reasoning})"


Binding = EntryBinding | RuntimeBinding


def binding_of(defaults: SessionDefaults) -> Binding | None:
    identity = defaults.model
    if identity is None:
        return None
    if identity.provider.startswith(RUNTIME_PROVIDER_PREFIX):
        return RuntimeBinding(
            runtime=identity.provider[len(RUNTIME_PROVIDER_PREFIX) :],
            model=identity.model,
            reasoning=defaults.reasoning,
        )
    return EntryBinding(name=identity.model)


def binding_words(defaults: SessionDefaults) -> str:
    """The fixed wording every surface prints for a session's binding (plan ruling 4)."""
    binding = binding_of(defaults)
    return PROJECT_DEFAULT_WORDS if binding is None else binding.words


def runtime_identity(runtime: str, model: str) -> ModelIdentity:
    return ModelIdentity(provider=f"{RUNTIME_PROVIDER_PREFIX}{runtime}", model=model)


def entry_identity(name: str) -> ModelIdentity:
    return ModelIdentity(provider=ENTRY_PROVIDER, model=name)
```

- [ ] **Step 8: Run it green**

Run: `uv run pytest tests/unit/conversation/test_binding.py -q` — Expected: 4 passed.

- [ ] **Step 9: Write the failing service test**

`tests/contract/conversation/test_session_configure.py`. Reuse the fake `codex` fixture shape from `tests/e2e/test_cli_providers_commands.py:47-62` (copy the fixture; it installs the fake, sets `PATH` and `HOME`, clears `DEFAULT_CACHE`) and the `ctx` fixture from `tests/contract/capabilities/conftest.py` (a `CapabilityContext` over a temp workspace). The `HELP` text and `lines()` helper come from the same e2e module; copy them rather than importing from `tests/e2e`.

```python
"""`ConversationService.configure`: a binding is validated like an entry (binding spec §8)."""

from __future__ import annotations

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.conversation.binding import EntryBinding, RuntimeBinding, binding_of
from research_harness.conversation.service import ConversationService
from research_harness.domain.errors import CapabilityError
from tests.fixtures.cli.fakes import FakeCli


def test_a_runtime_binding_is_stored_with_its_model_and_reasoning(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = service.create("Latency study")

    record = service.configure(session.id, runtime="codex", model="gpt-5.5", reasoning="high")

    assert binding_of(record.defaults) == RuntimeBinding("codex", "gpt-5.5", "high")
    assert service.store.get_session(session.id).defaults == record.defaults, "durable"
    assert codex.runs() == [], "binding never sends a request"


def test_default_model_and_no_reasoning_are_accepted(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = service.create("x")
    record = service.configure(session.id, runtime="codex", model="default")
    assert binding_of(record.defaults) == RuntimeBinding("codex", "default", None)


def test_a_runtime_with_no_proven_posture_is_refused_with_the_entry_sentence(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = service.create("x")
    with pytest.raises(CapabilityError, match="has no proven bounded"):
        service.configure(session.id, runtime="pi", model="default")


def test_an_unknown_runtime_an_unlisted_model_and_an_unoffered_reasoning_are_refused(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = service.create("x")
    with pytest.raises(CapabilityError, match="runtime"):
        service.configure(session.id, runtime="nope", model="default")
    with pytest.raises(CapabilityError, match="does not list model 'gpt-9'"):
        service.configure(session.id, runtime="codex", model="gpt-9")
    with pytest.raises(CapabilityError, match="reasoning 'max'"):
        service.configure(session.id, runtime="codex", model="gpt-5.5", reasoning="max")


def test_an_installed_but_logged_out_runtime_can_still_be_bound(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    codex.write_script(
        {
            **codex.script(),
            "probes": [
                {"args": ["login", "status"], "stdout": "Not logged in\n", "exit": 1},
                *[p for p in codex.script()["probes"] if p["args"] != ["login", "status"]],
            ],
        }
    )
    from research_harness.providers.cli.detection import DEFAULT_CACHE

    DEFAULT_CACHE.clear()
    service = ConversationService(ctx)
    session = service.create("x")
    record = service.configure(session.id, runtime="codex", model="gpt-5.5")
    assert binding_of(record.defaults) == RuntimeBinding("codex", "gpt-5.5", None)


def test_an_entry_binding_needs_an_enabled_entry(ctx: CapabilityContext) -> None:
    ctx.repo.update_providers(
        [
            {
                "name": "fast",
                "kind": "openai",
                "model": "gpt-5.4-mini",
                "api_key_env": "OPENAI_API_KEY",
            }
        ]
    )
    service = ConversationService(ctx)
    session = service.create("x")
    assert binding_of(service.configure(session.id, entry="fast").defaults) == EntryBinding("fast")
    with pytest.raises(CapabilityError, match="no provider named 'slow'"):
        service.configure(session.id, entry="slow")


def test_clear_returns_the_session_to_the_project_default(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = service.create("x", token_budget=4000)
    service.configure(session.id, runtime="codex", model="gpt-5.5", reasoning="high")
    record = service.configure(session.id, clear=True)
    assert record.defaults.model is None and record.defaults.reasoning is None
    assert record.defaults.token_budget == 4000, "other defaults are kept"


def test_exactly_one_target_is_required(ctx: CapabilityContext) -> None:
    service = ConversationService(ctx)
    session = service.create("x")
    with pytest.raises(CapabilityError, match="exactly one of"):
        service.configure(session.id)
    with pytest.raises(CapabilityError, match="exactly one of"):
        service.configure(session.id, entry="fast", clear=True)
    with pytest.raises(CapabilityError, match="model is required"):
        service.configure(session.id, runtime="codex")


def test_create_stores_a_model_argument_as_an_entry_binding(ctx: CapabilityContext) -> None:
    session = ConversationService(ctx).create("x", model="fast")
    assert binding_of(session.defaults) == EntryBinding("fast")
```

If `ctx.repo.update_providers` takes `RouterProviderConfig`-shaped dicts with a different kind name for the OpenAI adapter, use the kind `tests/integration/conversation/test_send_streaming_selection.py` uses for its providers table.

- [ ] **Step 10: Run it red**

Run: `uv run pytest tests/contract/conversation/test_session_configure.py -q` — Expected: FAIL, `configure` does not exist.

- [ ] **Step 11: Implement `configure` and adjust `create`**

In `src/research_harness/conversation/service.py`, change `create` to store an entry binding, and add `configure`:

```python
    def create(self, title: str, *, visibility=Visibility.PRIVATE, model: str | None = None,
               mode: str | None = None, token_budget: int | None = None) -> ConversationSession:
        """Open a session. Private by default: conversation is local working context."""
        from research_harness.conversation.binding import entry_identity

        identity = None if model is None else entry_identity(model)
        defaults = SessionDefaults(model=identity, mode=mode, token_budget=token_budget)
        return self._store.create_session(
            title=title,
            provenance=self._ctx.provenance(workflow="session"),
            visibility=visibility,
            defaults=defaults,
        )

    def configure(
        self,
        session: ConversationSessionId,
        *,
        runtime: str | None = None,
        model: str | None = None,
        reasoning: str | None = None,
        entry: str | None = None,
        clear: bool = False,
    ) -> ConversationSession:
        """Bind a session to a runtime and model, or to an entry, or clear it (spec §8).

        A runtime binding is validated exactly as a `research.yaml` entry would be, then
        checked against the cached scan's model list. An installed runtime that is not
        routable right now is accepted: the send refuses with the scan's sentence until it
        is. Nothing here writes `research.yaml` or sends a request.
        """
        import os

        from pydantic import ValidationError

        from research_harness.conversation.binding import entry_identity, runtime_identity
        from research_harness.providers.models.router import RouterConfig, RouterProviderConfig

        chosen = sum((runtime is not None, entry is not None, clear))
        if chosen != 1:
            raise CapabilityError("give exactly one of runtime, entry, or clear")
        if runtime is None and (model is not None or reasoning is not None):
            raise CapabilityError("model and reasoning are only for a runtime binding")
        record = self._store.get_session(session)
        if clear:
            defaults = record.defaults.touch(model=None, reasoning=None)
            return self._store.update_session(session, defaults=defaults)
        if entry is not None:
            table = RouterConfig.model_validate({"providers": list(self._ctx.repo.config.providers)})
            names = [item.name for item in table.providers if item.enabled]
            if entry not in names:
                known = ", ".join(sorted(names)) or "none"
                raise CapabilityError(f"no provider named {entry!r} in research.yaml (have: {known})")
            defaults = record.defaults.touch(model=entry_identity(entry), reasoning=None)
            return self._store.update_session(session, defaults=defaults)
        assert runtime is not None
        if model is None:
            raise CapabilityError("model is required with runtime")
        try:
            RouterProviderConfig(
                name=f"session:{runtime}", kind="local_cli", runtime=runtime, model=model,
                reasoning=reasoning, priority=0,
            )
        except ValidationError as exc:
            raise CapabilityError(_validation_sentence(exc)) from exc
        from research_harness.providers.cli.detection import detect_cached
        from research_harness.providers.cli.registry import get_runtime

        status = detect_cached(get_runtime(runtime), env=os.environ)
        if model != "default" and model not in {item.id for item in status.models}:
            raise CapabilityError(
                f"{runtime} does not list model {model!r}; run `research providers scan`"
            )
        defaults = record.defaults.touch(model=runtime_identity(runtime, model), reasoning=reasoning)
        return self._store.update_session(session, defaults=defaults)
```

and the module-level helper:

```python
def _validation_sentence(exc: ValidationError) -> str:
    """The first message of a pydantic error, without its `Value error, ` prefix."""
    message = str(exc.errors()[0]["msg"])
    return message.removeprefix("Value error, ")
```

`CapabilityError` is imported from `research_harness.domain.errors`; `ConversationSession`/`SessionDefaults` are already imported in that module. Keep line length ≤ 100 (wrap the `create` signature as the file already does). The `touch` on `record.defaults` re-validates through the shape rule, so an entry binding with a stale `reasoning` cannot be produced.

- [ ] **Step 12: Run it green, then the neighbours**

Run: `uv run pytest tests/contract/conversation/test_session_configure.py tests/unit/domain tests/unit/conversation tests/contract/capabilities/test_conversation.py tests/integration/conversation -q`
Expected: all pass (the existing conversation suites must not change behaviour: `create(model=...)` was never read on the send path).

- [ ] **Step 13: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src`

```bash
git add src/research_harness/domain/conversation.py src/research_harness/conversation/binding.py \
        src/research_harness/conversation/service.py tests/unit/domain/test_session_defaults.py \
        tests/unit/conversation/test_binding.py tests/contract/conversation/test_session_configure.py
git commit -m "feat(conversation): session bindings on the record, validated like an entry"
```

---

### Task 2: `session.configure` capability, parity, generated docs

**Files:**
- Modify: `src/research_harness/capabilities/conversation.py` (request near line 97, handler near 343, handler map at 527-547, spec list at 550-640)
- Modify: `tests/contract/protocol/test_new_capability_parity.py:102-118` (add the request sample)
- Modify: `tests/contract/capabilities/test_conversation.py` (round trip)
- Regenerate: `docs/guide/capabilities.md`, `web/capabilities.json`, `web/openapi.json`, `web/src/api/capabilities.gen.ts`
- Test: the two files above

**Interfaces:**
- Consumes: `ConversationService.configure(...)` (Task 1); `SessionView`; `Permission.MUTATE`.
- Produces: capability `session.configure` with request `{session, runtime?, model?, reasoning?, entry?, clear?}` and response `SessionView`; permission `mutate`, human-only by permission, not long-running.

- [ ] **Step 1: Write the failing round-trip test**

Append to `tests/contract/capabilities/test_conversation.py`:

```python
def test_a_session_binding_round_trips_through_the_registry(
    registry: CapabilityRegistry, ctx: CapabilityContext
) -> None:
    ctx.repo.update_providers(
        [{"name": "fast", "kind": "openai", "model": "gpt-5.4-mini", "api_key_env": "OPENAI_API_KEY"}]
    )
    created = invoke(registry, ctx, "session.create", {"title": "Latency study"})
    session = str(created.session.id)

    bound = invoke(registry, ctx, "session.configure", {"session": session, "entry": "fast"})
    assert bound.session.defaults.model is not None
    assert bound.session.defaults.model.model_dump() == {
        "provider": "entry", "model": "fast", "request_fingerprint": None
    }

    cleared = invoke(registry, ctx, "session.configure", {"session": session, "clear": True})
    assert cleared.session.defaults.model is None

    with pytest.raises(Exception, match="exactly one of"):
        invoke(registry, ctx, "session.configure", {"session": session})
    with pytest.raises(Exception, match="only for a runtime binding"):
        invoke(registry, ctx, "session.configure", {"session": session, "entry": "fast", "model": "x"})
```

and the sample to `tests/contract/protocol/test_new_capability_parity.py` next to `"session.rename"`:

```python
    "session.configure": {"session": "CS0001", "clear": True},
```

- [ ] **Step 2: Run both red**

Run: `uv run pytest tests/contract/capabilities/test_conversation.py tests/contract/protocol/test_new_capability_parity.py -q`
Expected: FAIL — unknown capability `session.configure`.

- [ ] **Step 3: Add the request, handler, map entry, and spec**

In `src/research_harness/capabilities/conversation.py`, after `RenameSessionRequest`:

```python
class ConfigureSessionRequest(CapabilityRequest):
    """`session.configure`: bind a session to a runtime and model, or to an entry, or clear.

    Exactly one of `runtime`, `entry`, `clear`; `model` is required with `runtime`;
    `reasoning` is allowed only with `runtime`. Nothing is written to `research.yaml`.
    """

    session: ConversationSessionId
    runtime: str | None = None
    model: str | None = None
    reasoning: str | None = None
    entry: str | None = None
    clear: bool = False

    @model_validator(mode="after")
    def _exactly_one_target(self) -> ConfigureSessionRequest:
        if sum((self.runtime is not None, self.entry is not None, self.clear)) != 1:
            raise ValueError("give exactly one of runtime, entry, or clear")
        if self.runtime is not None and self.model is None:
            raise ValueError("model is required with runtime")
        if self.runtime is None and (self.model is not None or self.reasoning is not None):
            raise ValueError("model and reasoning are only for a runtime binding")
        return self
```

(import `model_validator` from `pydantic` if the module does not already.) After `rename_session`:

```python
def configure_session(ctx: CapabilityContext, request: ConfigureSessionRequest) -> SessionView:
    """`session.configure`: the binding changes, and nothing else does (binding spec §8)."""
    return SessionView(
        session=_service(ctx).configure(
            request.session,
            runtime=request.runtime,
            model=request.model,
            reasoning=request.reasoning,
            entry=request.entry,
            clear=request.clear,
        )
    )
```

Map entry after `"session.rename": rename_session,`:

```python
            "session.configure": configure_session,
```

Spec entry after the `session.rename` spec:

```python
        spec(
            "session.configure",
            summary=(
                "Bind a session to a runtime and model, or to a research.yaml entry, or clear "
                "it; research.yaml is untouched."
            ),
            semantics=working,
            permission=Permission.MUTATE,
            request_model=ConfigureSessionRequest,
            response_model=SessionView,
        ),
```

- [ ] **Step 4: Run green**

Run: `uv run pytest tests/contract/capabilities/test_conversation.py tests/contract/protocol/test_new_capability_parity.py tests/contract/protocol -q` — Expected: pass. If the parity harness has a table of expected permissions per capability, add `session.configure` as `mutate`.

- [ ] **Step 5: Regenerate and verify the generated artifacts**

```bash
uv run python docs/guide/gen_capabilities.py
uv run python web/scripts/export_backend_json.py
cd web && pnpm gen:types && cd ..
git status --short
```

Expected changed files: `docs/guide/capabilities.md`, `web/capabilities.json`, `web/openapi.json` (only if the capability list is part of it), `web/src/api/capabilities.gen.ts`. Revert any `web/src/test/fixtures/*.json` whose diff is only temp paths, timestamps, or run ids: `git checkout -- web/src/test/fixtures/<file>` for each. Confirm `capabilities.gen.ts` contains `"session.configure": { permission: "mutate", humanOnly: true, longRunning: false, ... }`.

- [ ] **Step 6: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest tests/contract/protocol/test_web_routes.py tests/e2e/test_cli_capability_parity.py -q` (the CLI parity test will now fail for the missing `chat configure` command: that is Task 4's red; note it in the report and do not add the command here).

```bash
git add src/research_harness/capabilities/conversation.py tests/contract/capabilities/test_conversation.py \
        tests/contract/protocol/test_new_capability_parity.py docs/guide/capabilities.md \
        web/capabilities.json web/openapi.json web/src/api/capabilities.gen.ts
git commit -m "feat(capabilities): session.configure binds a session without touching research.yaml"
```

---

### Task 3: Routing resolution on send

**Files:**
- Modify: `src/research_harness/conversation/send.py:253-345` (`ProviderSelector`, `WorkspaceProviders.select`), `:369-384` (`ScriptedProviders.select`), `:505-514` (`_prepare` call site)
- Test: `tests/integration/conversation/test_send_session_binding.py` (new)

**Interfaces:**
- Consumes: `binding_of`, `RuntimeBinding`, `EntryBinding` (Task 1); `RouterProviderConfig`, `RouterConfig`, `build_router`, `ModelRouter`; `ProviderProfile`.
- Produces: `ProviderSelector.select(self, ctx, *, model, budget, defaults: SessionDefaults | None = None) -> Selection`; every selector implementation (including test doubles in `tests/`) accepts the keyword.

- [ ] **Step 1: Write the failing tests**

`tests/integration/conversation/test_send_session_binding.py`. Copy the fake `codex` fixture, `HELP`, and `lines()` from `tests/e2e/test_cli_providers_commands.py:20-62`; use the `ctx` fixture from `tests/contract/capabilities/conftest.py`. Sends run with `background=False` so the answer is appended before the call returns.

```python
"""A bound session routes like an entry and is refused like one (binding spec §9)."""

from __future__ import annotations

import pytest

from research_harness.capabilities.context import CapabilityContext
from research_harness.conversation.service import ConversationService
from research_harness.domain.conversation import MessageRole
from research_harness.domain.errors import CapabilityError
from research_harness.providers.cli.detection import DEFAULT_CACHE
from research_harness.providers.cli.errors import CliAuthError
from tests.fixtures.cli.fakes import FakeCli


def last_assistant(service: ConversationService, session) -> object:
    page = service.transcript(session, limit=500)
    return [m for m in page.messages if m.role is MessageRole.ASSISTANT][-1]


def test_a_bound_session_spawns_the_runtime_with_its_model_and_reasoning(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = service.create("x")
    service.configure(session.id, runtime="codex", model="gpt-5.5", reasoning="high")

    service.send(session.id, "What does Table 3 say?", background=False)

    (run,) = codex.runs()
    assert "gpt-5.5" in run["argv"]
    assert '-c' in run["argv"] and 'model_reasoning_effort="high"' in run["argv"]
    assert "What does Table 3 say?" not in " ".join(run["argv"])
    answer = last_assistant(service, session.id)
    assert answer.model is not None
    assert (answer.model.provider, answer.model.model) == ("session:codex", "gpt-5.5")


def test_a_per_message_model_wins_over_the_binding(ctx: CapabilityContext, codex: FakeCli) -> None:
    ctx.repo.update_providers(
        [{"name": "codex-sub", "kind": "local_cli", "runtime": "codex", "model": "gpt-5.4-mini"}]
    )
    service = ConversationService(ctx)
    session = service.create("x")
    service.configure(session.id, runtime="codex", model="gpt-5.5")

    service.send(session.id, "hello", model="codex-sub", background=False)

    (run,) = codex.runs()
    assert "gpt-5.4-mini" in run["argv"] and "gpt-5.5" not in run["argv"]
    assert last_assistant(service, session.id).model.provider == "local_cli:codex"


def test_a_bound_runtime_that_is_logged_out_is_refused_before_any_run(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    service = ConversationService(ctx)
    session = service.create("x")
    service.configure(session.id, runtime="codex", model="gpt-5.5")
    codex.write_script(
        {
            **codex.script(),
            "probes": [
                {"args": ["login", "status"], "stdout": "Not logged in\n", "exit": 1},
                *[p for p in codex.script()["probes"] if p["args"] != ["login", "status"]],
            ],
        }
    )
    DEFAULT_CACHE.clear()

    with pytest.raises(CliAuthError) as caught:
        service.send(session.id, "hello", background=False)

    assert caught.value.diagnostic == "login_missing"
    assert "codex is not logged in" in str(caught.value)
    assert codex.runs() == []


def test_the_policy_refuses_a_bound_session_before_any_spawn(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    from research_harness.privacy.policy import EgressPolicy

    service = ConversationService(ctx)
    session = service.create("x")
    service.configure(session.id, runtime="codex", model="gpt-5.5")
    ctx.repo.update_config(EgressPolicy(external_models="disabled"))

    with pytest.raises(Exception, match="external"):
        service.send(session.id, "hello", background=False)
    assert codex.runs() == []


def test_an_entry_binding_to_a_removed_entry_fails_like_a_stale_name(
    ctx: CapabilityContext, codex: FakeCli
) -> None:
    ctx.repo.update_providers(
        [{"name": "codex-sub", "kind": "local_cli", "runtime": "codex", "model": "gpt-5.5"}]
    )
    service = ConversationService(ctx)
    session = service.create("x")
    service.configure(session.id, entry="codex-sub")
    ctx.repo.update_providers([])

    with pytest.raises(CapabilityError, match="no provider named 'codex-sub'"):
        service.send(session.id, "hello", background=False)
    assert codex.runs() == []


def test_a_retry_follows_the_binding_at_retry_time(ctx: CapabilityContext, codex: FakeCli) -> None:
    service = ConversationService(ctx)
    session = service.create("x")
    service.configure(session.id, runtime="codex", model="gpt-5.4-mini")
    service.send(session.id, "hello", background=False)
    service.configure(session.id, runtime="codex", model="gpt-5.5")
    answer = last_assistant(service, session.id)

    service.retry(answer.id, background=False)

    assert "gpt-5.5" in codex.runs()[-1]["argv"]
```

The exact exception the policy raises is the one `WorkspaceProviders.select` already raises through `narrowed.egress_refusal()`; match on its message. If `send` wraps provider errors into a failed attempt instead of raising (read `SendService._prepare` and `_run`), assert on the failed attempt's `error` text and `diagnostic` instead, keeping `codex.runs() == []`. The retry test needs a message id from the transcript; `retry` takes the assistant message's id or the user message's id as `RetryMessageRequest` documents — read `SendService.retry` and use what it expects.

- [ ] **Step 2: Run red**

Run: `uv run pytest tests/integration/conversation/test_send_session_binding.py -q`
Expected: FAIL — the bound session sends to the project default (no providers → "no model providers configured").

- [ ] **Step 3: Thread the defaults into selection and resolve the binding**

In `src/research_harness/conversation/send.py`:

```python
class ProviderSelector(Protocol):
    """How a send finds its backend. Configuration, never a branch in domain code."""

    def select(
        self,
        ctx: CapabilityContext,
        *,
        model: str | None,
        budget: ContextBudget,
        defaults: SessionDefaults | None = None,
    ) -> Selection:
        """The provider for this call, refusing before a request exists (Product 34)."""
```

`WorkspaceProviders.select` becomes:

```python
    def select(
        self,
        ctx: CapabilityContext,
        *,
        model: str | None,
        budget: ContextBudget,
        defaults: SessionDefaults | None = None,
    ) -> Selection:
        from research_harness.conversation.binding import EntryBinding, RuntimeBinding, binding_of
        from research_harness.privacy.policy import load_policy
        from research_harness.privacy.traces import trace_writer_for
        from research_harness.providers.models.router import (
            ModelRouter,
            RouterConfig,
            RouterProviderConfig,
            build_router,
        )

        config = RouterConfig.model_validate({"providers": list(ctx.repo.config.providers)})
        # A per-message `model` wins; otherwise the session's binding; otherwise the
        # project default in priority order (binding spec §9).
        binding = None if model is not None or defaults is None else binding_of(defaults)
        wanted = model
        label: str | None = None
        if isinstance(binding, RuntimeBinding):
            session_entry = RouterProviderConfig(
                name=binding.label,
                kind="local_cli",
                runtime=binding.runtime,
                model=binding.model,
                reasoning=binding.reasoning,
                priority=0,
            )
            config = RouterConfig(providers=[*config.providers, session_entry])
            wanted = label = binding.label
        elif isinstance(binding, EntryBinding):
            wanted = binding.name
        if not config.providers:
            raise CapabilityError(
                "no model providers configured: add a `providers:` list to research.yaml, "
                "or preview the context with `context.preview`"
            )
        policy = load_policy(ctx.repo)
        router = build_router(config, policy=policy)
        entries = [
            entry
            for entry in router.entries
            if wanted is None or wanted in entry.tags or entry.provider.name == wanted
        ]
        if not entries:
            known = (
                ", ".join(sorted({tag for entry in router.entries for tag in entry.tags})) or "none"
            )
            raise CapabilityError(f"no provider named {wanted!r} in research.yaml (have: {known})")
        narrowed = ModelRouter(entries, policy=policy)
        refusal = narrowed.egress_refusal()
        if refusal is not None:
            raise refusal
        entry = narrowed.select(_requirements(budget.total), SEND_ROLE)
        capabilities = entry.provider.capabilities()
        alternatives = tuple(
            (other.label, other.provider.capabilities())
            for other in router.entries
            if other is not entry
        )
        return Selection(
            capabilities=capabilities,
            alternatives=alternatives,
            provider=streaming_provider(
                entry.provider, model=entry.model, trace=trace_writer_for(ctx.repo)
            ),
            profile=ProviderProfile(
                provider=label or entry.provider.name,
                model=entry.model,
                egress=(
                    EgressClass.LOCAL
                    if is_local_endpoint(capabilities.egress.endpoint_host)
                    else EgressClass.EXTERNAL
                ),
                vision=capabilities.vision,
                max_context_tokens=capabilities.max_context_tokens,
            ),
        )
```

`ScriptedProviders.select` gains `defaults: SessionDefaults | None = None` and `del`s it. At the `_prepare` call site (`send.py:514`) pass `defaults=record.defaults` (the session record is already in scope as `record`; if it is named differently, use the loaded `ConversationSession`). Import `SessionDefaults` from `research_harness.domain.conversation` at module level (it is a domain type; `send.py` already imports domain types). Grep `tests/` for `def select(` on selector doubles and add the keyword to each.

Note the `RouterProviderConfig` validator runs here too, so a record whose runtime lost its posture in a newer registry fails with the entry sentence rather than spawning.

- [ ] **Step 4: Run green, then every send suite**

Run: `uv run pytest tests/integration/conversation tests/contract/capabilities/test_conversation.py tests/e2e/test_conversation_gate.py tests/contract/providers/test_cli_provider.py -q`

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
git add src/research_harness/conversation/send.py tests/integration/conversation/test_send_session_binding.py
git commit -m "feat(conversation): resolve a session binding on send through the entry gates"
```

---

### Task 4: `research chat configure`, binding words in `list`/`show`, CLI reference

**Files:**
- Modify: `src/research_harness/cli/commands/session.py` (new command after `session_rename`; `list` line at 142-155; `show` header at 158-190)
- Modify: `tests/e2e/test_cli_capability_parity.py:245-291` (add `"session.configure": ("chat", "configure")`)
- Regenerate: `docs/guide/cli-reference.md`
- Test: `tests/e2e/test_chat_configure_command.py` (new)

**Interfaces:**
- Consumes: `ConversationService.configure` (Task 1); `binding_words` (Task 1); the egress sentence helper the `providers test` command uses in `src/research_harness/cli/commands/provider.py` (the line that prints `egress: <name> sends research content to <host> through <runtime name>`) — reuse its function; if it is private to that module, move it to a shared helper in `cli/commands/provider.py` exported as `egress_sentence(runtime_id: str, subject: str) -> str`.
- Produces: `research chat configure <session> [--runtime ID --model ID [--reasoning LEVEL] | --entry NAME | --clear] [--json]`; `chat list` rows end with `  [<binding words>]` when bound; `chat show` prints `bound to: <words>` as its second line.

- [ ] **Step 1: Write the failing e2e test**

`tests/e2e/test_chat_configure_command.py`. Reuse the `workspace` and `codex` fixtures and the `run`/`cli` helpers of `tests/e2e/test_cli_providers_commands.py` (copy the fixtures; import the Typer app the same way that module does).

```python
"""`research chat configure` binds, shows, and clears with the daemon's words (spec §11)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from research_harness.cli.app import app
from tests.fixtures.cli.fakes import FakeCli

runner = CliRunner()


def test_configure_prints_egress_then_the_binding_and_list_and_show_repeat_it(
    workspace: Path, codex: FakeCli
) -> None:
    created = json.loads(
        runner.invoke(app, ["chat", "new", "Latency", "-w", str(workspace), "--json"]).stdout
    )
    session = created["session"]["id"]

    result = runner.invoke(
        app,
        ["chat", "configure", session, "--runtime", "codex", "--model", "gpt-5.5",
         "--reasoning", "high", "-w", str(workspace)],
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if line]
    assert lines[0].startswith("egress: ") and "chatgpt.com" in lines[0]
    assert lines[1] == "bound to: session:codex/gpt-5.5 (reasoning high)"
    assert codex.runs() == []

    listed = runner.invoke(app, ["chat", "list", "-w", str(workspace)]).stdout
    assert "[session:codex/gpt-5.5 (reasoning high)]" in listed
    shown = runner.invoke(app, ["chat", "show", session, "-w", str(workspace)]).stdout
    assert shown.splitlines()[1] == "bound to: session:codex/gpt-5.5 (reasoning high)"

    cleared = runner.invoke(app, ["chat", "configure", session, "--clear", "-w", str(workspace)])
    assert cleared.exit_code == 0 and "bound to: project default" in cleared.stdout


def test_configure_refuses_with_the_entry_sentence_and_exits_non_zero(
    workspace: Path, codex: FakeCli
) -> None:
    created = json.loads(
        runner.invoke(app, ["chat", "new", "x", "-w", str(workspace), "--json"]).stdout
    )
    session = created["session"]["id"]
    result = runner.invoke(
        app, ["chat", "configure", session, "--runtime", "pi", "--model", "default", "-w", str(workspace)]
    )
    assert result.exit_code == 1
    assert "has no proven bounded" in result.output
    as_json = runner.invoke(
        app, ["chat", "configure", session, "--entry", "nope", "-w", str(workspace), "--json"]
    )
    assert as_json.exit_code == 1 and "no provider named 'nope'" in as_json.output
```

- [ ] **Step 2: Run red**

Run: `uv run pytest tests/e2e/test_chat_configure_command.py tests/e2e/test_cli_capability_parity.py -q` — Expected: FAIL (no such command; parity table incomplete).

- [ ] **Step 3: Add the command and the words**

In `src/research_harness/cli/commands/session.py`:

```python
@session_app.command("configure")
def session_configure(
    session: SessionArgument,
    workspace: WorkspaceOption = None,
    runtime: Annotated[
        str | None, typer.Option("--runtime", help="Runtime id from `research providers scan`.")
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="Model id from the scan, or `default`.")
    ] = None,
    reasoning: Annotated[
        str | None, typer.Option("--reasoning", help="The runtime's own effort name.")
    ] = None,
    entry: Annotated[
        str | None, typer.Option("--entry", help="An entry name in research.yaml.")
    ] = None,
    clear: Annotated[
        bool, typer.Option("--clear", help="Return the session to the project default.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Bind a session to a runtime and model, or an entry, or clear it (`session.configure`)."""
    from research_harness.cli.commands.provider import egress_sentence
    from research_harness.conversation.binding import binding_words

    with cli_errors():
        if runtime is not None and not as_json:
            typer.echo(egress_sentence(runtime, subject=f"session {session}"))
        record = _service(workspace).configure(
            ConversationSessionId(session),
            runtime=runtime, model=model, reasoning=reasoning, entry=entry, clear=clear,
        )
        emit(
            {"session": record.model_dump(mode="json")},
            [f"bound to: {binding_words(record.defaults)}"],
            as_json=as_json,
        )
```

`egress_sentence(runtime_id, *, subject)` returns `f"egress: {subject} sends research content to {definition.egress_host} through {definition.name}"` from the registry definition; extract it from the `providers test` implementation so both commands share one function. In `session_list`, append `  [{binding_words(item.defaults)}]` to a row only when `binding_of(item.defaults) is not None`; in `session_show`, insert `f"bound to: {binding_words(page.session.defaults)}"` as the second line. `cli_errors()` already turns `CapabilityError` into exit code 1 with the message.

Parity table: add `"session.configure": ("chat", "configure"),` after the `session.rename` row.

- [ ] **Step 4: Run green; regenerate the reference**

```bash
uv run pytest tests/e2e/test_chat_configure_command.py tests/e2e/test_cli_capability_parity.py tests/e2e/test_conversation_gate.py -q
uv run python docs/guide/gen_cli_reference.py
git diff --stat docs/guide/cli-reference.md
```

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src
git add src/research_harness/cli/commands/session.py src/research_harness/cli/commands/provider.py \
        tests/e2e/test_chat_configure_command.py tests/e2e/test_cli_capability_parity.py docs/guide/cli-reference.md
git commit -m "feat(cli): research chat configure binds a session and list/show print the binding"
```

---

### Task 5: Design system — grouped `ModelSelector`, nullable context, `SessionSummary.binding`

**Files:**
- Modify: `design/src/conversation/models.ts:102-113` (`ModelOption`, add `ModelOptionGroup`; `SessionSummary` gains `binding?: string`)
- Modify: `design/src/conversation/ModelSelector/ModelSelector.tsx`, its `.specimen.tsx` and `.test.tsx`
- Modify: the `SessionList` component under `design/src/conversation/` (find it with `grep -rl "SessionSummary" design/src/conversation`) and its test
- Modify: `design/src/index.ts` (export `ModelOptionGroup`)
- Test: `design/src/conversation/ModelSelector/ModelSelector.test.tsx`, the SessionList test

**Interfaces:**
- Consumes: `Menu.Group` (`design/src/primitives/Menu/Menu.tsx:375-408`).
- Produces: `ModelOption.contextTokens: number | null`; `interface ModelOptionGroup { id: string; label: string; options: readonly ModelOption[] }`; `ModelSelectorProps.groups?: readonly ModelOptionGroup[]` rendered after the flat `options`, each as a `Menu.Group` with the group label as its accessible name; a disabled option still shows its `unavailableReason` as today; `SessionSummary.binding?: string` rendered by `SessionList` as a muted second line under the title.

- [ ] **Step 1: Write the failing tests**

Add to `ModelSelector.test.tsx`:

```tsx
it('renders groups with their label as the accessible name and keeps disabled reasons', async () => {
  const onChange = vi.fn();
  render(
    <ModelSelector
      options={[SAMPLE_MODELS[0]]}
      groups={[
        {
          id: 'codex',
          label: 'Codex CLI 0.150.1',
          options: [
            { ...SAMPLE_MODELS[0], id: 'runtime:codex:gpt-5.5', label: 'gpt-5.5', contextTokens: null },
            {
              ...SAMPLE_MODELS[0],
              id: 'runtime:cursor-agent',
              label: 'Cursor Agent 1.4.0',
              available: false,
              unavailableReason: 'cursor-agent 1.4.0 has no tested bounded (no-tools, read-only) mode',
              contextTokens: null,
            },
          ],
        },
      ]}
      value={SAMPLE_MODELS[0].id}
      onChange={onChange}
    />,
  );
  await userEvent.click(screen.getByRole('button', { name: /model/i }));
  const group = screen.getByRole('group', { name: 'Codex CLI 0.150.1' });
  expect(within(group).getByRole('menuitemradio', { name: /gpt-5\.5/ })).toBeEnabled();
  const blocked = within(group).getByRole('menuitemradio', { name: /Cursor Agent 1\.4\.0/ });
  expect(blocked).toHaveAttribute('aria-disabled', 'true');
  expect(within(group).getByText(/has no tested bounded/)).toBeInTheDocument();
  await userEvent.click(within(group).getByRole('menuitemradio', { name: /gpt-5\.5/ }));
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ id: 'runtime:codex:gpt-5.5' }));
});

it('renders a model with no declared context window without a token count', async () => {
  render(
    <ModelSelector
      options={[{ ...SAMPLE_MODELS[0], contextTokens: null }]}
      value={SAMPLE_MODELS[0].id}
      onChange={() => undefined}
    />,
  );
  await userEvent.click(screen.getByRole('button', { name: /model/i }));
  expect(screen.queryByText(/ctx|tokens|k\b/)).not.toBeInTheDocument();
});
```

Match the role names (`menuitemradio` or `menuitem`) and the trigger's accessible name to what the existing tests in that file use. Add to the SessionList test:

```tsx
it('shows a session binding under the title when the record has one', () => {
  render(
    <SessionList
      sessions={[{ ...SAMPLE_SESSIONS[0], binding: 'session:codex/gpt-5.5 (reasoning high)' }]}
      activeId={null}
      onSelect={() => undefined}
      query=""
      onQueryChange={() => undefined}
    />,
  );
  expect(screen.getByText('session:codex/gpt-5.5 (reasoning high)')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run red**

Run: `pnpm --filter @research-harness/design test -- ModelSelector SessionList` — Expected: FAIL (no `groups` prop; type error on `contextTokens: null`; binding not rendered).

- [ ] **Step 3: Implement**

In `models.ts`:

```ts
export interface ModelOption {
  id: string;
  label: string;
  provider: string;
  egressClass: EgressClass;
  vision: boolean;
  /** Declared context window in tokens; `null` when the source declares none. */
  contextTokens: number | null;
  available: boolean;
  unavailableReason?: string;
}

/** A labelled set of options, rendered as one accessible group in the selector. */
export interface ModelOptionGroup {
  id: string;
  label: string;
  options: readonly ModelOption[];
}
```

and `binding?: string` on `SessionSummary` with the doc comment `/** The session's binding words, composed by the client from the record; absent for the project default. */`. In `ModelSelector.tsx`, add `groups?: readonly ModelOptionGroup[]` to the props, render each group after the flat options as `<Menu.Group label={group.label}>{group.options.map(renderItem)}</Menu.Group>`, factoring the existing item rendering into `renderItem(option)`; wherever `contextTokens` is formatted, render nothing when it is `null`. `value` lookup must search the groups too (for the selected label on the trigger). In the SessionList row, render `summary.binding` in a `<span className="rh-session-list__binding rh-text-secondary">` under the title when present; add the class to the component's CSS with tokens only. Update `samples.ts` if the type change breaks it, and the specimen to show one group.

- [ ] **Step 4: Run green and the whole design suite**

Run: `pnpm --filter @research-harness/design test && pnpm --filter @research-harness/design typecheck` (or the package's equivalent scripts; check `design/package.json`).

- [ ] **Step 5: Commit**

```bash
git add design/src
git commit -m "feat(design): grouped ModelSelector, nullable context window, session binding line"
```

---

### Task 6: Web — composer picker, disclosure, session binding

**Files:**
- Modify: `web/src/api/dto.ts:784-789` (`SessionDefaults.reasoning`), add `ConfigureSessionRequest`
- Modify: `web/src/api/client.ts` (add `configureSession`)
- Modify: `web/src/views/conversation/useModels.ts`, `useSessions.ts`, `mappers.ts`, `state.tsx`, `ComposerPane.tsx`, `SessionListPane.tsx`
- Modify: `web/src/test/fixtures/conversation/sessions.json` (bind `CS0002`)
- Test: `web/src/views/conversation/ConversationRoute.test.tsx` (new cases) and `mappers.test.ts`; `tests/contract/protocol/test_web_routes.py` (DTO name assertion, if it enumerates `SessionDefaults` fields)

**Interfaces:**
- Consumes: capability `session.configure` (Task 2); `ModelOptionGroup`, `SessionSummary.binding` (Task 5); `client.providerCliScan()`; `web/src/app/settings/mappers.ts` (`groupRuntimes`); `useSession().canMutate` and `mutationBlockedReason`.
- Produces: `client.configureSession(input: ConfigureSessionRequest): Promise<ConversationSession>`; `SessionsApi.configure(sessionId, input): Promise<void>` that replaces the record in `sessions`; `ModelsApi.groups: ModelOptionGroup[]`, `ModelsApi.reasoningChoices(runtime): string[]`; `mappers.ts` `bindingWords(defaults): string | null` and `runtimeOptionId(runtime, model)` / `parseRuntimeOptionId(id)`.

- [ ] **Step 1: DTO and client**

In `dto.ts`:

```ts
/** `domain/conversation.py::SessionDefaults`. */
export interface SessionDefaults {
  model?: ModelIdentity | null;
  mode?: string | null;
  token_budget?: number | null;
  /** The runtime's own effort name for a runtime binding; absent otherwise. */
  reasoning?: string | null;
}

/** `session.configure`: exactly one of `runtime`, `entry`, `clear`. */
export interface ConfigureSessionRequest {
  session: string;
  runtime?: string;
  model?: string;
  reasoning?: string;
  entry?: string;
  clear?: boolean;
}
```

In `client.ts` next to `renameSession`:

```ts
  /** Bind a session to a runtime and model, an entry, or clear it. research.yaml is untouched. */
  async configureSession(input: ConfigureSessionRequest): Promise<ConversationSession> {
    const request: Record<string, Json> = { session: input.session };
    if (input.runtime !== undefined) request.runtime = input.runtime;
    if (input.model !== undefined) request.model = input.model;
    if (input.reasoning !== undefined) request.reasoning = input.reasoning;
    if (input.entry !== undefined) request.entry = input.entry;
    if (input.clear !== undefined) request.clear = input.clear;
    return (await this.call<SessionView>('session.configure', request)).session;
  }
```

- [ ] **Step 2: Mappers with a failing test first**

Add to `mappers.test.ts`:

```ts
it('composes the binding words in the fixed format the CLI uses', () => {
  expect(bindingWords({ model: { provider: 'local_cli:codex', model: 'gpt-5.5' }, reasoning: 'high' }))
    .toBe('session:codex/gpt-5.5 (reasoning high)');
  expect(bindingWords({ model: { provider: 'local_cli:claude', model: 'default' } }))
    .toBe('session:claude/default');
  expect(bindingWords({ model: { provider: 'entry', model: 'codex-sub' } })).toBe('entry codex-sub');
  expect(bindingWords({ model: { provider: 'fast', model: 'fast' } })).toBe('entry fast');
  expect(bindingWords({ model: null })).toBeNull();
});

it('round-trips a runtime option id', () => {
  expect(parseRuntimeOptionId(runtimeOptionId('codex', 'gpt-5.5'))).toEqual({ runtime: 'codex', model: 'gpt-5.5' });
  expect(parseRuntimeOptionId('codex-sub')).toBeNull();
});
```

Then in `mappers.ts`:

```ts
const RUNTIME_PROVIDER_PREFIX = 'local_cli:';
const RUNTIME_OPTION_PREFIX = 'runtime:';

/** Plan ruling 4: one fixed format on every surface; `null` means the project default. */
export function bindingWords(defaults: SessionDefaults): string | null {
  const identity = defaults.model;
  if (!identity) return null;
  if (identity.provider.startsWith(RUNTIME_PROVIDER_PREFIX)) {
    const base = `session:${identity.provider.slice(RUNTIME_PROVIDER_PREFIX.length)}/${identity.model}`;
    return defaults.reasoning ? `${base} (reasoning ${defaults.reasoning})` : base;
  }
  return `entry ${identity.model}`;
}

export function runtimeOptionId(runtime: string, model: string): string {
  return `${RUNTIME_OPTION_PREFIX}${runtime}:${model}`;
}

export function parseRuntimeOptionId(id: string): { runtime: string; model: string } | null {
  if (!id.startsWith(RUNTIME_OPTION_PREFIX)) return null;
  const rest = id.slice(RUNTIME_OPTION_PREFIX.length);
  const at = rest.indexOf(':');
  return at <= 0 ? null : { runtime: rest.slice(0, at), model: rest.slice(at + 1) };
}

export function toRuntimeGroup(status: CliRuntimeStatus): ModelOptionGroup {
  const title = status.version ? `${status.name} ${status.version}` : status.name;
  if (!status.routable) {
    return {
      id: status.runtime,
      label: title,
      options: [
        {
          id: `${RUNTIME_OPTION_PREFIX}${status.runtime}`,
          label: title,
          provider: `local_cli:${status.runtime}`,
          egressClass: 'external',
          vision: false,
          contextTokens: null,
          available: false,
          ...(status.unavailable_reason ? { unavailableReason: status.unavailable_reason } : {}),
        },
      ],
    };
  }
  return {
    id: status.runtime,
    label: title,
    options: status.models.map((model) => ({
      id: runtimeOptionId(status.runtime, model.id),
      label: `${model.label} (${status.model_source})`,
      provider: `local_cli:${status.runtime}`,
      egressClass: 'external',
      vision: false,
      contextTokens: model.context_tokens ?? null,
      available: true,
    })),
  };
}
```

`toSessionSummary` adds `...(words ? { binding: words } : {})` from `bindingWords(session.defaults)`.

- [ ] **Step 3: Hooks**

`useModels(client, { enabled })` additionally calls `client.providerCliScan()` (in parallel with `providers()`; a failure of the scan leaves `groups: []` and does not disturb the entries) and returns `groups: ModelOptionGroup[]` built from `groupRuntimes(report).installed.map(toRuntimeGroup)` and `reasoningChoices(runtime)` reading `report.runtimes`. `useSessions` gains:

```ts
  configure: (sessionId: string, input: Omit<ConfigureSessionRequest, 'session'>) => Promise<void>;
```

implemented like `rename`: call `client.configureSession({ session: sessionId, ...input })`, replace the returned record in `sessions`, set `refusal` on failure with the daemon's message.

- [ ] **Step 4: Composer and session list, with failing route tests first**

Add to `ConversationRoute.test.tsx` (fixtures: `sessions.json` with `CS0002` bound to `local_cli:codex` / `gpt-5.5` / `high`; `cli-scan.json` from the providers fixtures; a `session.configure` answer returning the updated record):

1. the selector shows a "Configured entries" section and a "Codex CLI 0.150.1" group with `gpt-5.5 (live)`, and a disabled "Cursor Agent 1.4.0" row carrying the scan's reason; no row for `amp` (not installed);
2. picking `gpt-5.5` under Codex shows the egress notice text from the scan fixture (`notice`) and, after confirming, calls `session.configure` with `{ session, runtime: 'codex', model: 'gpt-5.5' }`, then the selector value follows the returned record;
3. the reasoning control appears for a runtime binding with `low, medium, high, xhigh` and changing it calls `session.configure` with `reasoning`;
4. the confirmation is not shown a second time for the same session (a second pick calls `session.configure` directly);
5. opening the bound `CS0002` shows the selector value `gpt-5.5 (live)` under Codex and the session row shows `session:codex/gpt-5.5 (reasoning high)`;
6. a read-only window (`AS_HOST` overview, as in `settings.test.tsx`) shows runtime rows disabled with the mutation-blocked reason and picking an entry sets the per-message model without calling `session.configure`;
7. a refused `session.configure` (envelope with `ok: false`) renders the daemon's message and leaves the selector on the previous value;
8. `expectNoAxeViolations` on the composer with the reasoning control shown.

Implementation in `ComposerPane.tsx`: pass `groups={models.groups}` to `ModelSelector`; compute `selectedModel` from `sessions.active?.defaults` via `bindingWords`/`parseRuntimeOptionId` (runtime binding → `runtimeOptionId`; entry binding → the entry id; else per-message `model` or `models.defaultId`); on change, when `canMutate`: if `parseRuntimeOptionId(option.id)` is non-null, check `localStorage['rh.binding-disclosed.' + sessionId]` (wrapped in try/catch); if absent, open a confirmation `Dialog` (the same component the Settings `RuntimeCard` uses for its egress warning) whose body is the scan report's `notice` and whose confirm button calls `sessions.configure(sessionId, { runtime, model })` and sets the key; otherwise configure directly; for an entry option call `sessions.configure(sessionId, { entry: option.id })`. When `!canMutate`, keep `setModel(option.id)` and render runtime groups with every option `available: false` and `unavailableReason: mutationBlockedReason`. Render the reasoning control as a `Select` next to the selector when the binding is a runtime binding, options from `models.reasoningChoices(runtime)` plus a first "runtime default" option; on change call `sessions.configure(sessionId, { runtime, model, reasoning })` (omit `reasoning` for the default). `SessionListPane` needs no change beyond `toSessionSummary`.

- [ ] **Step 5: Run green and the gates**

```bash
pnpm --filter research-harness-web typecheck && pnpm --filter research-harness-web lint && pnpm --filter research-harness-web test && pnpm --filter research-harness-web build
uv run pytest tests/contract/protocol/test_web_routes.py -q
```

plus the token and contrast checks used by the settings section (`check-tokens`, contrast script in `web/package.json`).

- [ ] **Step 6: Commit**

```bash
git add web/src design/src
git commit -m "feat(web): bind a session to a runtime and model from the composer"
```

---

### Task 7: Docs and status

**Files:**
- Modify: `docs/guide/providers.md` (a short subsection after the YAML block: "Binding a session instead of configuring the project"), `docs/architecture/web.md` (composer paragraph), `docs/decisions/ADR-030-cli-backed-providers-are-bounded-external-workers.md` (addendum), `docs/plans/acceptance-matrix.md` (a new table for the eight criteria of binding spec §16), `ROADMAP.md` (a status paragraph and gate rows under the CLI providers section), `README.md` (one sentence in the status paragraph), `docs/guide/cli-reference.md` and `docs/guide/capabilities.md` (already regenerated; verify byte-identical)

**Interfaces:** consumes the test names of Tasks 1–6 (read them from the tree; every cell names a test that exists).

- [ ] **Step 1: Write the guide subsection** with the three `research chat configure` invocations, the composer path, the precedence rule (per-message, binding, project default), the refusal sentences, and the words `session:<runtime>/<model>`.
- [ ] **Step 2: Write the ADR addendum** (dated 2026-09-04): "A session binding is a second, non-persisted way to name a CLI provider; it passes every invariant above through the same validator and gates as a `research.yaml` entry."
- [ ] **Step 3: Acceptance matrix and ROADMAP**: eight rows, each naming the test that pins it; ROADMAP status "all eight hold" only if every named test exists and passed in Task 8's gate; otherwise the caveat goes in the cell.
- [ ] **Step 4: Verify generated files**: run both generators and `export_backend_json.py` and confirm no diff.
- [ ] **Step 5: Commit** `docs: session runtime binding — guide, ADR-030 addendum, acceptance rows`.

---

### Task 8 (PM): gates, final review, push

- Full `uv run pytest -q`; web and design suites; ruff/format/mypy; secret scan `git grep -nE 'sk-(proj-)?[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer [A-Za-z0-9._-]{20,}|xox[abpr]-' -- ':!open-design' ':!deepseek-harness' ':!tests' ':!docs/superpowers/plans' ':!pnpm-lock.yaml'`.
- Whole-branch review (most capable model), one fix wave, one scoped re-review, adjudicate residuals.
- Update the acceptance matrix cells to the final state; push `cli-providers:main` to `origin` as the user directed.
