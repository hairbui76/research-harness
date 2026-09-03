# ADR-027: ResearchGraph is a disposable projection, with authority and visibility on every node and edge

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §15, §37, §42 (O), §43 "the index becomes the knowledge model"; ROADMAP.md Phase 20, Gate P20; `docs/superpowers/specs/2026-09-03-research-graph-index-design.md` §2–§11; measured in `docs/plans/performance-budgets.md`; implemented in `domain/graph.py`, `graph/` (schema, projectors, sessions, rebuild, queries, resolver, context, bench), `capabilities/graph.py`

## Context

Resolving `@E0482` by walking YAML is fine at ten Works and hopeless at a thousand, and a
two-hop "which Evidence contradicts this Claim, and where exactly does it say so" is not a
query a file tree answers at all. So the product needs an index. Every index of scientific
state is one field away from becoming the authority: a row that says `accepted`, a
neighbourhood that quietly includes a private session, a stale anchor served as current.
ADR-006 settled that retrieval indexes are disposable; the graph is bigger than a retrieval
index — it spans corpus identity, document structure, scientific relations, manuscript
objects, and now conversation — and needed the rule restated with teeth.

## Decision

The ResearchGraph is a SQLite projection at `.research/graph/research-graph.db`: node,
edge, forward and reverse adjacency, an FTS5 text projection, per-source fingerprints, and
build checkpoints. It is deleted and rebuilt like everything else under `.research/`, and
`research rebuild` rebuilds it alongside the relational projection.

**Every node and every edge carries `authority` and `visibility`, and the values are
derived, not asserted.** An edge also carries `origin` (`structural | accepted |
model_proposed | researcher`), `status`, and a source pointer. `GraphEdge` refuses two
combinations outright: a `model_proposed` edge may not be `accepted` — "acceptance is a
reviewed canonical relation, never a projection label" — and an edge read off an accepted
relation may not be `candidate`. Candidate edges projected from staging therefore stay
candidate by construction rather than by discipline. The session namespace projects with
`private` authority throughout, because a transcript is not reviewed state, and a message
or attachment inherits *the stricter* of its own and its session's visibility, so a
`project` message inside a `private` session projects as `private` and nothing downstream
has to remember to re-join the session record.

**Privacy is a filter on the walk, not on the result.** Every query runs inside one
`GraphVisibility` allow-list that `graph.queries` applies at each hop, so an excluded node
is never expanded and a fragment cannot be reached by hopping *through* something the
request was not allowed to see. That is what makes graph spec §8 a property of the data
rather than a rule each query re-implements — and it is measurably free, because pruning
the frontier can only reduce work.

**The projection proposes; canonical files decide.** `graph.resolve` answers an `@`
reference or an `rh://` deep link by reading the canonical object through
`WorkspaceRepository` — existence in *this* project, authority, visibility, and anchor
freshness (both `file_hash` and `text_hash`, so a re-parse that moved a block is reported
stale rather than opened and hoped for). A stale graph therefore degrades navigation and
can never mislabel authority. A workspace with no graph answers reads emptily instead of
raising, and the conversation retriever falls back to a direct transcript scan.

**Rebuild is deterministic and incremental update is equivalent to it.** The unit of
projection is one durable file, carrying its workspace-relative path as source key and its
digest as fingerprint. `rebuild_graph` builds beside the target and moves it into place;
`update_graph` deletes every row the changed sources own, inserts the current projection,
restores rows an unchanged source still owns, re-indexes FTS, and advances the checkpoint —
all in one transaction. `dump_graph` is how the tests prove a full rebuild and an
incremental update produce byte-identical output.

**The budgets are measured, not assumed.** `graph/bench.py` measures warm latency for the
three modes graph spec §9 budgets, `benchmarks/graph/` generates the agreed personal-scale
corpus (33,180 nodes and 74,617 edges from 2,307 source files), and
`tests/perf/test_graph_budgets.py` asserts *the product budgets themselves* — 100 ms exact,
250 ms neighbourhood, 100 ms autocomplete — rather than a loosened CI version, because the
margin is three orders of magnitude.

## Consequences

### Positive

