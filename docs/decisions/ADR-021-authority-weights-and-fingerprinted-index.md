# ADR-021: Authority outweighs any single index, and each embedding gets its own directory

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §5 (P7), §15.1–§15.4, §42 C, §43; ROADMAP.md Phase 5 Tasks 5.2–5.4, Gate P5, Task 17.3; implemented in `retrieval/rerank.py`, `retrieval/planner.py`, `retrieval/service.py`, `retrieval/semantic.py`, `providers/models/embeddings.py`

## Context

ADR-006 says the indexes are disposable and the authority ladder decides what a project
treats as known. Turning that into a ranker is where it quietly fails: a ladder that merely
orders the *sources* still lets a strong lexical or semantic score on raw prose outrank an
accepted Evidence object once the scores are blended, and the index is the knowledge model
again — §43's risk, by arithmetic. The quieter failure is reusing a directory across models.

## Decision

Authority is a scored component whose weight is chosen so the ladder cannot be outvoted.
`AUTHORITY_SCORES` runs from accepted Evidence at 1.0 and accepted Claim at 0.88 down to the
parsed corpus at 0.25 and an external hint at 0.05; that gap is deliberately the widest on
the scale, and under every retrieval intent the authority weight times it exceeds what
either the lexical or the semantic component can contribute alone — an inequality asserted
as a test. Staleness is subtracted, so a stale accepted object is demoted. Ranking is the
second line: the ladder consults a rung only if higher rungs have not produced `k` hits and
records why it stopped, a merge keeps the *better* authority, and authority is resolved from
the projection rather than taken from the index.

The semantic index lives at `.research/index/semantic/<fingerprint>/`, where the fingerprint
is the provider's own `name/model/dimension` as a readable slug plus eight hex characters of
its digest, so two that fold to the same text can never share a directory of vectors. The
provider and model are recorded there and only there. Opening an index built by a different
fingerprint marks it as needing a rebuild and leaves an empty, queryable index rather than
raising; a format bump invalidates rather than migrates.

## Consequences

### Positive

- "Find support for C0041" returns the evidence the researcher accepted, not the paragraph
  that shares its vocabulary — the behavior that makes the ladder worth having.
- Swapping embedding models is a directory change, nothing canonical moves (§5 P7), and the
  early stop makes the correct answer also the fast one.

### Negative / costs

- The weights are a fixed table per intent; only the inequality is tested, not the values.
- Per-fingerprint directories mean three embedding experiments keep three full indexes —
  194 MB each at the Task 17.3 corpus — and the dense index sits at its p95 budget already.

## Invariants this ADR protects

- Accepted research objects are queried before raw-vector retrieval, and no single index can
  promote raw prose over accepted state (§15.3, §43) — asserted for every intent.
- Changing the embedding model changes no Work, Evidence, Claim, Decision, or manuscript
  provenance (§5 P7, §42 C).
- The embedding provider and model live in index metadata, never in a canonical object
  (Task 5.2), and vectors built by one fingerprint are never queried through another.
- Deleting the vector index changes retrieval performance only.
- Retrieval responses expose source, location, authority, and score components (Task 5.4).

## Rejected alternatives

- **Rank by similarity and use authority only as a tiebreak.** The index decides in every
  case that is not an exact tie, which is nearly all of them.
- **Filter to accepted state and fall back only when empty.** Loses the parsed corpus where
  it is genuinely the right answer; the early stop gives the benefit without the loss.
- **Take authority from the index row.** The index can be behind, so a superseded object
  would keep the authority it had when indexed.
- **One semantic directory with the model recorded inside.** A model swap would mix vectors
  or need a migration; a fingerprinted path makes the mistake unreachable.

## Where it is enforced

- `src/research_harness/retrieval/rerank.py`: `AUTHORITY_SCORES`, `RERANK_WEIGHTS`,
  `RerankWeights.score`, `authority_score`.
- `retrieval/planner.py` (`LADDER`, `RetrievalHit.merged_with`), `retrieval/service.py`
  (`_Walk.above`, the early stop, `_object_states`), `retrieval/structured.py` (`Authority`).
- `retrieval/semantic.py` (`fingerprint_slug`, `semantic_index_dir`, `INDEX_VERSION`,
  `_inconsistency`) and `providers/models/embeddings.py` (`EmbeddingProvider.fingerprint`).
- Tests: `tests/unit/retrieval/` (`test_rerank.py` asserts the inequality, `test_planner.py`),
  `tests/integration/retrieval/test_semantic.py`, `tests/e2e/test_retrieval_gate.py`.
