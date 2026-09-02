---
name: slr-writer
description: "Writes a publication-grade IEEE systematic literature review (SLR) / survey paper end-to-end. Pipeline: (1) build/reuse a paper corpus via my-literature-review + PRISMA screening; (2) construct the outline TOP-DOWN in four user-gated levels — L0 scope/RQ/taxonomy, L1 chapters, L2 subsections, L3 evidence-and-citation map; (3) deep-read the full PDF of every cited paper into evidence cards; (4) write each section in IEEEtran LaTeX (English), citing ONLY corpus papers with every claim traceable to an evidence card; (5) assemble the IEEEtran document with taxonomy figure, PRISMA flow diagram, comparison tables auto-built from the information matrix, generate refs.bib, compile with pdflatex/bibtex, and run a citation + claim-traceability check. Interaction in Vietnamese, paper text in English. Triggers on: viết review, viết survey, viết SLR, systematic literature review, survey paper, write review paper, slr-writer, viết bài tổng quan, related work chapter."
metadata:
  version: "1.0.0"
  last_updated: "2026-07-25"
  status: active
  depends_on: "my-literature-review, academic-paper-reviewer"
  task_type: open-ended
  data_access_level: raw
---

# slr-writer — Publication-Grade IEEE Systematic Literature Review Writer

Writes a full IEEE survey/SLR paper from a review title, top-down and user-gated, with PRISMA rigor and strict anti-hallucination discipline.

**Locked configuration for this vault** (from user decisions, override via flags):

| Dimension | Setting |
|-----------|---------|
| Output type | Standalone IEEE **survey/SLR for publication** (IEEEtran journal) |
| Methodology | **Formal PRISMA** — protocol, inclusion/exclusion, flow diagram with counts |
| Paper language | **English** |
| Interaction language | **Vietnamese** (all gates, questions, summaries) |
| Evidence depth | **Deep full-PDF read** of every cited paper (evidence cards) |
| PRISMA protocol source | reuse `literature-review-protocol.md` at the vault root (authoritative inclusion/exclusion, extraction fields, quality appraisal, synthesis themes) |

---

## Core Principles (non-negotiable)

