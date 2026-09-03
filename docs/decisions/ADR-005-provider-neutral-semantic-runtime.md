# ADR-005: Provider-neutral structured semantic runtime

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §5 (P3, P9), §20, §21, §23, §41.3, §42 A, §43, §44.4, §44.12, §44.13; ROADMAP.md Global Constraints, Phase 4 Tasks 4.1–4.5, Gate P4, Phase 13, §5 (contract tests)

## Context

Model APIs change faster than research projects finish. Provider-specific concepts —
model names, tool-call encodings, prompt conventions, reasoning modes — spread through
application code as branches, and once they reach domain objects the scientific record
depends on a vendor. A researcher must be able to switch providers without migrating
scientific state (§41.3); provider lock-in is a named risk (§43).

## Decision

No provider-, host-, or vendor-specific concept enters the Research Domain Core (§5 P9;
`docs/architecture/conventions.md` forbids OpenAI, Anthropic, Claude, ChatGPT, and MCP
names in `domain/`). Model providers are internal workers, a separate abstraction from
agent hosts (§21, ADR-009). Workflows request capabilities, not model names —
`structured_output`, `context_tokens`, `reasoning`, `vision` (§20.2) — and a router maps
those requirements onto a configured provider/model.

Every scientific worker role returns a validated Pydantic schema; prose
is presentation, not canonical state (§20.3). Invalid structured output is rejected
before it reaches staging. Hidden chain-of-thought is neither required nor persisted;
what is persisted is provider, model identifier, configuration, workflow/template
version, timestamp, source object IDs, structured output, and a concise rationale where
useful (§20.5). Cross-model verification is selective, reserved for high-value gates
rather than routine extraction (§20.4, Phase 13).

## Consequences

### Positive

- §42 A becomes a test, not an aspiration: one workflow, two providers, one schema.
- New providers, local models included, are adapters rather than core changes.
- Fake transports make provider tests deterministic and offline (ROADMAP.md §5).

### Negative / costs

- A neutral contract gives up provider-specific features, and structured-output support
  differs across providers, so adapters carry normalization work.
- Refusing to persist hidden reasoning removes a debugging aid when a role misbehaves.

## Invariants this ADR protects

- The same Evidence verification workflow runs with Anthropic or OpenAI without changing
  canonical schemas — §42 A; at Gate P4 both adapters produce the same response schema.
- No provider-, host-, or vendor-specific concept appears in `domain/` (Global Constraints).
- Provider selection is by capability and configuration, not domain code branches, and
  invalid structured output is rejected before it reaches staging (Task 4.1).
- Hidden chain-of-thought is neither required nor persisted (§20.5, Task 4.1).
- Provider or model failure leaves canonical state unchanged (§6, item 5).
- Provider agreement does not auto-accept a Tier-2 scientific judgment under strict policy
  (Task 13.2, ADR-007).

## Rejected alternatives

- **Use one provider SDK directly.** Fastest to build, and the lock-in §43 warns about;
  it makes §42 A unimplementable.
- **Adopt a general-purpose LLM orchestration framework.** Imports another project's
  abstractions and release cadence into the core the domain is meant to outlive.
- **Free-text responses parsed with regexes.** Contradicts §20.3 and turns parser drift
  into silent scientific error.
- **Cross-verify every call.** Doubles routine cost for no scientific gain; §20.4
  restricts it to high-value gates.

## Where it is enforced

- `src/research_harness/providers/models/`: `base.py` (neutral request/response contract),
  `router.py` (capability routing), `openai_provider.py`, `anthropic_provider.py`,
  `local_provider.py`, `cross_verify.py`.
- `src/research_harness/roles/contracts.py` and the role modules define output schemas and
  permissions. Per `docs/architecture/conventions.md`, `providers/` holds no
  domain-specific business rules and `domain/` never imports it.
- Tests: `tests/contract/providers/` (`test_model_contract.py`, `test_openai_provider.py`,
  `test_anthropic_provider.py`, `test_local_provider.py`) with fake transports and opt-in
  live smoke, `tests/unit/roles/test_permissions.py`,
  `tests/unit/providers/test_cross_verify_policy.py`, Task 17.1 provider independence.
