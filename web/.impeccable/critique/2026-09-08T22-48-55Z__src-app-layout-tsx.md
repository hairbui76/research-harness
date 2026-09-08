---
target: "web cockpit: app shell, conversation workspace, research pages"
total_score: 31
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 2
target_identity: "file:/mnt/virtual/repo/research-harness/.claude/worktrees/wave-6/web/src/app/Layout.tsx"
target_fingerprint: "sha256:c7fc892941aaa7b178c3c9e9c2083df6059c12a2eea19f3f2a7c380040021748"
target_path: /mnt/virtual/repo/research-harness/.claude/worktrees/wave-6/web/src/app/Layout.tsx
timestamp: 2026-09-08T22-48-55Z
slug: src-app-layout-tsx
---
Method: dual-agent (A: design-review subagent · B: detector-and-browser subagent, isolated; A finished before B's findings entered synthesis; A was not told the earlier scores)

Target: the web cockpit — app shell and projects home, conversation workspace, research pages, manuscript workspace — resolved to `web/src/app/Layout.tsx` on `wave-6` at `a4cce5e` (origin/main, waves one to six and the batch that answered wave six's finish review). Evidence: source, DESIGN.md, PRODUCT.md and the task gate's real-browser captures at 1440×1000 dark and 768×1024 light, plus the 1920 and 1024 layout captures (Assessment A); `impeccable detect --json` over `web/src` and `design/src`, with and without config, an HTML control fixture and a TSX/CSS control fixture, and the browser detector injected on six routes at both viewports against the real daemon (Assessment B).

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | The manuscript route at 768 states one state three ways: the header names `main.tex`, the tree says "No manuscript files yet", the editor says "Choose a file to open it" |
| 2 | Match system / real world | 4 | Domain language throughout; only "Number continues under the decision." speaks about layout instead of research |
| 3 | User control and freedom | 2 | Accept writes accepted state in one press, by design without undo, 8px from Reject in a row of six equal pills |
| 4 | Consistency and standards | 3 | Corpus prints `Readable: yes/no` as bare text where every peer field is a badge; the inspector's six tabs duplicate five rail destinations |
| 5 | Error prevention | 3 | Rejection demands a reason and anchor validity is shown before Accept — but the six-way Decide bar guards nothing |
| 6 | Recognition rather than recall | 3 | Rail counts and "Next: Method summary · W0001" are excellent; at ≤768 the rail and its counts collapse behind one icon |
| 7 | Flexibility and efficiency | 3 | The palette mirrors the rail with `g` chords; nothing in the chrome says it exists |
| 8 | Aesthetic and minimalist design | 2 | At 1920 a 1620px card holds a 530px paragraph over 800px of void; every queue row carries a ~55px blank band |
| 9 | Error recovery | 4 | The outage screen names what is safe, what self-heals, the one command and a retry — best in class |
| 10 | Help and documentation | 4 | Every empty state teaches its concept; the vocabularies define themselves in place for pointer, finger and keyboard |
| **Total** | | **31/40** | **Good (20/40 on 2026-09-06, 25/40 on 2026-09-07, 32/40 on 2026-09-08)** |

## Design Specificity Verdict

**LLM assessment.** This could not be another product. The rail's groups — Waiting / The record / Outputs — are an epistemic claim about research, not a menu; the footer's "Researcher — may accept" is a permission model rendered as furniture; the paper surface keeps its own ink inside the dark theme and carries multiply-blended anchor marks over the actual Table 1 the number was read off; "an empty cell means 'not recorded', never 'absent'" and the strength ladder `Requested L3 Field generalization / Allowed L0 Individual` do the work a lesser product would hand to a confidence percentage. §26's prohibitions hold: no model-confidence number anywhere, orange reserved for Send and model provenance, six status families each carrying a glyph and a word. The failure is no longer specificity of language but specificity of composition: under the vocabulary sits a generic three-pane shell that stops thinking above 1280px, and the page rhythm — panel, panel, panel — is the same whatever the page is for.

**Deterministic scan.** `impeccable detect --json` returns `[]` at exit 0 for `web/src` and `design/src`, also with `--no-config` (there is no config to suppress by). The engine is alive (`impeccable-engine 0.1.2`) and an HTML control fixture returned five findings at exit 2; a TSX/CSS control fixture with deliberate defects also returned `[]`, so the static pass has little rule coverage over this source and the browser pass is the load-bearing evidence. Injected on twelve route × viewport runs: 36 `cramped-padding` hits, all false positives — the small badges' 1px block padding and the count chips' border-width padding are stated rules, and the rendered inset measured 2–4px because of line-box leading; 2 `clipped-overflow-container` hits on the review inbox, false positives — every positioned descendant lies inside the shell's box and the three filters are native selects whose popups no overflow can clip; 1 `body-text-viewport-edge` on the conversation at 768, an accurate measurement of the composer's destination line at 13px from either edge, marginal for a one-line small-print string. Zero page errors on every route.

**Visual overlays.** No native browser tool is exposed, so no user-visible overlay tab was opened; annotated and clean captures of all six routes at both viewports sit under `/tmp/critique4-B/`.

## Overall Impression

The cockpit's language is finished; its composition is not. Every record page now opens with the work, the accepted state has its own page, the twenty-one vocabularies answer a pointer and a finger as well as a keyboard, the source stays beside the decision at every width, and the writing in the empty and failure states is the best in the product. What the fourth reading sees, once those are in place, is the frame around them: a canvas that spends its widest screens on empty cards, a decision bar that gives the one irreversible act the same weight as five reversible ones, an attention model that vanishes on the narrowest screen, and a wave-six repair — the reserved hint line — that traded a moving row for a visible hole. The single biggest opportunity is a composition that changes with the width and with the page's purpose.

## What's Working

- **The review screen honours §26 literally.** The actual page, on paper, with the accepted span marked, sits beside a restatement that names anchor validity, why the daemon staged it, and the number's unit, dataset and condition; the researcher never has to trust a summary.
- **Failure states designed better than most products' success states.** The outage screen and the "No LaTeX toolchain" panel share one shape — what is safe, what is not your fault, what recovers itself, the one action, a disclosure for the curious — and answer the anxiety before the question.
- **A vocabulary layer that teaches without a tour.** Dotted-underlined terms and empty states that define their own nouns put the teaching at the point of confusion rather than in a modal nobody reads.

## Priority Issues

- **[P0] The composition stops thinking above 1280px.** At 1920 a full-width card 1620px across holds a 530px paragraph and a link over ~800px of empty canvas; the conversation route gives a 1250px transcript one small card and a 400px inspector one small card; Synthesis ends at y=780 with 250px of dead space. **Why it matters:** the north star is dense and editorial, and on the widest screens this is the least dense interface in its category — prose is capped at measure, its containers are not, so every card reads as a mis-set frame. **Fix:** cap the route's content column at ~1100px and centre it, or make the width earn its keep: on Overview, "Waiting for a decision" as a full-width lead with "Claim health" and "Open questions" as a two-column band beneath; on the conversation route, the transcript at measure with the recovered width given to an always-visible context strip. **Suggested command:** /impeccable layout
- **[P1] The highest-stakes action is the flattest control on the screen.** Accept, Qualify, Edit, Reject, Defer and Request more evidence are six same-size pills in one row; Accept differs only by being primary; there is no confirmation and, by the product's own rule, no undo. **Why it matters:** irreversibility plus adjacency plus visual equality is the destructive-misclick set-up, and this one writes accepted scientific state. **Fix:** Accept alone on its own row under the restatement it agrees to, Qualify and Edit secondary beneath, Reject, Defer and Request more evidence behind one "Something else…" disclosure; after acceptance a persistent, dismissible receipt naming what was written and where to reverse it by hand. **Suggested command:** /impeccable shape
- **[P1] "Needs a researcher" does not scale with the problem it names.** A 1000-work backlog is headed by eight arbitrary links and "992 more are in the list below"; the ordered corpus does the same with 8 of 60. **Why it matters:** the panel is the cockpit's promise of next actions over vanity metrics, and at scale it degrades into the count-and-sample it was meant to replace. **Fix:** the panel's shape follows the count — under about five, list them; above, one sentence, one bulk action and a link that opens the list already filtered, never a truncated sample. **Suggested command:** /impeccable distill
- **[P2] Two visible layout defects in the review surface.** Every queue row carries a ~55px blank band between the tier line and the anchor — the line wave six reserved so a resting pointer's sentence cannot move the row's controls — and the Number and Verification cards are clipped mid-row under "Number continues under the decision." **Why it matters:** both read as rendering bugs; a reserved line that stays empty looks like a hole, and a card sliced through its own list looks like overflow, which the explanatory sentence confirms rather than repairs. **Fix:** reserve the hint's height on the group, not on each row, or render the sentence in a layer the scroll container does not clip; for the cut card, continue the overflowed rows below the Decide panel under their own heading, or let the panel scroll independently. **Suggested command:** /impeccable polish
- **[P2] At ≤768 the product loses its attention model.** The rail — and with it Review inbox 3, Conflicts 1, Stale 1 — collapses behind one unlabelled icon while a full-width mono path bar keeps a band at every width. **Why it matters:** the counts are the "what needs me" answer; hiding them on the narrowest screen inverts the priority, and the path spends the same space on a string nobody acts on. **Fix:** a compact attention strip in the narrow header (three glyph-and-count chips linking to the three queues); the path moves into the project menu. **Suggested command:** /impeccable adapt

## Cognitive Load

Five of eight fail: single focus (Overview's five co-equal panels; the manuscript's tree, tab row, nested tab row and audit list), chunking (The record holds five), visual hierarchy ("Waiting for a decision" and "Claim health" are the same card at the same weight), one thing at a time (the inbox's filtering, scoping, bulk-accepting and per-row deciding all live at once), and the working-memory bridge (the manuscript inspector at 1024 replaces the prose being audited, so a finding and the sentence it indicts are never co-visible). Decision points over four: the Decide bar (six verbs and the advance switch), the research inspector (six tabs wrapping to two rows, five reading 0), the inbox toolbar (five), the corpus attention group (eight links and "992 more"), the rail (sixteen targets in one column), and the manuscript header (five controls across three bands).

## Persona Red Flags

**Alex (power user):** review rows ~430px tall, two candidates per 1000px screen; Evidence's Strength and Origin columns read "Direct" and "Source observed" on every row, a third of the table on constants; the palette is unadvertised; no selection model in the queue beyond the pre-scoped routine batch.

**Jordan (first-timer):** an empty Overview is five consecutive "Nothing…" cards whose next actions are four phrasings of "Open the conversation to…"; the composer footer at 768 stacks four controls and four sentences so the egress disclosure sits at the same weight as "Research index not built"; nothing says a palette exists.

**A researcher returning after a week:** "Since your last session" is third, below two panels that on a quiet week both read "Nothing"; its rows are a flat chronology with no grouping by kind; the Overview says "Read at 04:53" while the project home says "Last opened 2026-09-08 21:51 UTC" — two clock formats one click apart.

## Minor Observations

- `Readable: yes/no` is bare lowercase text where every neighbouring field is a badge.
- The command palette has no scrim, so it reads as a floating card over a fully legible page.
- Save, Compile and Jump to PDF appear active with no file open on the manuscript route at 768.
- "Gone stale" carries a status badge in its panel header while "Waiting for a decision" carries none.
- The composer's destination line sits 13px from either edge at 768 (detector `body-text-viewport-edge`), 4px inside the transcript's gutter.
- The full-page workspace's toolbar badges still grow their header when a meaning is asked for — the same defect the reserved line repaired in rows, uncited by either assessment and logged by wave six's batch.
- The 11px label role sits under the 12px reading floor by DESIGN.md's documented exemption for metadata; reduced-motion is honoured in eight component stylesheets.

## Questions to Consider

- If accepted state is the authority and cannot be undone, why does accepting it look exactly like deferring it?
- The rail names three groups — Waiting, The record, Outputs — but every page is built from the same panel, table and chip. What would a Waiting page look like if it were designed as a queue rather than as a record with a queue printed on top?
- The empty states are the best writing in the product and the only place it teaches. Where does a researcher learn what "Tier 2" means on the day the queue is full?
