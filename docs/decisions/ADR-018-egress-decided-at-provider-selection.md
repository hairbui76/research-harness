# ADR-018: Egress is decided at provider selection; secrets come only from the environment

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §4, §18, §19.3, §34, §42 F, §43; ROADMAP.md Task 4.1, Task 12.1, Task 17.4; implemented in `privacy/policy.py`, `privacy/traces.py`, `privacy/egress.py`, `providers/models/router.py`, `providers/search/__init__.py`, `cli/commands/privacy.py`

## Context

§34 asks for four things easy to state and easy to place badly: every provider declares
what leaves the workstation, a project can disable external-model egress, keys live in the
environment and never in a workspace file, and traces are disposable and redactable.
Checking late — inside an adapter — means every adapter must remember it and a new one
silently opts out. Checking in `capabilities/` would make it a permission, which it is not:
egress is about where bytes go, not who is asking.

## Decision

`EgressPolicy` lives in `research.yaml` under `privacy:`: `external_models`,
`search_providers`, an `allowed_hosts` allowlist, `allow_source_text`, `allow_identifiers`,
`trace_retention_days`, and `redact_traces`. Each provider declares an `EgressDeclaration`
— endpoint host, whether it sends source text or identifiers — and `check_egress` collects
every failing rule so a refusal names the setting to change. Loopback is exempt: a local
model is not egress. `EgressDeniedError` is a domain error and deliberately *not* the
provider-failure type, so failover cannot mistake it for an outage.

**Enforcement sits where a provider is chosen, before a request exists.**
`ModelRouter.select` treats a refused entry exactly like an incapable one, so
`external_models: disabled` still routes to a local model and raises only when nothing
capable remains. The search registry checks before constructing an adapter, and
asymmetrically: a source the researcher named is refused loudly, a default-set source is
dropped — but an emptied set raises, because "we could not search" must never look like "we
searched and found nothing" (§18, §42 F). Secrets come from the environment alone: an entry
names a variable, no field holds a key, `refuse_inline_secrets` rejects key-shaped config at
workspace open and at router validation, and a resolved key is a `SecretStr` excluded from
dumps. Traces carry `authority: none`, and redaction digests source text as it is written.

## Consequences

### Positive

- A sensitive corpus is configured once in a readable file, and a refusal names the
  endpoint and the setting rather than failing as a timeout.
- Disabling external models degrades to local inference rather than breaking the workflow;
  no credential can be committed, because the only source of a key is the shell.

### Negative / costs

- Policy is applied per provider selection, so a client built outside the router escapes
  the check — and `extra_handlers._router` is built without the policy today, so model
  egress is enforced on the CLI path and **not** on the HTTP and MCP paths reaching
  `evidence.extract`, `evidence.verify`, and `manuscript.draft`. A gap to close.
- Redaction is by field name, so a new source-text field is unredacted until it is listed.

## Invariants this ADR protects

- Every provider declares what leaves the workstation, addressable without constructing an
  adapter (§34), and a local endpoint is never treated as egress.
- A key in `research.yaml` stops the workspace from opening (Task 17.4), and no egress
  report can contain a credential value.
- A policy refusal is never a provider failure and never a zero result: a source that could
  not be searched is a `SourceFailure` (§18, §42 F), and traces carry no authority (§19.3).

## Rejected alternatives

- **Check inside each adapter before the HTTP call.** Every new adapter opts out by
  forgetting, and the check runs after a request with source text is built.
- **Make egress a capability permission.** Confuses who is asking with where bytes go.
- **Fail the whole call when one provider is refused.** A refused external model should
  fall through to a local one; refusing everything is honest only when nothing remains.
- **Redact traces on read.** Plaintext would already be on disk.

## Where it is enforced

- `src/research_harness/privacy/policy.py`: `EgressPolicy`, `check_egress`,
  `EgressDeniedError`, `is_local_endpoint`, `refuse_inline_secrets`, `load_policy`.
- `providers/models/router.py` (`select`, `_denial_for`), `providers/search/__init__.py`
  (`_permitted_sources`), `privacy/egress.py` (`check_embedding_egress`, `egress_report`).
- `providers/models/base.py` (`EgressDeclaration`, `resolve_api_key`, `TraceSink`),
  `privacy/traces.py` (`TraceWriter`, `redact_payload`, `purge`), `cli/commands/privacy.py`.
- Tests: `tests/unit/privacy/`, `tests/integration/privacy/`, `tests/contract/search/`.