1. **Top-down, gated.** The outline is built general → specific across four levels (L0→L3). **Each level is presented to the user in Vietnamese and must be explicitly confirmed before proceeding.** If the user rejects, revise that level and re-present; never advance on a silent pass.
2. **Cite only the corpus.** Every `\cite` must resolve to a paper in the collected corpus (`papers.json`). No invented references, ever.
3. **Every claim is traceable.** Each written sentence that asserts a fact/number must trace to an **evidence card** (deep read of that paper's PDF). Distinguish "author claims X" from "we verified X in the PDF". Numbers must be copied from the PDF, never estimated.
4. **Evidence before prose.** No section is written until its subsections have a confirmed L3 evidence map AND the mapped papers have evidence cards.
5. **Resumable.** Every gate result and artifact is persisted; the pipeline can stop and resume across sessions via `state.json`.

---

## Agent Team (6 agents)

| # | Agent | Role | Phase |
|---|-------|------|-------|
| 1 | `scope_taxonomy_agent` | L0: research questions, taxonomy/organizing axis, inclusion/exclusion, target venue & length | 2 |
| 2 | `outline_architect_agent` | L1 chapters, then L2 subsections (two separate gates) | 2 |
| 3 | `evidence_mapper_agent` | L3: bind each subsection → specific papers + per-paragraph claims; flag thin/uncovered cells | 2 |
| 4 | `deep_reader_agent` | Read the full PDF of every mapped paper → structured evidence card | 3 |
| 5 | `section_writer_agent` | Draft each section in IEEEtran LaTeX (EN) from evidence cards only | 4 |
| 6 | `assembler_checker_agent` | refs.bib, main.tex assembly, taxonomy + PRISMA figures, comparison tables, compile, consistency & traceability check | 1 (bib/PRISMA) + 5 |

---

## Orchestration Workflow

```
User: /slr-writer <review title>   [+ optional seed papers, constraints]
     │  derive <review-slug>; create slr-output/<slug>/; init state.json
     │
=== Phase 1: CORPUS + PRISMA ===
     │  If SLRW_CORPUS_DIR exists and is fresh → reuse it.
     │  Else → run /my-literature-review (Mode B, seeds = user's seeds) to produce:
     │     papers.json, information_matrix.md, grouping_by_*.md, research_gaps.md, pdfs/
     │  [assembler_checker_agent]:
     │     - Apply inclusion/exclusion from literature-review-protocol.md → PRISMA counts
     │       (identified → deduplicated → screened → eligibility → included)
     │     - Write 00_prisma.md (counts + reasons for exclusion) and figures/prisma.tex
     │     - Generate paper/refs.bib from papers.json (only INCLUDED papers)
     │  ** Present PRISMA summary + included-paper count to user (VI). Gate. **
     │
=== Phase 2: OUTLINE (top-down, 4 gates) ===
     │  L0 [scope_taxonomy_agent] → 01_scope.md
     │     RQs · taxonomy/organizing axis · inclusion-exclusion recap · target venue & length
     │     ** Gate: user confirms scope + taxonomy (this is the paper's spine). **
     │  L1 [outline_architect_agent] → 02_chapters.md
     │     Section list (I, II, III...) + one-paragraph intent per section
     │     ** Gate. **
     │  L2 [outline_architect_agent] → 03_subsections.md
     │     Subsection headings per section + bullet intents
     │     ** Gate. **
     │  L3 [evidence_mapper_agent] → 04_evidence_map.md
     │     Each subsection → {papers to cite (citation_keys), claim per paragraph}
     │     + coverage report: subsections with <2 sources, gaps from research_gaps.md not yet placed
     │     ** Gate: user confirms the citation plan; adjust until coverage is acceptable. **
     │
=== Phase 3: DEEP READ ===
     │  [deep_reader_agent] for every UNIQUE paper appearing in 04_evidence_map.md:
     │     read pdfs/<key>.pdf against the evidence-card schema →
     │     05_evidence_cards/<key>.md  (claims + exact numbers + page/section refs + quality rating)
     │  Papers with no OA PDF: card built from abstract + metadata, flagged "abstract-only —
     │     do not cite specific numbers", surfaced to user.
     │
=== Phase 4: WRITE (per-section, gated) ===
     │  For each section in outline order [section_writer_agent]:
     │     - Draft paper/sections/<NN>_<slug>.tex in English, IEEEtran
     │     - Use ONLY claims present in the relevant evidence cards; cite via \cite{key}
     │     - Insert \ref to comparison tables / figures where the L3 map calls for them
     │     ** Gate: present a Vietnamese summary of the drafted section + key claims for audit. **
     │
=== Phase 5: ASSEMBLE + CHECK ===
     │  [assembler_checker_agent]:
     │     - Build paper/main.tex (IEEEtran journal): title, abstract, keywords, \input sections
     │     - figures/taxonomy.tex (TikZ/forest from the L0 taxonomy)
     │     - tables/comparison_*.tex auto-generated from information_matrix.md
     │     - Compile: latexmk -pdf (bibtex) unless SLRW_SKIP_COMPILE
     │     - CHECK: every \cite has a bib entry & vice versa; every factual sentence maps to a
     │       card; PRISMA counts consistent; report unresolved items to user (VI)
     │  ** Present compiled PDF path + check report. **
```

---

## Output Directory Layout

```
slr-output/<review-slug>/
├── state.json                     ← which gates passed; resume point
├── 00_prisma.md                   ← PRISMA counts + exclusion reasons
├── 01_scope.md                    ← [L0 gated] RQs, taxonomy, criteria, target venue/length
├── 02_chapters.md                 ← [L1 gated] section list + intents
├── 03_subsections.md              ← [L2 gated] subsection headings + intents
├── 04_evidence_map.md             ← [L3 gated] subsection → papers + per-paragraph claims
├── 05_evidence_cards/
│   └── <citation_key>.md          ← deep full-PDF read per cited paper
└── paper/
    ├── main.tex                   ← IEEEtran journal document
    ├── refs.bib                   ← generated from papers.json (INCLUDED papers only)
    ├── sections/<NN>_<slug>.tex   ← one file per section (gated)
    ├── figures/taxonomy.tex, prisma.tex
    ├── tables/comparison_*.tex
    └── build/<slug>.pdf           ← compiled output + logs
```

---

## state.json schema

```json
{
  "review_title": "...",
  "review_slug": "...",
  "corpus_dir": "literature-review-output",
  "seeds": ["arxiv:2504.04222"],
  "gates": {
    "phase1_prisma": "confirmed",
    "L0_scope": "confirmed",
    "L1_chapters": "confirmed",
    "L2_subsections": "pending",
    "L3_evidence_map": "not_started"
  },
  "sections_written": ["01_introduction"],
  "deep_read_done": ["smith2024rag", "..."],
  "compiled": false
}
```

On invocation, read `state.json` if present and **resume at the first non-confirmed gate** rather than restarting.

---

## Trigger Conditions

**English:** write review, write survey, write SLR, systematic literature review, survey paper, related work chapter, slr-writer

**Tiếng Việt:** viết review, viết survey, viết SLR, viết bài tổng quan, viết chương tổng quan, tổng quan hệ thống

The user supplies a **review title** (and optionally seed papers + constraints). If no corpus exists yet, Phase 1 runs `my-literature-review` first.

---

## Environment Flags

| Flag | Effect |
|------|--------|
| `SLRW_OUTPUT_DIR=/path` | Override output dir (default `slr-output/<slug>`) |
| `SLRW_CORPUS_DIR=/path` | Reuse an existing my-literature-review output (default `literature-review-output`) |
| `SLRW_IEEE_MODE=journal\|conference` | IEEEtran document class option. Default: `journal` |
| `SLRW_SKIP_COMPILE=1` | Emit `.tex`/`.bib` but skip pdflatex/bibtex |
| `SLRW_DEEP_READ=0` | Fall back to matrix/abstract evidence instead of full-PDF cards (NOT recommended; default deep read on) |
| `SLRW_SECTION_GATE=0` | Draft all sections before review instead of per-section gates (faster, less control) |

---

## References

- `references/prisma_protocol.md` — how to reuse `literature-review-protocol.md` and build the PRISMA flow.
- `references/ieee_survey_structure.md` — IEEEtran setup + canonical survey section skeleton + table/figure conventions.
- `references/anti_hallucination_rules.md` — citation & claim-traceability discipline (enforced by every writing agent).
- `references/evidence_card_spec.md` — schema for deep-read evidence cards.

## Prerequisites

| Requirement | Required? | Notes |
|-------------|-----------|-------|
| `my-literature-review` skill | Required | Builds/refreshes the corpus (Phase 1) |
| MiKTeX / TeX Live (`pdflatex`, `bibtex`, `latexmk`) | Recommended | Verified present on this machine (MiKTeX). Without it, use `SLRW_SKIP_COMPILE=1` |
| `IEEEtran.cls` | Recommended | Ships with MiKTeX/TeX Live; auto-installed on first compile |
| Open-access PDFs in corpus | Strongly recommended | Deep reading needs full text; abstract-only papers are flagged and cannot support specific-number claims |
