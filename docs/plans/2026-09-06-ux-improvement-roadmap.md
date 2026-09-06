# UX improvement roadmap: the web cockpit

**Date:** 2026-09-06
**Instruction:** "Use Impeccable to improve UI/UX; create a roadmap and follow up autonomously; up to ten Opus subagents."
**Method:** Impeccable 4.2.1 (critique → fix → re-critique), executed by subagents in isolated
git worktrees with disjoint file ownership, integrated on `main` behind `pnpm run task:check`
(AGENTS.md). Never more than ten agents at once; never more than two visual inspection
passes per wave; the mechanical detector runs once per wave over the changed targets.

## Where we start

Critique snapshot: `web/.impeccable/critique/2026-09-06T16-27-46Z__src-app-layout-tsx.md`
(target `web/src/app/Layout.tsx`, surfaces: app shell and projects home, conversation
workspace, research pages). **Score 20/40, "Acceptable".** No browser automation was
available when it ran, so it worked from tokens, CSS, components and tests; the task gate's
Chromium runs now give later passes real screenshots.

| # | Heuristic | Score | Key issue |
|---|-----------|-------|-----------|
| 1 | Visibility of system status | 3 | States replace the page frame; inspector has no error branch; Skeleton unused |
| 2 | Match system / real world | 2 | Raw enums, raw byte counts, internal document citations in UI copy |
| 3 | User control and freedom | 2 | No undo; one-click Accept; one-click provider Remove; tab switch loses a draft |
| 4 | Consistency and standards | 2 | h1 at 13px and 28px; h4 smaller than body; three border widths |
| 5 | Error prevention | 2 | The irreversible action has the least ceremony; danger colour on the reversible one |
| 6 | Recognition rather than recall | 2 | Status descriptions authored and never rendered; ids typed from memory |
| 7 | Flexibility and efficiency | 1 | No shortcuts, palette, batch accept, search, filter or sort |
| 8 | Aesthetic and minimalist design | 2 | 182–232 character lines; stacked notice strips; eight controls per message |
| 9 | Error recovery | 3 | Good vocabulary; research pages collapse refusals |
| 10 | Help and documentation | 1 | No help affordance; empty states teach nothing |

Priority issues: **P0** PDF evidence highlights unreadable in the dark theme. **P1** Accept has
no ceremony and danger sits on Reject. **P1** Review costs one page load per candidate. **P1**
Loading, empty and error states destroy the page frame. **P2** The layout never checks
whether its content fits (prose measure, six inspector tabs in a 352px pane).

## Rules that bind every wave

- **Operate mode.** Scanability, consistency and the real usage scene outrank expression.
- **The design system is the incumbent world** (one warm ramp, a paper surface with its own
  ink tokens, an accent that never says whether a claim is true, six scientific status
  families). Waves 1 and 2 refine inside it; wave 3 changes page concepts inside it too.
- **Product rules that shape UX decisions.** The review queue's order is the server's and is
  scientific (PRODUCT §5 P8, §24.2); acceptance writes authority and there is no undo
  capability, so the ceremony happens before the write and nothing fakes an undo; strict
  human-in-the-loop; conversation transcripts never outrank accepted state.
- **Craft floor.** No coloured side borders above 1px, no gradient text, no kicker labels,
  no emoji as icons, no modal where inline confirmation works, skeletons not spinners,
  empty states that teach.
- **Verification.** One worktree per agent, disjoint file ownership, a new browser spec per
  agent under `browser-tests/`, `pnpm run task:check` with its own `TASK_BROWSER_PORT`,
  `pnpm run task:status` after the last edit. The PM merges on `main`, runs the gate again,
  runs the detector and the finish review, fixes in at most two batches, pushes.

## Wave 1: correctness (P0, P1, safety)

