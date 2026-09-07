---
target: "web cockpit: app shell, conversation workspace, research pages"
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 2
target_identity: "file:/mnt/virtual/repo/research-harness/.claude/worktrees/wave-3/web/src/app/Layout.tsx"
target_fingerprint: "sha256:2fb3f0342f6bd9401ce0dd1355303008fca576d9ca3ea670c46216a568c5fa29"
target_path: /mnt/virtual/repo/research-harness/.claude/worktrees/wave-3/web/src/app/Layout.tsx
timestamp: 2026-09-07T13-12-06Z
slug: src-app-layout-tsx
---
Method: dual-agent (A: design-review subagent · B: detector-and-browser subagent, isolated; A finished before B's findings entered synthesis)

Target: the web cockpit — app shell and projects home, conversation workspace, research pages — resolved to `web/src/app/Layout.tsx` on `wave-3` at `6a58545` (origin/main). Evidence: source, tokens and the task gate's real-browser captures (Assessment A); `impeccable detect --json` over `web/src` and `design/src` plus the browser detector injected on five routes at 1440×1000 dark and 768×1024 light against the real daemon (Assessment B).

## Design Health Score

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | "Look again" never says when it last looked; a blocked daemon empties the rail's counts and footer together |
| 2 | Match system / real world | 3 | Researcher vocabulary throughout, undercut by notice titles that open with their own kind ("Try again:", "Blocked:") and transcript telemetry (`scripted-1 attempt 1`) |
| 3 | User control and freedom | 2 | Forget confirms in an alertdialog; accepting restates and needs a second press; nothing offers undo, by product rule, so the outcome is only a toast |
| 4 | Consistency and standards | 3 | One token system; but screening states have no icon or description, and compact badge labels render at 10.2px (B: `--rh-type-label-size` × the compact scale), under the 12px floor the ramp declares |
| 5 | Error prevention | 3 | Safety statements, batch preview with its conditions, anchors required before promotion |
| 6 | Recognition rather than recall | 1 | Promote is an icon-only arrow; Synthesis makes you retype a field printed two panels above; half the inspector's tabs sit behind a chevron; "992 more are in the list below" |
| 7 | Flexibility and efficiency | 3 | Palette, shortcut keys with a help sheet, auto-advance, resizable panes; no per-row decision in the queue and Batch accept below every item |
| 8 | Aesthetic and minimalist design | 2 | ~350px of empty rail with no sessions; three helper strips under the composer; two empty inspector cards side by side; transcript prose has no measure cap (B: 114 characters at 1440) |
| 9 | Error recovery | 3 | The daemon-offline notice states cause, path, what is safe and the command — then the page repeats it beneath |
| 10 | Help and documentation | 2 | Empty states teach the ontology; nothing defines "Tier 2 — deep review", "Ambiguous extractions" or `strength: Direct` |
| **Total** | | **25/40** | **Acceptable — improving (20/40 on 2026-09-06)** |

## Design Specificity Verdict

**LLM assessment.** The product is specific where it writes and on one screen. No generic dashboard says "A staged proposal, beside the page it was read off. Nothing here is accepted state", or "An empty cell means 'not recorded', never 'absent'", or ends an overview with the id of the next decision it will record. The evidence-review screen — a scanned page with its anchor highlighted beside the proposal read off it — is the thesis made visible and could not be lifted into another product. The frame around it is still off-the-shelf: an eleven-item flat rail, a title bar, a card stack; and Corpus and Synthesis render scientific objects as key/value cards (ID / AUTHORS / YEAR / VENUE), the shape a CRM gives a contact. The product knows what it is; the composition mostly does not yet.

**Deterministic scan.** `impeccable detect --json` returns `[]` at exit 0 for both `web/src` (240 files) and `design/src` (401 files), with no ignore config in the tree; a control fixture returned six findings, so the engine works and the trees are genuinely clean of static patterns. The browser detector, injected successfully on all ten route × viewport runs with zero page errors, reported 44 real findings after discounting its own overlay (33 `dark-glow`/`text-occlusion` hits were the detector measuring itself): `cramped-padding` ×59 on badges and count chips — a measured condition standing against Badge.css's deliberate "height comes from the text" decision; `undersized-ui-text` ×4 — `.rh-badge--sm` at 11px × 0.929 = 10.2px inside `data-density="compact"` subtrees on Claims, a real gap (density.css checks only the body size against the floor); `line-length` ×3 — `.rh-md p` in the transcript at `max-width: none`, 798px, ~114 characters; `clipped-overflow-container` ×3 on the inspector pane — the standard flex containment idiom, benign until a child overflows; `monotonous-spacing` ×8 — the 4px base step of a documented scale, a weak signal.

**Visual overlays.** No native browser tool is exposed to this session, so no user-visible overlay tab was opened; annotated and clean captures of every route sit under `/tmp/critique-B/`.

## Overall Impression

The cockpit now respects the difference between a proposal and a fact everywhere it speaks, and every research page opens with the work rather than the size of the project. What it still lacks is a frame worthy of that content: the act the product exists for — deciding — sits below the fold, the act that creates scientific state — promoting — has no name on screen, and the rail treats eleven destinations as one list. The single biggest opportunity is to make the decision reachable at the moment of decision.

## What's Working

- **Safety is a component, not a paragraph.** `SafetyNote` on `ErrorNotice` renders "Your draft is safe. The source is unchanged." as structured UI in the outage and blocked states. It answers the actual fear — did the daemon dying eat my work? — before it is asked.
- **Empty states teach the ontology instead of apologising.** "A claim is what this project asserts, registered so that the strength it asks for can be held against the strength its evidence allows." Definition, then one next action: the cheapest onboarding in the product and the only one that exists.
- **The Overview obeys its brief literally.** It leads with "Waiting for a decision", puts "Since your last session" third and buries the counts in a closing sentence — next actions over vanity metrics, with no confidence number anywhere.

## Priority Issues

- **[P0] The decision is below the fold, and absent from the queue.** `EvidenceReview.tsx` renders Proposal → Number → Verification → Conflicts, then `Decide`; at 1024px height the Decide panel is off-screen (`review-decided.png`, `vocabulary-review.png`). The inbox has no per-item action and Batch accept sits after every card. **Why it matters:** an Operate surface whose purpose is deciding never shows its primary action at the moment of decision. **Fix:** pin the decision bar to the bottom of the right pane with the outcome line and Next inside it; move Batch accept into the queue toolbar beside the filters; give tier-1 queue cards a compact Accept / Defer / Reject row. **Suggested command:** /impeccable layout
- **[P1] The product's central act has no name on screen.** Promote — message to Note / Question / Claim candidate / Decision candidate — is a 16px `arrow-up-right` icon button between a labelled "Inspect" and an overflow (`message-overflow.png`). **Why it matters:** the one control that turns conversation into scientific state is the least legible thing in the transcript. **Fix:** a labelled secondary button, "Promote…", with the arrow as its icon; "Inspect" to the overflow. **Suggested command:** /impeccable clarify
- **[P1] The rail wastes a third of its height and asks eleven decisions at once.** The empty session list is `flex: 1 1 auto`, so ~350px of void opens above the nav (`rail-actions.png`); the eleven destinations are one flat list. **Why it matters:** the rail reads as broken at first glance and gives the four counted destinations no more weight than Taxonomy. **Fix:** cap the empty list at its content height now; the grouping itself is the open proposal in `docs/plans/2026-09-07-rail-grouping-proposal.md`, which waits for the researcher. **Suggested command:** /impeccable layout
- **[P2] Every notice announces its kind, and the outage says itself twice.** `ErrorNotice` opens each title with "Try again:", "Blocked:", "Information:"; during an outage the shell notice and the page's own "Try again: Waiting for the daemon" stack, with two retry buttons for one condition (`daemon-offline.png`). **Fix:** the kind moves to the icon's accessible name; while the daemon is out, the page keeps its last answer with a quiet "last read at …" instead of a second notice. **Suggested command:** /impeccable clarify
- **[P2] The inspector's six tabs are three tabs and a chevron.** The 22rem pane overflows its strip at every width; at 1920 the clipped label reads "ew inbox" (`inspector-1920.png`). **Fix:** wrapped or icon-first tabs with counts, or a select below the pane's minimum; widen the pane to 26rem. **Suggested command:** /impeccable adapt
- **[P2] Two measurable type defects the detector found.** Compact badge labels at 10.2px under the declared 12px reading floor; transcript prose with no measure cap at ~114 characters. **Fix:** floor the label role the way the table cell is floored (`max(…, --rh-type-reading-min-size)`), and put `--rh-measure-prose` on `.rh-md p` in the transcript as the research pages already do. **Suggested command:** /impeccable typeset

## Persona Red Flags

**Alex (power user):** the palette lists destinations with no shortcut hints and no visible actions group; no per-row decision in the queue; Batch accept needs a scroll past every item; Synthesis makes him retype `tokenization` instead of picking it; transcript rows carry `scripted-1 attempt 1` he cannot act on.

**Jordan (first-timer):** the projects home is one card in a void with no word about what a project is; eleven destinations at once; "Tier 2 — deep review", "Ambiguous extractions", `STRENGTH: Direct` and `ORIGIN: Source observed` are never defined on screen; Promote has no label; at 768 the collapsed bar never names the current page.

**A researcher returning after a week:** "Since your last session" is the right idea in the wrong slot — third card, five undifferentiated rows, no marker of what she decided against what the daemon did; "Look again" never says when it last looked; if the daemon is blocked on her return, the rail loses its counts and its footer, so the one screen that should orient her goes blank.

## Minor Observations

- Screening states (Discovered / Included / Excluded) are the only vocabulary without icons or descriptions, so they separate by tint in a thousand-row corpus.
- The anchor highlight in `vocabulary-review.png` bleeds past the cited cell over empty columns, implying a wider span than the evidence claims.
- "Sends to Codex CLI · default — leaves this machine for chatgpt.com" is a privacy disclosure styled as tertiary grey text under a keyboard hint.
- The inspector shows two stacked empty cards ("Nothing selected", "No receipt open") where one would do.
- The Overview's attention card mixes "waiting" and "clear" badges with the described status badges — three badge vocabularies in one card.
- Count chips in the rail and the inspector tabs have zero block padding against a 1px border (detector `cramped-padding`), a measured condition against a deliberate text-height rule.

## Questions to Consider

- If accepted state is the authority, why is the one surface that creates it — Decide — the one you scroll to find, while the metadata you cannot act on gets the fold?
- Corpus and Synthesis render scientific objects as key/value cards. What would they look like designed around the question a researcher brings — "which of these thousand works has nothing accepted from it?" — rather than around the shape of the record?
- Accepting a candidate already restates what it will write and asks for a second press. Why does it then resolve into a toast that opens with the word "Information:", and what would reassure at that moment instead?
