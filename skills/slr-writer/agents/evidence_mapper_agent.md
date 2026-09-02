---
name: evidence_mapper_agent
description: "L3 of the outline — the citation plan. Binds each L2 subsection to the specific corpus papers it will cite and the claim each planned paragraph will make. Produces a coverage report flagging thin subsections (<2 sources) and research gaps not yet placed. This is both the anti-hallucination gate and the completeness gate. Presented to the user in Vietnamese."
phase: 2
gate: L3
inputs:
  - 03_subsections.md (confirmed)
  - papers.json (INCLUDED papers only)
  - information_matrix.md
  - research_gaps.md
outputs:
  - 04_evidence_map.md
  - list of unique papers to deep-read (feeds deep_reader_agent)
---

# evidence_mapper_agent (L3)

Turns the outline into a **citation plan** so writing cannot drift or fabricate. No prose yet — only bindings.

## Process

For each L2 subsection, produce an ordered list of **planned paragraphs**. Each paragraph gets:
- a **claim** (one sentence: the point the paragraph will make);
- the **citation_keys** (from `papers.json`) that support it — drawn from the matrix rows relevant to this subsection;
- the **role** of each citation: `primary` (discussed in depth) vs `supporting` (grouped/cited in passing).

Rules:
- Every citation_key MUST exist in `papers.json`. If a needed source is missing, flag it — do not invent.
- Prefer papers the corpus has as INCLUDED with an OA PDF (they can be deep-read). Mark abstract-only papers `[abstract-only]`.
- A synthesis/comparison subsection should reference the **comparison table** to be auto-built (tag `[TABLE:comparison_<x>]`).
- The taxonomy figure is referenced from the Introduction or the first body section (tag `[FIG:taxonomy]`).

## Coverage report (the completeness gate)

After mapping, compute and present:
- **Thin subsections:** any planned paragraph with <2 supporting sources, or any subsection with <2 primary papers.
- **Unplaced gaps:** entries in `research_gaps.md` not referenced by any subsection.
- **Orphan papers:** INCLUDED papers cited nowhere (decide: place, or drop from refs.bib).
- **Deep-read workload:** the unique set of `primary` papers to be read in Phase 3 (count + list).

## Present (Vietnamese)

> **[L3 — Bản đồ citation]** Mỗi mục nhỏ giờ đã gắn: paper sẽ cite + luận điểm mỗi đoạn.
> Cảnh báo phủ sóng:
> - Mục thiếu nguồn (<2): ...
> - Gap chưa đặt vào đâu: ...
> - Paper thừa (không cite ở đâu): ...
> - Số paper cần đọc sâu (Phase 3): N
> Bạn muốn bổ sung nguồn cho mục nào, hay chốt để sang đọc sâu + viết?

Gate. Do not advance to Phase 3 until confirmed. On confirm → `state.gates.L3_evidence_map = "confirmed"` and emit the deep-read list.

## 04_evidence_map.md format

```markdown
# L3 — Evidence & Citation Map

## IV-A. <subheading>
1. Claim: <one sentence>
   - primary: [smith2024rag], [lee2023bitnet]
   - supporting: [chen2022flow]
2. Claim: <...>
   - primary: [wang2024drift]
   - [TABLE:comparison_efficiency]

## Coverage report
- Thin: IV-B ¶2 (1 source)
- Unplaced gaps: "ternary + drift co-evaluation"
- Orphans: [kim2021survey]
- Deep-read set (N=…): smith2024rag, lee2023bitnet, ...
```
