# ADR-004: One application capability layer for CLI/API/MCP/UI

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §5 (P10), §22, §27, §36, §42 B, §44.2, §44.3; ROADMAP.md Global Constraints, Task 1.6, Phase 10 Tasks 10.1–10.4, Gate P10, §6 items 6 and 10

## Context

The product has four daily surfaces — CLI, Web cockpit, VS Code, and agent hosts
(PRODUCT.md §1) — and the failure it is built against is that each of these accumulates
its own hidden state and logic (§2). If every transport implements its own mutation path,
the review gate (ADR-003), the atomic journal (ADR-001), and dependency invalidation
(ADR-008) are re-implemented four times, and they diverge.

## Decision

`capabilities/` is the only supported mutation surface for accepted state. Every
accepted-state mutation has exactly one application handler, regardless of whether it is
reached from CLI, HTTP, MCP, Web, or VS Code (ROADMAP.md Task 1.6).

Capabilities are named and registered per PRODUCT.md §22 (`corpus.ingest`,
`evidence.accept`, `claim.audit`, `review.accept_batch`, `state.rebuild`, and so on), each
declaring read/write permissions, an input DTO, an output DTO, and its scientific mutation
semantics (Task 10.1). Every mutation produces a validation result, a semantic diff, an
event entry, and a dependency invalidation set (§36).

`cli/`, `server/`, `protocol/http.py`, and `protocol/mcp.py` are thin transports that
never write canonical files or SQLite. The layer starts deliberately small in Phase 1 and
gains discovery, permissions, and transports in Phase 10 without becoming a second
business-logic layer (Task 10.4).

## Consequences

### Positive

- The review gate, journal, and invalidation rules have exactly one enforcement point,
  and adding a transport is wiring rather than a scientific-semantics decision.
- Every important Web operation maps to a capability and is therefore scriptable (§27).
- Capability names give hosts and plugins a stable contract to call.

### Negative / costs

- A DTO layer sits between transports and handlers; some of it is boilerplate, and
  transports wanting a chattier or specialized interface do not get one.
- Capability granularity is an expensive commitment once hosts depend on the names.
- Direct file editing stays technically possible because state is human-readable, so
  edits must be validated and normalized on next load or rebuild (§36).

## Invariants this ADR protects

- A Claim created through CLI can be inspected through Web, VS Code, Claude, and ChatGPT
  without duplication — §42 B, shown at Gate P10 as exactly one canonical Claim.
- CLI commands do not call repository writes as an alternative path (Task 1.6).
- Every accepted-state mutation has one application handler regardless of transport.
- The API never exposes arbitrary SQLite mutation, and workspace mutations are serialized
  (Task 10.2); long workflows return durable run IDs rather than holding a connection open.
- CLI and API produce equivalent state transitions for the same operation (Task 10.4).
- No frontend or client acquires direct persistence responsibility (§6, item 6).

## Rejected alternatives

- **A service layer per transport.** Four implementations of the same invariants, drifting
  apart where correctness matters most.
- **Exposing the repository or ORM session to transports.** Makes ADR-001's journal and
  lock optional in practice.
- **A generic `execute_sql` or `patch_object` capability.** Reintroduces the bypass this
  ADR removes, with a stable name attached to it.
- **Placing the capability layer only inside the HTTP daemon.** The CLI would need a
  running server, defeating scriptability and offline use.

## Where it is enforced

- `src/research_harness/capabilities/`: `registry.py`, `permissions.py`, `handlers.py`,
  `dto.py` — the only supported mutation surface.
- `src/research_harness/protocol/` (`http.py`, `mcp.py`, `dto.py`), `server/app.py`, and
  `cli/app.py` — thin clients. Per `docs/architecture/conventions.md`, `capabilities/`
  must not import `cli/` or `server/`, and transports must not import each other.
- Tests: `tests/contract/capabilities/test_core_mutations.py` and `test_registry.py`,
  `tests/contract/protocol/test_http.py` and `test_mcp.py`,
  `tests/e2e/test_cli_capability_parity.py`, Task 17.1 host independence.
