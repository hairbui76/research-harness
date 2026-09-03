# ResearchGraph Index — Design Specification

**Status:** Design approved in conversation; awaiting review of this written specification.

**Scope:** Design only; no implementation is authorised by this document.

## 1. Purpose

Provide CodeGraph-like speed and traversal for research references while keeping canonical files as authority. ResearchGraph is the unified, rebuildable graph projection used by lookup, navigation, retrieval, dependency analysis, and context assembly.

It does not replace Evidence/Claim files, transcript files, manuscript source, or the semantic event log.

## 2. Node model

The graph may project these namespaces:

- project and working context: Project, Session, Message, Attachment;
- corpus identity: Work, Version, Artifact;
- document structure: Section, Paragraph, Table, Figure, Equation, Reference;
- scientific knowledge: Evidence, Claim, Question, Decision, Synthesis;
- manuscript: File, sentence, citation, and anchor.

Each node stores a stable external identity, node kind, authority/status label, visibility/egress class, canonical or durable source pointer, fingerprint, and projection metadata. Projected internal row IDs are disposable.

## 3. Edge model

### Deterministic edges

Derived from explicit structure or identity:

- `contains`;
- `version_of`;
- `artifact_of`;
- `cites`;
- `attached_to`;
- `anchored_at`;
- `mentioned_in`.

### Scientific edges

Scientific relations include:

- `supports`;
- `contradicts`;
- `qualifies`;
- `derived_from`;
- `depends_on`.

Every edge records origin, authority, status, and source pointer. Deterministically derived edges may be regenerated. Model-proposed scientific edges are `candidate` and cannot masquerade as accepted relations. Existing Research Core review rules decide when a relation becomes accepted.

## 4. Storage and rebuild

The initial implementation target is local SQLite:

- node table;
- edge table;
- forward and reverse adjacency indexes;
- FTS5 text projection;
- embedded vector projection;
- fingerprints and projection checkpoints.

No Neo4j or remote graph/search service is required initially. Graph, FTS, and vector data live under `.research/` and can be deleted and deterministically rebuilt from canonical scientific state, durable conversations, attachments, and manuscript source.

Incremental updates consume semantic events and source fingerprints. An update must remove obsolete projected nodes/edges for the changed source, insert the current projection, and advance its checkpoint atomically. Rebuild results must not change accepted scientific conclusions.

## 5. Stable references and deep links

Existing research IDs remain the primary human references:

- `@W0017` — Work;
- `@E0482` — Evidence;
- `@C0041` — Claim.

Session/manuscript types receive their own non-colliding prefixes. A reference resolves through canonical identity, not a disposable database row.

Deep links may address exact local targets, for example:

```text
rh://artifact/A0017-3?page=6&block=B0081
```

The resolver validates project, object existence, authority, privacy, and anchor freshness before navigation or context inclusion.

## 6. Query modes

ResearchGraph supports:

- exact reference lookup;
- prefix/name autocomplete for composer `@` references;
- one- and two-hop traversal in either direction;
- structured filters by node/edge kind, authority, status, project, and privacy;
- lexical and semantic retrieval constrained by graph neighborhoods;
- provenance paths from manuscript statement to exact artifact anchor;
- dependency/staleness and citation-neighborhood queries.

The query planner combines structured, FTS, vector, and graph operations according to intent. Vector similarity never grants scientific authority.

## 7. Context assembly

The context assembler requests a provenance-bearing subgraph under token and privacy budgets. It prioritises:

1. exact referenced accepted objects;
2. directly supporting, contradicting, and qualifying accepted relations;
3. current-session context;
4. relevant cross-session or corpus nodes;
5. broader semantic neighbours.

Each selected fragment carries its stable identity, source pointer, authority, relation path, and omission/reduction metadata. This produces the visible `Context used` receipt and lets a response be traced back through the same graph.

## 8. Privacy and authority

- Session/message/attachment nodes inherit local privacy and provider egress policy.
- A graph traversal cannot bypass an egress restriction merely because a neighbouring public node is allowed.
- Accepted Evidence, Claims, and Decisions rank above messages and model summaries.
- Stale or candidate nodes are labelled and cannot be silently substituted for accepted/current nodes.
- Direct canonical reads remain possible if the graph is unavailable or rebuilding.

## 9. Performance budgets

On the personal-scale benchmark corpus, target warm local latency is:

- exact stable-reference resolution: under 100 ms;
- one- or two-hop neighbourhood query: under 250 ms;
- autocomplete fast enough to update interactively while typing.

These are measured budgets, not reasons to weaken correctness or privacy. Benchmark shape and cold-start budgets belong in the later implementation plan.

## 10. Extension boundary

A code-symbol graph may later be delivered as a plugin with its own namespace and parsers. It can link repository symbols to Artifact or Work nodes, but it must not add programming-language concepts to the generic Research Core or weaken scientific authority rules.

## 11. Acceptance scenarios

1. Resolve `@E####` to the same Evidence before and after deleting and rebuilding `.research/`.
2. Traverse Claim → supporting/contradicting Evidence → exact Artifact anchors in both directions.
3. Keep a model-proposed `supports` edge visibly candidate until reviewed.
4. Autocomplete an `@` reference and record the exact resolved object in `Context used`.
5. Prevent a private prior-session node from entering an unauthorised external context pack.
6. Update affected nodes and edges after a source fingerprint change without leaving obsolete adjacency.
7. Meet the exact-ref and neighbourhood latency budgets on the agreed personal-scale corpus.
