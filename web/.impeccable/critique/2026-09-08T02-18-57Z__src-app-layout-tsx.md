---
target: "web cockpit: app shell, conversation workspace, research pages"
total_score: 32
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/mnt/virtual/repo/research-harness/.claude/worktrees/wave-5/web/src/app/Layout.tsx"
target_fingerprint: "sha256:0b39b07c6143096b9eab9d2394d6b7c7f65566650e870c256cdfc764f1a9c764"
target_path: /mnt/virtual/repo/research-harness/.claude/worktrees/wave-5/web/src/app/Layout.tsx
timestamp: 2026-09-08T02-18-57Z
slug: src-app-layout-tsx
---
Method: dual-agent (A: design-review subagent · B: detector-and-browser subagent, isolated; A finished before B's findings entered synthesis)

Target: the web cockpit — app shell and projects home, conversation workspace, research pages — resolved to `web/src/app/Layout.tsx` on `wave-5` at `9c63e78` (origin/main, waves one to five). Evidence: source, DESIGN.md, the recorded product record and the task gate's real-browser captures (Assessment A); `impeccable detect --json` over `web/src` and `design/src`, a control fixture, and the browser detector injected on six routes at 1440×1000 dark and 768×1024 light against the real daemon with its own overlay removed before measuring (Assessment B).

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 4 | The composer is disabled on an open project with no reason at the control; the reason sits in the transcript's empty state |
| 2 | Match system / real world | 4 | "Assistant" and the raw metadata strip `M0002 … scripted-1 attempt 1` inside otherwise researcher vocabulary |
| 3 | User control and freedom | 3 | No route back from a review screen to the queue except Next; a provider-vs-provider conflict offers no action |
| 4 | Consistency and standards | 3 | "Start a session in the rail" names a button called "New session"; `included` screening wears the accepted green |
| 5 | Error prevention | 4 | Acceptance restates the write and needs a second press; reject requires a reason; nothing fakes an undo |
| 6 | Recognition rather than recall | 2 | Twenty-one vocabularies with written meanings, revealed by keyboard focus only |
| 7 | Flexibility and efficiency | 3 | Auto-advance off by default; no column sort on a thousand-row corpus; queue filters reset on every visit |
| 8 | Aesthetic and minimalist design | 3 | Project home ~80% empty canvas at 1440; four rows of chrome under the composer at 768; zero rows printed |
| 9 | Error recovery | 3 | The outage notice is exemplary; an unknown URL silently renders the Overview |
| 10 | Help and documentation | 3 | Every badge carries a definition, and only a keyboard can see it |
| **Total** | | **32/40** | **Good (20/40 on 2026-09-06, 25/40 on 2026-09-07)** |

## Design Specificity Verdict

**LLM assessment.** Product-specific, and unusually so. The claim no neighbouring product makes — the model may propose, only a persisted human decision creates authority — is drawn, not just written: the accent is quarantined to model activity and forbidden from tabs and status; the paper surface keeps its own ink inside the dark theme so a source page never inverts; the Conflicts page keeps both readings and prefers neither; Synthesis says an empty cell means "not recorded, never absent"; the rail's Waiting / The record / Outputs is this product's ontology. Strip the copy and the colour rules and the skeleton still would not transplant. Where it goes generic is at the edges: the project home is a recent-folders list any editor ships, the transcript a conventional chat column, the manuscript pane a stock editor with tabs. The centre is specific; the entrances are not.

**Deterministic scan.** `impeccable detect --json` returns `[]` at exit 0 for both `web/src` (243 files) and `design/src` (407 files), also with `--no-config`; a control fixture returned one finding at exit 2, so the engine works and the trees are genuinely clean — including against DESIGN.md's recorded scales, which the detector now reads. The browser detector, injected on twelve route × viewport runs with its own overlay removed before measuring, reports 82 `cramped-padding` hits — the small badges' 1px block padding, a deliberate rule the stylesheet states ("height comes from the text"), and the rail and inspector count chips with zero block padding against a 1px pill border — and four `clipped-overflow-container` hits that are false positives (visually-hidden screen-reader spans and a closed combobox panel, both intended). Nothing else.

**Visual overlays.** No native browser tool is exposed to this session, so no user-visible overlay tab was opened; annotated and clean captures of every route sit under `/tmp/critique-C/shots/`.

## Overall Impression

The cockpit now composes its thesis as well as it states it: every research page opens with the work, decisions carry their ceremony everywhere they are offered, the frame names where you are, and the record of the design system exists. What remains is at the doors and at the edges of reach: the product's largest body of accepted state has no page of its own, the source slips out from beside the decision at narrow widths, the twenty-one vocabularies explain themselves only to a keyboard, and the first screen a newcomer meets does not say what the product is. The single biggest opportunity is an Evidence index under The record.

## What's Working

- **The refusal and acceptance ceremony.** The confirmation restates the write, not the button — "The reason is recorded with the Work; nothing is accepted" — and appears inline, so the source stays on screen while you commit.
- **Empty states that teach the epistemics.** Each names the object, says why it might be absent, and offers one next action; "an empty cell means 'not recorded', never 'absent'" does more product work in nine words than a dashboard would in a screen.
- **The outage as a condition, not an interruption.** A polite status that names the restart command, states what is safe, offers one retry, heals itself, and removes the control that would fail.

## Priority Issues

- **[P1] Accepted evidence has no page.** `routes.tsx` defines `evidence/:evidenceId` but no index, and the rail's eleven destinations hold no Evidence entry; §26 lists Evidence between Corpus and Claims. **Why it matters:** the product's largest body of accepted state is unbrowsable — "what have I accepted from this corpus?" has no answer surface, and the review queue becomes a one-way valve. **Fix:** an `/evidence` index under The record between Corpus and Claims, filtered by work, status, strength and origin, opening with the same "needs a researcher" group the other record pages open with. **Suggested command:** /impeccable shape
- **[P1] At ≤1100px the source is not beside the decision.** The narrow review capture shows Proposal → Number → Verification → Decide with the source pane scrolled off-screen; the sticky Decide card is opaque and at 1440 bisects the `UNIT percent` row with no fade. **Why it matters:** §26 requires the exact source beside the decision, and the row the card happens to cut is the unit — the disagreement Conflicts is built around. **Fix:** below 1100px a persistent source strip (the quoted span and page) pinned above the Decide bar; a top fade and a "more above" affordance on the sticky card so no row is half-cut. **Suggested command:** /impeccable layout
- **[P2] Twenty-one vocabularies, definable only by keyboard.** `RESEARCH_VOCABULARIES` publishes every meaning; `StatusBadge` and `DescribedTerm` reveal it on focus alone, with no pointer affordance. Wave two chose focus-only so a pointer crossing a badge would never move the row under it; the cost is that a mouse user never learns what `Candidate`, `Unverified` or `Tier 2 — deep review` mean. **Fix:** a visible affordance (dotted underline, `cursor: help`) and the same sentence on hover and long-press, rendered where it cannot reflow the row (the full-width hint slot the review screen already uses). **Suggested command:** /impeccable clarify
- **[P2] The project home is anonymous and does not scale.** No product name on the first screen; the lead and its two buttons sit against ~80% empty canvas at 1440; at 768 an unbounded, unsearchable list where every row wears a constant "Available" badge. **Fix:** name the product; the lead under the title at prose measure with the buttons on their own row; a filter above the list; group by last opened; drop the badge except when a project is not available. **Suggested command:** /impeccable onboard
- **[P2] The conversation route's entrance is a disabled control.** With no session open the composer renders as an inviting field with an accent Send, disabled, while the transcript says "Start a session in the rail" and the rail's button says "New session"; four rows of chrome sit under the composer at 768. **Fix:** typing into the composer starts a session, or the disabled field becomes one "Start a session" button in the rail's words; the index notice collapses into the composer footer once read. **Suggested command:** /impeccable clarify
- **[P3] Two colour systems collide in one row.** `included` screening paints corpus membership in the accepted green one column from an Accepted count; `unverified` puts feedback amber beside the scientific `Candidate`. **Fix:** screening as neutral badges told apart by their glyphs; green reserved for accepted state. **Suggested command:** /impeccable colorize

## Persona Red Flags

**Alex (power user):** no column sort on Corpus; auto-advance off by default and below the Decide card's fold; no Evidence index to sweep; review-inbox filters reset on every visit.

**Jordan (first-timer):** the transcript's metadata strip of five machine tokens; `Candidate` and `Unverified` on one Claims row, both undefined to a mouse; "Tier 2 — deep review" in three places with no word on what tiers are; the disabled composer on arrival.

**A researcher returning after a week:** "Since your last session" is the third card down, below two cards that may both be empty; "Read at 08:43" states when the page read, not when the project changed; Conflicts says "Decide it in the review inbox" without a deep link; nothing records what she was in the middle of.

## Minor Observations

- An unknown URL silently renders the Overview; a stale bookmark shows a plausible wrong page.
- Manuscript's Save is enabled while the status reads "Saved"; "Source-to-PDF navigation is unavailable" occupies a permanent row.
- The Overview prints zero rows ("0 unsupported manuscript claims — nothing waiting here").
- The provider-vs-provider conflict offers no action where the candidate-vs-accepted one does.
- The review source pane's blank page block carries no caption saying it is a page image.
- Claims rows lead with id and status badges above the claim's sentence, so machine metadata outranks the assertion.
- The rail and inspector count chips have zero block padding against a 1px pill border (detector `cramped-padding`), against a text-height rule the stylesheet states.

## Questions to Consider

- If conversation is the product's front door, why is the composer the one control on it that cannot be used, and why does a button in the rail outrank the field the researcher is already looking at?
- Overview, Review inbox, Conflicts, Stale and Claims each open with a group answering "what needs a researcher". Five surfaces answer one question: which of them is the cockpit, and what are the other four for?
- The confidence number is banned and twenty-one vocabularies ship. Which of the twenty-one could be deleted tomorrow without a researcher noticing, and what does it cost that "Included" is the same green as "Accepted"?