- `@E0482` means the same object before and after `rm -rf .research/`, because a reference
  resolves through canonical identity and the resolver's final answer is a canonical read.
- A model's proposed `supports` edge is visible in the same traversal as the accepted ones
  and is visibly not one of them.
- Restricting a walk for privacy costs nothing measurable (8.1 ms project-visible against
  11.9 ms unfiltered on the benchmark corpus), so there is no incentive to skip it.

### Negative / costs

- The graph holds no foreign keys: a citation node named by a bibliography the parse has
  not seen yet must be storable. A dangling edge is therefore an audit finding rather than
  an insert failure.
- A no-op incremental update still costs ~3.8 s at benchmark scale, because it re-projects
  every source to compare fingerprints. That is the same shape as the relational rebuild
  and touches no budgeted query mode.
- Candidate nodes live in `.research/staging/`, so deleting the projection legitimately
  changes the *node count* (the benchmark workspace loses its candidate nodes and their
  edges) while every stable reference and every accepted relation resolves identically.
  "Deterministic rebuild" is about the projection of what survived, not about a count.
- Session and attachment deep links are answered by the conversation store rather than the
  resolver, which reads canonical objects only.

## Invariants this ADR protects

- The graph is never scientific authority: it labels, it does not decide (§42 O, ADR-001,
  ADR-006).
- A model-proposed edge cannot be written as accepted, and an accepted relation cannot be
  written as candidate — both refused in the domain object (ADR-003).
- Deleting `.research/` cannot change a stable reference or an accepted relation (§42 C).
- A traversal cannot bypass an egress restriction through an allowed neighbour (graph spec
  §8; PRODUCT §34).
- A stale or candidate node is labelled and never silently substituted for an accepted one;
  the context assembler demotes it to the lowest tier and classes it `discovery`.
- Vector or lexical rank never grants authority: `score` is an assembly rank.
- An incremental update leaves no obsolete adjacency: update and full rebuild dump
  identically.

## Rejected alternatives

- **Neo4j, or a remote graph/search service.** The spec's own non-goal: a local SQLite
  projection has not failed a measured need, and a network dependency would break the
  offline guarantee for a lookup.
- **Make the graph canonical, and generate the files from it.** Turns a database with no
  Git history into the authority for what a project believes; the exact failure PRODUCT §43
  names.
- **Resolve references from the projected row.** Faster, and wrong the moment the index is
  behind — the row is exactly what may be stale.
- **Post-filter query results for privacy.** Cheap to write, and it leaks: the walk has
  already used the forbidden node to reach the fragment it returns.
- **Store one authority per node kind (evidence accepted, message private, …).** Loses
  contested, qualified, and stale, which are the states a researcher most needs to see in
  a traversal.
- **Budget by feel.** Task 17.3's lesson (ADR-023): a budget nobody measured is a number
  the implementation sets.

## Where it is enforced

- `src/research_harness/domain/graph.py`: `GraphEdge._authority_matches_origin`,
  `GraphNode`, `NodeKind` / `EdgeKind` / `EdgeOrigin` / `GraphAuthority` / `GraphVisibility`,
  `StableReference`, `DeepLink`.
- `graph/schema.py` (tables, adjacency, FTS, fingerprints, checkpoints),
  `graph/projectors.py` and `graph/sessions.py` (authority and visibility at projection
  time), `graph/rebuild.py` (`rebuild_graph`, `update_graph`, `dump_graph`),
  `graph/queries.py` (per-hop visibility), `graph/resolver.py` (canonical reads, anchor
  freshness), `graph/context.py` (ordered, privacy-first fragments),
  `graph/service.py` (empty answers when the index is absent), `capabilities/graph.py`.
- `graph/bench.py`, `benchmarks/graph/`, `docs/plans/performance-budgets.md` §"The
  ResearchGraph index".
- Tests: `tests/e2e/test_graph_gate.py`, `tests/perf/test_graph_budgets.py`,
  `tests/integration/graph/` (rebuild, incremental, queries, resolver, privacy,
  context fragments, sessions rebuild), `tests/unit/graph/`,
  `tests/unit/domain/test_graph.py`, `tests/contract/capabilities/test_graph.py`.
