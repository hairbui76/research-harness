# ADR-016: Four capability permissions, and an agent host that can never accept

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §5 (P4), §21, §22, §24, §29, §34, §42 (B, H); ROADMAP.md Phase 10 Tasks 10.1–10.4, Gate P10, Task 17.1, Task 17.4; implemented in `capabilities/permissions.py`, `capabilities/registry.py`, `server/app.py`, `protocol/mcp.py`, `cli/commands/serve.py`

## Context

ADR-004 gives every mutation one handler and ADR-009 gives hosts one boundary, leaving the
authority question: who may call what. The rule is that a model proposes and the researcher
accepts (§5 P4, §24), but "the researcher" arrives over four transports with different
notions of identity — a shell, a browser and an editor holding a token, and an MCP host that
is a local subprocess with no credential at all. A permission model that is only a set of
grants is one hand-built request away from an agent host holding `mutate`.

## Decision

Capabilities declare one of four permissions: `read`, `stage` (writes only under
`.research/staging/`), `mutate`, and `admin` — the last carried today by `state.rebuild`
alone. A `human` principal holds all four; an `agent_host` and a `model` hold `read` and
`stage`. `Principal.authorize` makes two checks, and the second is deliberately
**kind-based rather than grant-based**: a `mutate`/`admin` permission, or a `human_only`
capability, is refused to any non-human principal whatever grants it holds.
`CapabilityRegistry.invoke` is the single choke point every transport passes, and it also
requires the context's actor to be human, so authority cannot be laundered by running a
human-shaped principal under a model actor; domain transitions re-check independently.

The daemon's authority is `.research/daemon-token`: 32 bytes from `secrets.token_urlsafe`,
written `0600` under regenerable state, presented as `Authorization: Bearer` and compared
with `compare_digest`. A caller with no token, or a wrong one, resolves to `agent_host` — a
correct state, not an error — and the daemon binds `127.0.0.1:8765` and nothing else. MCP
has no credential by design, so it is always `agent_host`, refuses mutations before taking
the lock, and still advertises them with a description saying to propose instead.

## Consequences

### Positive

- "A model cannot accept" is one predicate on one code path, re-checked in the domain,
  rather than a rule each transport remembers, and an agent host stays useful.
- Two hosts get byte-identical refusals: the message names the principal kind, never the
  host label.

### Negative / costs

- Downgrading rather than rejecting a tokenless caller means a misconfigured client gets a
  read-only session silently and discovers it at the first mutation.
- `create_app()` binds nothing itself, so loopback is a property of `research serve`, and
  one shared token cannot distinguish two of the researcher's own clients.

## Invariants this ADR protects

- A model cannot bypass the strict review gate for interpretive scientific state — §42 H,
  refused at the handler, the registry, HTTP, and MCP, leaving no Evidence behind.
- Every `mutate`/`admin` capability is refused over MCP with `permission_denied` — §42 B.
- A `stage` call writes only under `.research/staging/`, and the API never exposes
  arbitrary SQLite mutation; mutations are serialized (Task 10.2).
- A principal is resolved from the token, and tokens live under `.research/` (§34).

## Rejected alternatives

- **Grant-based authority alone.** A hand-constructed principal holding `mutate` would be
  accepted; the kind check makes the rule unforgeable in-process.
- **Reject tokenless HTTP callers.** The cockpit could not render before a token is pasted.
- **Give MCP a token.** A credential in a host's config file, expressing none of the
  boundary MCP actually needs: propose, never accept.
- **A per-project `mutate` grant for agent hosts.** Reintroduces the bypass §42 H removes,
  with a configuration switch attached to it.

## Where it is enforced

- `src/research_harness/capabilities/permissions.py`: `Permission`, `PrincipalKind`,
  `Principal.authorize`, `HUMAN_AUTHORITY`, `PermissionDenied`.
- `capabilities/registry.py`: `CapabilitySpec`, `invoke`, `_require_matching_actor`;
  `domain/transitions.py` re-checks the actor.
- `server/app.py` (`ensure_token`, the bearer resolver), `cli/commands/serve.py`
  (`LOOPBACK`, stdio-only MCP), `protocol/mcp.py`.
- Tests: `tests/contract/capabilities/test_registry.py`, `tests/contract/protocol/`
  (`test_http.py`, `test_mcp.py`, `test_vscode_contract.py`),
  `tests/e2e/invariants/test_h_human_review.py` and `test_b_host_independence.py`.