| Item | Critique | Playbook | Owner files | Done when |
|---|---|---|---|---|
| 1A PDF highlights readable in both themes | P0 | audit | `web/src/pdf/*`, design tokens and themes, `design/scripts/check-contrast.mjs` | Page ink over every highlight ≥ 4.5:1 in dark and light, gated by the contrast script |
| 1B Decision ceremony and alarm vocabulary | P1, H3, H5, Sam, Riley | harden | `web/src/components/ReviewActions*`, `design/src/research/ReviewDecisionBar/*`, `design/src/research/models.ts`, `design/src/states/ResearchState*`, `web/src/views/conversation/PromoteDialog*`, `web/src/app/settings/*`, `web/src/app/SettingsDialog.tsx` | Accept restates what it will write and needs a second press; danger is off Reject; decision descriptions are reachable; persistent states announce politely; provider Remove confirms; tab switches keep drafts |
| 1C Review throughput | P1, H7 | shape → build | `web/src/views/ReviewInbox*`, `web/src/views/EvidenceReview*`, `web/src/api/client.ts`, `web/src/app/commands/*`, `web/src/app/Layout.tsx` (wiring only), `scripts/browser_server.py` (test seeding) | Policy-gated batch accept, decide-and-next, search and filter that never reorder the server's groups, a shortcut layer and a command palette |
| 1D Frame-preserving states | P1, H1, H10 | clarify, onboard | `design/src/workspace/FullPageWorkspace/*`, `design/src/states/*` except ResearchState, `design/src/primitives/Skeleton/*`, `web/src/components/Feedback*`, the eight non-review research pages, `web/src/views/conversation/InspectorPane*`, `web/src/styles.css` | Every research page keeps its h1, description and toolbar in every state; loading is a skeleton; every empty state names a next action; the inspector has an error branch |

Integration: merge the four branches on `main`, run `pnpm run task:check`, run the detector
over `web/src` and `design/src`, run the Impeccable finish review against the critique,
fix in one batch, confirm with one more, push.

## Wave 2: language, type, layout, resilience

| Item | Critique | Playbook | Scope |
|---|---|---|---|
| 2E Copy and labels | H2, H6 | clarify | Human labels for `observed_subset`-style enums; `formatBytes` used; no "PRODUCT §24.2" or "ADR-008" in UI copy; the six status descriptions rendered where the status is shown; an evidence picker instead of a typed id in RelateForm |
| 2F Typography and density | H4, minor | typeset | One h1 scale across the cockpit; h4 not smaller than body; body floor above 12px; research tables not forced to 11.15px; icon buttons never below 24px; three border widths become tokens |
| 2G Layout and measure | P2, H8 | layout | Prose capped near 72ch while tables stay wide; inspector tabs that fit the pane; project actions consistent between the rail menu and Project Home; notice strips above the composer consolidated |
| 2H Resilience and coverage | Riley, minor | harden, adapt, audit | axe with contrast, landmark and heading rules on across the web tests; narrow-layout tests; container queries where the pane widths demand them; the corpus list virtualised past a few hundred works; offline state; dead tokens removed |
| 2I Egress visibility | Question 4 | shape → build | After the one-time disclosure, the composer keeps a quiet, persistent indication of where an unpublished message goes |

## Wave 3: research pages stop being generic

| Item | Critique | Playbook | Scope |
|---|---|---|---|
| 3J Proof page: Overview | Design specificity | shape → new-work (inside the incumbent world) → critique | Replace the stat-tile row with the research state that matters today (what is waiting, what is stale, what changed since the last session); this page proves the pattern before the rest follow |
| 3K Rollout | Design specificity | build | Corpus, Claims, Taxonomy, Stale, Questions, Conflicts and Synthesis leave the card-wrapped-table template where the table is not the right instrument; tables stay where they are |
| 3L Navigation grouping | Question 1 | shape | A proposal to group the rail's eleven destinations; built only after the researcher agrees |

## Wave 4: close the loop

Re-run the critique for the score trend, run `polish` over the touched path, close the
snapshot, and offer `impeccable document` to write DESIGN.md (the incumbent world is coded
but undocumented) and `impeccable init` for the PRODUCT.md schema migration the context
check reported. Neither of the last two runs without the researcher's yes.

## Needs the researcher

- The PRODUCT.md schema migration (`init`) and DESIGN.md generation (`document`).
- The rail regrouping (3L).
- Any change that adds or alters a scientific claim in UI copy.

## Status log

- 2026-09-06: critique recorded (20/40); wave 1 dispatched as four agents.
