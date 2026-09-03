# Architecture Decision Records

ADR-001 to ADR-010 record the architectural choices that `ROADMAP.md` §7 requires to be
written down before implementation proceeds. ADR-011 onward record the choices that were
made *during* implementation, so the decision record matches the code (`ROADMAP.md` §6,
item 9). All of them are derived from `PRODUCT.md` (the specification) and `ROADMAP.md`
(the plan), and they must stay consistent with `docs/architecture/conventions.md`.

An ADR here is binding. If implementation pressure suggests violating one, change the ADR
and `PRODUCT.md` explicitly rather than introducing an undocumented exception
(ROADMAP.md §7). Phase completion requires that relevant ADRs are updated
(ROADMAP.md §6, item 9).

| # | Title | Status |
|---|---|---|
| [ADR-001](ADR-001-canonical-state-authority.md) | Git-readable canonical state vs SQLite projection authority | Accepted |
| [ADR-002](ADR-002-work-version-artifact-identity.md) | Work/Version/Artifact identity separation | Accepted |
| [ADR-003](ADR-003-candidate-verified-accepted-authority.md) | Candidate/verified/accepted authority model | Accepted |
| [ADR-004](ADR-004-single-application-capability-layer.md) | One application capability layer for CLI/API/MCP/UI | Accepted |
| [ADR-005](ADR-005-provider-neutral-semantic-runtime.md) | Provider-neutral structured semantic runtime | Accepted |
| [ADR-006](ADR-006-disposable-retrieval-indexes.md) | Embedded retrieval indexes are disposable | Accepted |
| [ADR-007](ADR-007-strict-human-review-default.md) | Strict human review as default policy | Accepted |
| [ADR-008](ADR-008-staleness-over-silent-rewriting.md) | Staleness instead of silent derived-state rewriting | Accepted |
| [ADR-009](ADR-009-mcp-primary-host-boundary.md) | MCP primary host boundary with HTTP fallback | Accepted |
| [ADR-010](ADR-010-plugin-extension-boundary.md) | Domain plugins may extend vocabularies but not core scientific authority | Accepted |
| [ADR-011](ADR-011-stored-parse-blocks-are-canonical.md) | Stored parse blocks are canonical, and regenerable from artifact bytes | Accepted |
| [ADR-012](ADR-012-regenerable-staging-canonical-rejections.md) | Candidates are regenerable staging; acceptances and refusals are canonical | Accepted |
| [ADR-013](ADR-013-stale-marks-are-recomputed-projection-state.md) | Stale marks are projection state recomputed from canonical facts | Accepted |
| [ADR-014](ADR-014-event-object-digests-fail-closed.md) | Events carry object digests, and the workspace fails closed on disagreement | Accepted |
| [ADR-015](ADR-015-one-transaction-one-event-server-side-ids.md) | One transaction, one event, and ids allocated server-side under the lock | Accepted |
| [ADR-016](ADR-016-capability-permissions-and-the-agent-host-ceiling.md) | Four capability permissions, and an agent host that can never accept | Accepted |
| [ADR-017](ADR-017-disagreement-is-an-object-agreement-is-not.md) | Provider disagreement becomes an object; agreement never accepts | Accepted |
| [ADR-018](ADR-018-egress-decided-at-provider-selection.md) | Egress is decided at provider selection; secrets come only from the environment | Accepted |
| [ADR-019](ADR-019-table-driven-claim-strength-ladder.md) | The claim strength ladder is a table of named, checkable requirements | Accepted |
| [ADR-020](ADR-020-plugin-boundaries-enforced-at-load-time.md) | Plugin boundaries are enforced at load time, not by convention | Accepted |
| [ADR-021](ADR-021-authority-weights-and-fingerprinted-index.md) | Authority outweighs any single index, and each embedding gets its own directory | Accepted |
| [ADR-022](ADR-022-parser-recovers-but-never-fabricates.md) | The parser reconstructs and recovers, but never fabricates text | Accepted |
| [ADR-023](ADR-023-measured-budgets-behavior-preserving-fixes.md) | Budgets are measured and published; only behavior-preserving hotspots are fixed | Accepted |
| [ADR-024](ADR-024-imported-skills-are-classified-design-inputs.md) | Imported research skills are classified design inputs, not runtime components | Accepted |
| [ADR-025](ADR-025-conversation-is-durable-private-working-context.md) | Conversation is durable private working context, never accepted state | Accepted |
| [ADR-026](ADR-026-attachments-are-session-only-until-save-to-corpus.md) | Attachments are session-only until an explicit Save to corpus | Accepted |
| [ADR-027](ADR-027-researchgraph-is-a-disposable-labelled-projection.md) | ResearchGraph is a disposable projection, with authority and visibility on every node and edge | Accepted |
| [ADR-028](ADR-028-bounded-compilation-and-candidate-only-manuscript-edits.md) | Manuscript compilation is a bounded local process, and model edits are candidate diffs | Accepted |
| [ADR-029](ADR-029-one-local-design-system-owns-presentation.md) | One local Design System package owns presentation, and owns nothing else | Accepted |

## Conventions for this directory

- File name: `ADR-NNN-<kebab-case-slug>.md`. ADR-001 to ADR-010 are numbered in the order
  fixed by ROADMAP.md §7; later records take the next free number when the decision is
  written down.
- Status is one of `Proposed`, `Accepted`, `Superseded by ADR-NNN`, `Deprecated`.
- Each ADR states the decision, its consequences, the testable invariants it protects
  (mapped to `PRODUCT.md` §42 acceptance tests where one applies), the alternatives that
  were rejected, and the packages and test directories where it is enforced. Keep one to a
  page: the existing records are 80 lines each.
- An implementation-time ADR names the modules that implement it in its `Source` line, and
  records a known gap in `Consequences` rather than describing behaviour the code does not
  have yet.
- Superseding an ADR means writing a new one and marking the old one superseded; ADRs are
  not edited into silence.
