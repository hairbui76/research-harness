# ADR-022: The parser reconstructs and recovers, but never fabricates text

**Status:** Accepted
**Date:** 2026-09-03
**Source:** PRODUCT.md §16, §42 (D, E), §43 "Risk: Parser instability"; ROADMAP.md Phase 2 Tasks 2.3–2.4; `docs/architecture/domain-changelog.md` entry 12; `docs/plans/dogfood-2026-09-03.md` §3 and F6; implemented in `parsing/pymupdf_parser.py`, `parsing/quality.py`, `parsing/base.py`

## Context

Real publisher PDFs do not hand a parser text. They encode inter-word spaces as pen
positioning rather than space glyphs; they set `2` and `RELATED WORK` on one baseline, so a
heading looks like two lines of a paragraph; and they embed subsetted fonts whose codes are
displaced, so a title extracts as mojibake. Every repair tempts a guess, and a guessed
reading becomes an anchored, quotable fact — parser instability as scientific error.

## Decision

The parser is `pymupdf` version **1.1**. Three geometric repairs are made, one recovery is
made under proof, and nothing else is invented. **Spaces are geometry**: the extractor's own
space guessing is off, so the only rule that inserts a space is a gap wider than
`_SPACE_GAP_RATIO` (0.15) of the larger adjacent font size, on left-to-right lines. **Lines
are merged by baseline** when they agree within `_BASELINE_TOLERANCE` (0.25) of the font
size and the horizontal gap is within four ems. **A displaced font is recovered only when
the recovered text proves itself**: offsets are fitted per `(page, font)` over every
code-point shift within `OFFSET_LIMIT` (94), and accepted only when the shifted text scores
at least `RECOVERY_SCORE` (0.8) on a dictionary-free English plausibility measure *and* its
letter share does not fall — the guard against near-miss offsets that turn letters into
symbols. Ties break to the smallest shift, so nothing depends on iteration order.

**Text that no offset recovers keeps exactly the characters the extractor returned**, is
listed in `ParseDiagnostics.undecodable_blocks`, and never opens a section, so
`section_path` falls back to the last heading that could be read. Table cell text comes from
the table finder rather than the span pipeline, so a table in a displaced font is reported
undecodable rather than recovered, and diagnostics travel with the document in its
provenance note. Because 1.1 changes block text and may renumber blocks for bytes 1.0 parsed,
it is a new parser version and anchors taken under 1.0 must be revalidated.

## Consequences

### Positive

- Papers that extracted as character soup now yield quotable text, and the ones that do not
  say so: a `decodability:low` field is left empty rather than stored as mojibake.
- The plausibility test needs no dictionary, model, or network, so parsing stays
  deterministic, offline, and testable against synthetic PDFs from a cipher helper.

### Negative / costs

- The thresholds are tuned for English technical PDFs; another language gets no recovery,
  only an undecodable verdict — the safe direction, but not a neutral one.
- Bumping to 1.1 invalidated every anchor taken under 1.0 (ADR-008).

## Invariants this ADR protects

- The parser never invents a reading: text no validated offset recovers is kept verbatim and
  reported, so an anchor never quotes characters the source does not contain (§42 D).
- An undecodable line never opens a section, and an offset applies only to its own font.
- Table cell text is the table finder's, preserving row and column relationships (§16).
- Changing extraction behavior means a parser version bump (ADR-011), and a document parsed
  before diagnostics existed reports "none recorded" rather than being called clean.

## Rejected alternatives

- **Trust the extractor's spaces.** What 1.0 did; positioned text came back as
  `presentationlayer` and FTS could not match a term.
- **OCR the page when text looks wrong.** A second, non-deterministic reading of bytes that
  already contain a correct one, indistinguishable downstream.
- **Ask a model to repair mojibake.** A model-proposed reading anchored as a source quote is
  the origin collapse §42 E forbids.
- **Recover with one global offset, or drop undecodable blocks.** Fonts are page resources,
  and dropping blocks makes numbering depend on how well the fonts extracted.

## Where it is enforced

- `src/research_harness/parsing/pymupdf_parser.py`: `_is_gap`, `_merge_baseline_runs`,
  `_font_offsets`, `_recover_line`, `_is_heading`, `_read_tables`, `_diagnostics`.
- `parsing/quality.py` (`detect_offset`, `verify_offset`, `offset_qualifies`, `shift_text`,
  `assess_text`) and `parsing/base.py` (`BlockQuality`, `ParseDiagnostics`,
  `parse_provenance`, `diagnostics_summary`).
- `ingest/metadata.py` runs `assess_text` over the extracted title and authors (dogfood F6).
- Tests: `tests/unit/parsing/`, `tests/integration/parsing/test_publisher_quirks.py`.
