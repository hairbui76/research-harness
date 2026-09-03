# ADR-011: Stored parse blocks are canonical, and regenerable from artifact bytes

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §8.1, §8.2, §15.4, §16, §42 (C, D); ROADMAP.md Phase 2 Tasks 2.3–2.4, Phase 3 Task 3.2, Task 17.1; implemented in `workspace/layout.py`, `workspace/repository.py`, `capabilities/handlers.py` (`work.store_blocks`), `parsing/anchors.py`

## Context

An Evidence anchor names an artifact, a page, a block id, character offsets, and a text
hash (§9, §16). Resolving one needs the parse that produced those block ids. Re-parsing on
every read costs seconds per artifact and puts PyMuPDF in every read path; keeping the
parse only in SQLite would put block ids, the things anchors point at, in a store ADR-001
says has no authority, so `rm -rf .research/` would break every anchor until a rebuild
happened to reproduce identical numbering.

## Decision

The parse is written beside the Work it belongs to, as JSON Lines:
`corpus/works/W####/parsed/A####-N.blocks.jsonl` (`WorkspaceLayout.blocks_file`). It is
canonical — Git-visible, inside the corpus tree, outside the `.research/` set
`is_regenerable` reports — and at the same time derived: reproducible from the immutable
artifact bytes by the parser named in its provenance.

`work.store_blocks` is the only writer, and it refuses a `ParsedDocument` whose
`file_hash` differs from the Artifact's, so a parse can never claim bytes it did not read.
`validate_anchor` compares that hash first and returns `stale` before looking at any block
(ADR-008). Block ids are positional (`BlockIdAllocator`), so identical bytes under an
identical parser version yield identical ids and a parser change may renumber them:
changing extraction behavior requires a parser version bump (ADR-022). Reading blocks back
is a replay surface, not a parse — `get_parsed_document` rebuilds a document under the
deliberate non-parser identity `stored-blocks@canonical`, never to be stored back.

## Consequences

### Positive

- An anchor resolves, and a source pane draws its bounding box, without opening the PDF —
  what makes `GET /blocks/{artifact_id}` and source-beside-decision review cheap.
- Deleting `.research/` costs no provenance, so §42 C and D do not depend on a rebuild
  reproducing parser output; a parser upgrade is a reviewable diff on the corpus.

### Negative / costs

- The corpus carries the parse as well as the file: 100,000 blocks is a real share of the
  186 MB canonical tree, and digesting those records is a measured cost (ADR-023).
- The hash check is load-bearing rather than defensive, and `stored-blocks@canonical` is a
  placeholder a reader can misread as a parser.

## Invariants this ADR protects

- Every accepted Evidence anchor opens the exact artifact and location it was accepted from
  — §42 D — and rebuilding from canonical files changes no anchor and no block id — §42 C.
- A stored parse names the bytes it read, or `work.store_blocks` refuses it; a document
  rebuilt from stored blocks is never fingerprinted or stored as a parse.
- Changed artifact bytes make an anchor `stale` and reattachment is never attempted
  (Task 2.4, ADR-002); `build_anchor` refuses a span the block does not contain.
- `document_fingerprint` excludes timestamps and `anchor_fingerprint` excludes work and
  version ids, so both follow the bytes rather than the catalogue.

## Rejected alternatives

- **Re-parse on every anchor resolution.** Slow, and it binds every read to the parser
  version installed today rather than the one that made the anchor.
- **Keep blocks only in SQLite.** Puts anchor targets in a store with no authority;
  deleting the projection would break accepted provenance.
- **Store the parse under `.research/`.** Same failure, and invisible in a diff.
- **Anchor on offsets into a whole-document text stream.** Impossible to reconcile after
  re-parse; §16 asks for structural blocks, tables included.

## Where it is enforced

- `src/research_harness/workspace/layout.py` (`parsed_dir`, `blocks_file`, `path_for`) and
  `workspace/repository.py` (`put_blocks`, `get_parsed_document`, `iter_parsed_documents`,
  `STORED_PARSER_NAME`).
- `capabilities/handlers.py`: `work.store_blocks` and `work.parse`, the only mutation path;
  `domain/document.py` makes a block naming another artifact unconstructable.
- `parsing/anchors.py` and `parsing/base.py` (`BlockIdAllocator`, `document_fingerprint`).
- Tests: `tests/unit/parsing/test_anchors.py`, `tests/unit/workspace/test_layout.py`,
  `tests/integration/parsing/test_document_ir.py`, `tests/e2e/test_rebuild.py`, and
  `tests/e2e/invariants/test_d_provenance.py`.
