# Evidence Card Specification

One card per cited paper, at `05_evidence_cards/<citation_key>.md`. The card is the **only** source of facts the section writer may use.

## Required frontmatter-style header

```markdown
# Evidence Card: <citation_key>
pdf_available: true | false
citation_safe_numbers: true | false      # false if abstract-only
title: <full title>
authors: <first author et al.>
venue: <name> | year: <yyyy> | rank: <A*/A/.../Q1..Q4>
quality: high | medium | low
quality_condition: <cross-dataset | time-split | hw-benchmark | released code+data | real-world>
```

## Body sections

```markdown
## Problem / task
<one line>  [§1]

## Method
<≤2 sentences: architecture / algorithm / compression>  [§3]

## Claims (author-stated, unverified)
- claimed: "<paraphrase>"  [Abstract]

## Verified facts (copied from the PDF — value + unit + location)
- <metric> = <value><unit>   [Table N, §x.y, p.Z]
- dataset: <name> (<#flows/#samples>)   [§4.1]
- baselines: <list>          [Table N]
- edge hardware: <device>    [§5.1]
- latency/memory/energy: <value><unit>   [Table N]
- drift/generalization protocol: <random-split | cross-dataset | time-split | none>  [§4]

## Limitations (author-admitted)
- "<paraphrase>"  [§6]

## Usable-for (from 04_evidence_map.md)
subsections: [IV-A ¶1, V-B ¶2]
```

## Rules

- **Anchor everything.** Every verified fact carries a `[Table/§/p]` location. A fact without a location is not verified — move it to Claims or drop it.
- **`not reported`** is a valid, important value — record it so the writer knows not to invent one.
- **No synthesis on the card.** The card is raw facts; cross-paper comparison happens in the prose, not here.
- Keep it short enough to scan — this is a fact sheet, not a re-review. For a full 5-reviewer critique, that is a separate `academic-paper-reviewer` run.
```
