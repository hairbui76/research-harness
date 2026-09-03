# ADR-009: MCP primary host boundary with HTTP fallback

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §1, §2, §6, §21, §22, §29, §31, §32.2, §35, §42 B, §43, §44.3, §44.15; ROADMAP.md Global Constraints, Phase 10 Tasks 10.2–10.4, Gate P10, Phase 16, Task 17.1

## Context

Claude, ChatGPT, the Web cockpit, and VS Code all need to work over one research state,
and the failure being designed against is that each host accumulates its own hidden state
(PRODUCT.md §2). Separate Claude and ChatGPT integrations would reproduce that failure at
the protocol layer, which §29 forbids. The transport choice is a scientific-integrity
choice, not just plumbing.

## Decision

MCP is the primary host integration boundary where the host supports it (§29, §44.15). A
local HTTP/JSON-RPC daemon plus a small SDK are the fallbacks for clients that need a
different transport, including the Web cockpit and the VS Code extension (§35).
Both surfaces expose the same §22 capability names and semantics and are thin clients of
the one capability layer (ADR-004); neither holds host-specific research business logic.
Agent hosts remain a separate abstraction from model providers (§21, ADR-005), so Claude
may be both a host and an internal model without the layers coupling.

Hosts may ask questions, compare papers, challenge claims, search for counter-evidence,
explain decision history, draft from accepted claims, and request approval. Conversation
content becomes project knowledge only when promoted into a research object through a
capability (§29, §31).

## Consequences

### Positive

- There is one host boundary to specify and contract-test, not one per vendor; adding a
  host is a transport binding, and hosts stay replaceable (the §43 lock-in mitigation).
- The local HTTP daemon keeps Web and VS Code working where MCP is not the best fit, and
  the CLI usable with no server at all; §42 B is demonstrable at Gate P10, not argued.

### Negative / costs

- Two transports must be maintained at parity, and DTOs must be expressible in both,
  constraining capability signatures. MCP is an external spec that will evolve.
- Long-running workflows do not fit request/response, so hosts must handle durable run IDs.

## Invariants this ADR protects

- A Claim created through CLI can be inspected through Web, VS Code, Claude, and ChatGPT
  without duplication — §42 B; Gate P10 requires exactly one canonical Claim object.
- Claude- and ChatGPT-compatible hosts see the same capability names and semantics, and
  MCP holds no host-specific research business logic (Task 10.3).
- No Claude-, OpenAI-, Anthropic-, or host-specific concept enters the Domain Core
  (Global Constraints; `docs/architecture/conventions.md`).
- The API never exposes arbitrary SQLite mutation and workspace mutations are serialized
  (Task 10.2).
- Long workflows return durable run IDs rather than requiring an open connection
  (Task 10.2, ADR-003).
- Conversation content becomes project knowledge only by explicit promotion (§29, §31),
  and plugins may not create host-specific state (§32.2, ADR-010).

## Rejected alternatives

- **Separate Claude and ChatGPT integrations.** Rejected by §29: duplicated business
  logic guarantees divergence.
- **HTTP only, no MCP.** Gives up the first-class host integration §44.15 selects and
  pushes every host into bespoke glue.
- **MCP only.** Web and VS Code need another transport (§35); the CLI should not require
  a protocol server.
- **A hosted or remote API.** Contradicts the local-first, single-user boundary (§4).

## Where it is enforced

- `src/research_harness/protocol/`: `mcp.py`, `http.py`, `dto.py`;
  `src/research_harness/server/app.py`; both are thin clients of
  `src/research_harness/capabilities/` (`registry.py`, `permissions.py`).
- Durable run IDs come from `workflows/engine.py` and `workspace/runs.py`. Per
  `docs/architecture/conventions.md`, `protocol/`, `server/`, and `cli/` never write
  canonical files or SQLite, nor import each other's internals.
- Tests: `tests/contract/protocol/test_http.py` and `test_mcp.py` (DTO parity),
  `tests/contract/capabilities/test_registry.py`, `tests/e2e/test_cli_capability_parity.py`,
  Gate P10, Task 17.1 host independence.
