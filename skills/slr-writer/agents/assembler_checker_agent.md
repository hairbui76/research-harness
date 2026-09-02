---
name: assembler_checker_agent
description: "Two roles. Phase 1: apply PRISMA screening to the corpus (counts + exclusion reasons), draw the PRISMA flow figure, and generate refs.bib from papers.json. Phase 5: assemble main.tex (IEEEtran journal), build the taxonomy figure and comparison tables from the information matrix, compile with latexmk/pdflatex+bibtex, and run the citation + claim-traceability + PRISMA-consistency checks."
phase: [1, 5]
inputs:
  - papers.json, information_matrix.md, search_log.md, snowball_log.md
  - literature-review-protocol.md (inclusion/exclusion)
  - 01_scope.md, 04_evidence_map.md, 05_evidence_cards/*, paper/sections/*.tex
outputs:
  - 00_prisma.md, paper/figures/prisma.tex, paper/refs.bib   (Phase 1)
  - paper/main.tex, paper/figures/taxonomy.tex, paper/tables/comparison_*.tex, build/<slug>.pdf, check report (Phase 5)
---

# assembler_checker_agent

## PHASE 1 — PRISMA + refs.bib

### PRISMA counts
Using `literature-review-protocol.md` inclusion/exclusion criteria, classify every corpus paper:
```
Identification: N_identified (per-source hits from search_log.md + snowball_log.md)
   → after dedup: N_dedup
Screening:      N_screened  → excluded_title_abstract (with reason tally)
Eligibility:    N_fulltext  → excluded_fulltext (reason tally: no-eval, no-edge, off-topic, ...)
Included:       N_included
```
Write `00_prisma.md` (table of counts + exclusion-reason tallies) and `paper/figures/prisma.tex` (TikZ flow diagram, four stacked boxes with the counts).

### refs.bib
Generate `paper/refs.bib` from `papers.json`, **INCLUDED papers only**. Map fields:
- `@article` if journal, `@inproceedings` if conference/proceedings, `@misc` for arXiv-only.
- key = `citation_key`; include `title, author, year, booktitle/journal, doi, url`. For arXiv-only: `eprint`, `archivePrefix={arXiv}`.
- Do NOT emit entries for non-included papers (keeps \cite↔bib clean).

Present PRISMA summary to user (VI), gate on `phase1_prisma`.

## PHASE 5 — ASSEMBLE + CHECK

### Assemble
- `paper/main.tex`: IEEEtran, `\documentclass[journal]{IEEEtran}` (or `SLRW_IEEE_MODE`). Title from review title; `\author`; abstract (write from 01_scope contributions + key findings); `\begin{IEEEkeywords}` from CLAUDE.md vocabulary; `\input{sections/...}` in order; `\bibliographystyle{IEEEtran}` `\bibliography{refs}`.
- `paper/figures/taxonomy.tex`: TikZ/`forest` tree from the chosen taxonomy in `01_scope.md` (branches = body sections).
- `paper/tables/comparison_*.tex`: auto-build from `information_matrix.md`. Columns from the matrix (Problem · Method · Dataset · Metric · Edge-HW · Code). Rows = INCLUDED papers relevant to the table's subsection. Numbers pulled from evidence cards (verified only); `--` for `not reported`.

### Compile
Unless `SLRW_SKIP_COMPILE=1`, from `paper/`:
```
latexmk -pdf -bibtex -interaction=nonstopmode main.tex
```
Retry once on missing-package (MiKTeX auto-install). Move PDF to `build/<slug>.pdf`. Capture `main.log` warnings.

### Checks (report all, do not silently pass)
1. **Citation closure:** every `\cite{k}` has a `refs.bib` entry; every `refs.bib` entry is cited at least once (list orphans).
2. **Claim traceability:** for each numeric/factual sentence in `sections/*.tex`, confirm a matching value exists in some `05_evidence_cards/*.md`. List sentences with no backing card as **UNVERIFIED**.
3. **Abstract-only misuse:** flag any specific number cited to an `abstract-only` paper.
4. **PRISMA consistency:** `N_included` == number of distinct \cite keys? If body cites fewer, note which included papers went uncited (fine, but report).
5. **Compile health:** undefined references, missing citations, overfull boxes count.

Present a Vietnamese report:

> **[Assemble + Check]**
> - PDF: build/<slug>.pdf (X trang, Y refs)
> - Citation: đủ khớp / thiếu: ...
> - ⚠️ Câu chưa truy được về evidence card (UNVERIFIED): ...
> - ⚠️ Cite số cụ thể vào paper abstract-only: ...
> - Cảnh báo LaTeX: ...

Fix or surface every UNVERIFIED item before declaring the draft done. Set `state.compiled = true`.
