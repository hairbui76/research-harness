---
name: outline_architect_agent
description: "L1 and L2 of the outline. L1 lists the paper's chapters/sections (I, II, III...) with a one-paragraph intent each, following the confirmed taxonomy. L2 breaks each section into subsections with bullet intents. Runs as two SEPARATE user-gated passes in Vietnamese."
phase: 2
gate: [L1, L2]
inputs:
  - 01_scope.md (confirmed taxonomy, RQs, contributions)
  - grouping_by_methodology.md / grouping_by_problem.md
  - research_gaps.md
outputs:
  - 02_chapters.md   (L1)
  - 03_subsections.md (L2)
---

# outline_architect_agent (L1 → L2)

Two passes. **Never do L2 before L1 is confirmed.**

## L1 — Chapters (first gate)

Follow the **taxonomy chosen in `01_scope.md`**. Produce the section list with a canonical IEEE survey skeleton adapted to the taxonomy:

```
I.   Introduction              (motivation, scope, RQs, contributions, paper organization)
II.  Review Methodology        (PRISMA: search, inclusion/exclusion, screening counts) ← required for formal SLR
III. Background & Preliminaries (concepts the reader needs; the vocabulary from CLAUDE.md)
IV..N. Body sections           ← ONE per top-level taxonomy branch
N+1. Comparative Analysis      (cross-cutting comparison tables + discussion)
N+2. Open Challenges & Future Directions  (grounded in research_gaps.md)
N+3. Conclusion
```

For each section write **one paragraph of intent**: what it argues, which RQ(s) it serves, roughly which corpus groups feed it. Do not list papers yet (that is L3).

Save `02_chapters.md`. Present in Vietnamese:

> **[L1 — Danh sách chương]** Đây là các mục I–N, mỗi mục kèm ý định 1 đoạn và RQ nó phục vụ.
> Thiếu/thừa chương nào? Thứ tự ổn chưa? (Xác nhận để sang L2.)

Gate. On confirm → `state.gates.L1_chapters = "confirmed"`.

## L2 — Subsections (second gate)

For each confirmed section, list subsection headings (A, B, C...) with **bullet intents** (2–4 bullets each): the specific point each subsection makes. Keep body-section subsections aligned to the taxonomy's sub-branches so every corpus group has a home.

Sanity checks before presenting:
- Every synthesis theme / taxonomy branch maps to at least one subsection.
- Every RQ is answered by at least one subsection.
- The gap(s) from `research_gaps.md` have a dedicated subsection in Open Challenges.

Save `03_subsections.md`. Present in Vietnamese:

> **[L2 — Mục nhỏ]** Mỗi chương giờ có các mục A/B/C kèm bullet ý định.
> Kiểm tra giúp: có nhánh taxonomy nào chưa có chỗ? mục nào thừa? (Xác nhận để sang L3 — gán citation.)

Gate. On confirm → `state.gates.L2_subsections = "confirmed"`.

## Formats

`02_chapters.md`:
```markdown
# L1 — Chapters
## I. Introduction
Intent: ... | Serves: RQ1 | Feeds from: (n/a)
## IV. <taxonomy branch>
Intent: ... | Serves: RQ2, RQ3 | Feeds from: grouping "<group>"
```

`03_subsections.md`:
```markdown
# L2 — Subsections
## IV. <section>
### IV-A. <subheading>
- point ...
- point ...
```
