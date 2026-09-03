# ADR-002: Work/Version/Artifact identity separation

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §7.1, §7.2, §9, §13, §14, §16, §42 D, §44.10; ROADMAP.md Global Constraints, Phase 2 Tasks 2.1–2.2 and 2.4, Gate P2, Task 14.2

## Context

A scholarly work is not a file. arXiv v1, arXiv v2, and the camera-ready version of the
same paper differ in page numbers, table contents, and wording; a work may also have an
HTML rendering, a supplement, a code archive, and a dataset document (PRODUCT.md §13).
Citations are about the work; evidence is about a span of bytes in one specific file.
Collapsing the two produces one of two failures: an evidence anchor silently survives a
revision that moved the text it points at, or every revision becomes a separate paper and
citation deduplication, snowballing, and coverage counting break.

## Decision

`Work`, `Version`, and `Artifact` are three distinct entities with distinct typed IDs
(`W####`, `V####`, `A####`) from the first schema version (PRODUCT.md §7.2).

Citations primarily reference `Work`. Evidence references the exact `Version` and
`Artifact` it was read from, with file hash, page, block, character offsets, and optional
bounding box (§9, §13). Artifacts are immutable once registered: a different revision
creates a new
Artifact under the same Work rather than overwriting the existing one. The identity
resolver reconciles DOI, arXiv ID, DBLP, Semantic Scholar, OpenAlex, title, authors,
venue, and year, reporting one of four distinct outcomes — `same_artifact`,
`same_version`, `same_work`, `distinct_work`.

## Consequences

### Positive

- A new revision does not invalidate citations; an anchor stays bound to its own bytes.
- Deduplication, snowballing, and coverage counting operate at Work level while provenance
  operates at Artifact level; screening states (§14) attach to Works alone.

### Negative / costs

- Almost every query and view carries a three-level join, and each surface must decide
  which level it displays.
- Identity resolution is a real problem, not a lookup: conflicting metadata must keep
  field-level provenance, ambiguous cases reach the researcher as review questions, and
  three ID families must stay stable across rebuilds.

## Invariants this ADR protects

- Every accepted Evidence object opens the exact source artifact and location it was
  accepted from — §42 D.
- `Evidence` cannot exist without a `Work`/`Version`/`Artifact` reference (Task 1.2), and
  re-ingesting identical bytes is idempotent while a different revision never silently
  overwrites the existing Artifact (Task 2.1).
- `same_artifact`, `same_version`, `same_work`, `distinct_work` are four distinct resolver
  outcomes (Task 2.2).
- A one-byte artifact change invalidates the artifact hash and prevents silent
  reattachment; the anchor becomes stale instead (Task 2.4, ADR-008). Identity resolution
  preserves field-level metadata provenance.

## Rejected alternatives

- **A single `Paper` entity keyed by DOI.** Loses which file a quote came from; fails for
  preprints and revisions that share or lack a DOI.
- **File as identity.** The same paper ingested twice becomes two papers, inflating
  prevalence and coverage counts.
- **Work plus Artifact only.** Leaves nowhere to record that arXiv v1 and the camera-ready
  are the same work but different citable revisions.
- **Identity by embedding similarity.** Non-deterministic and index-dependent, which
  ADR-006 forbids for state carrying scientific authority.

## Where it is enforced

- `src/research_harness/domain/`: `ids.py`, `work.py`, `document.py`, `evidence.py` — the
  schema makes a source-less Evidence object unconstructable. Also
  `ingest/hashing.py`, `ingest/service.py`, `ingest/identity.py`, `parsing/anchors.py`
  (anchor fingerprint), and `projection/schema.py` (separate tables, canonical IDs).
- Plugins may not collapse this identity (PRODUCT.md §32.5; ROADMAP.md Task 14.2).
- Tests: `tests/unit/domain/test_ids.py`, `tests/unit/ingest/test_identity.py`,
  `tests/integration/ingest/test_local_pdf.py`, `tests/unit/parsing/test_anchors.py`,
  Task 17.1 provenance invariant.
