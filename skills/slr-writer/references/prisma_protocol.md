# PRISMA Protocol Reference

The authoritative protocol for this vault is **`literature-review-protocol.md`** at the vault root. Do not duplicate it — read and reuse it. It already defines: review question + subquestions, databases, search concepts/boolean queries, **inclusion criteria**, **exclusion criteria**, data-extraction fields, quality appraisal, and the 7 synthesis themes.

`slr-writer` uses it as follows:

| slr-writer step | Protocol section reused |
|-----------------|-------------------------|
| L0 research questions | Review Question + Subquestions |
| L0 scope in/out, PRISMA screening | Inclusion Criteria / Exclusion Criteria |
| Deep-read card fields | Data Extraction Fields |
| Card quality rating | Quality Appraisal (high/medium/low conditions) |
| L1/L2 body sections | Synthesis Plan (7 themes) as default taxonomy branches |
| Phase 5 deliverables | Target Outputs (PRISMA flow, evidence table, BibTeX) |

## PRISMA flow — four stages with counts

```
1. Identification: records from all sources (search_log.md per-source hits + snowball_log.md)
2. Screening:      after dedup → title/abstract screen → excluded (tally reasons)
3. Eligibility:    full-text assessed → excluded (tally reasons: no empirical eval, no edge
                   constraint, off-topic, no reproducible detail — from Exclusion Criteria)
4. Included:       final N used in the survey
```

Every arrow must carry an exact number. Exclusion reasons must tally to the difference between stages.

## prisma.tex (TikZ) skeleton

```latex
\begin{figure}[t]\centering
\begin{tikzpicture}[node distance=1.2cm,
  box/.style={draw,rounded corners,align=center,text width=6cm}]
\node[box] (id)  {Identification\\ $n=N_{id}$ records};
\node[box,below of=id] (sc) {Screening (after dedup $n=N_{dedup}$)\\ excluded $n=E_1$};
\node[box,below of=sc] (el) {Full-text eligibility $n=N_{ft}$\\ excluded $n=E_2$ (reasons)};
\node[box,below of=el] (in) {Included $n=N_{inc}$};
\draw[->](id)--(sc); \draw[->](sc)--(el); \draw[->](el)--(in);
\end{tikzpicture}
\caption{PRISMA flow of study selection.}\label{fig:prisma}
\end{figure}
```
