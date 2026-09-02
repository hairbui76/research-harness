# IEEE Survey Structure & LaTeX Conventions

## Document class

```latex
\documentclass[journal]{IEEEtran}   % 'journal' for a survey; SLRW_IEEE_MODE overrides
\usepackage{cite,graphicx,amsmath,booktabs,url}
\usepackage{tikz}\usetikzlibrary{positioning,arrows.meta}
\usepackage[edges]{forest}          % taxonomy tree
```
Keep the preamble in `main.tex` only; section files are `\input` fragments with no preamble.

## Canonical survey skeleton (adapt to the chosen taxonomy)

```
I.   Introduction
     - motivation & why-now; scope; RQs; contributions (bulleted); paper organization
     - forward-reference the taxonomy figure (Fig. 1)
II.  Review Methodology (PRISMA)
     - databases, query strings, inclusion/exclusion, screening counts, PRISMA figure
III. Background & Preliminaries
     - the stable vocabulary (traffic tokenization, flow-level inference, ternary LLM, ...)
IV..N Body — ONE section per top-level taxonomy branch
     - each synthesizes across papers; ends with a mini take-away
X.   Comparative Analysis
     - comparison table(s); cross-cutting discussion tied to RQs
Y.   Open Challenges & Future Directions
     - grounded in research_gaps.md; this is where the survey's thesis lands
Z.   Conclusion
```

## Tables & figures

- **Comparison table** = the survey's backbone. Build from `information_matrix.md`. Use `booktabs` (`\toprule/\midrule/\bottomrule`). Columns: Ref · Problem · Method · Dataset · Key metric · Edge HW · Code. `--` for unreported. Label `\label{tab:comparison_<x>}`.
- **Taxonomy figure** with `forest`; root = survey topic, children = body sections, leaves = representative methods/papers. Label `\label{fig:taxonomy}`.
- Use `\citet`-style narrative sparingly; IEEEtran default is numeric `\cite{}`.

## Style

- Synthesize, don't enumerate: a paragraph compares several works around one claim, not "Paper A did X. Paper B did Y."
- Contributions of a *survey* = taxonomy + gap synthesis + research agenda (not new experiments).
- Abstract: 150–250 words — scope, what is reviewed, taxonomy, key gap, and what the reader gains.
- Keywords (`IEEEkeywords`): pull from the CLAUDE.md stable vocabulary.
